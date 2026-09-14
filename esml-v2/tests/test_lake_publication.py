from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from azure_esml.domain_layer.lake_publication import publication_plan, publish
from azure_esml.domain_layer.shared_lake import SharedLake
from ml_model_factory.lake_flow import publication, finish


class Blob:
    def __init__(self, container, name):
        self.container, self.name = container, name

    def upload_blob(self, content, overwrite=False, **kwargs):
        assert not overwrite
        if self.name in self.container.data:
            raise ResourceExistsError("exists")
        self.container.data[self.name] = content.read() if hasattr(content, "read") else content
        self.container.writes.append(self.name)
        return {"etag": "etag"}

    def download_blob(self):
        if self.name not in self.container.data:
            raise ResourceNotFoundError("missing")
        return SimpleNamespace(chunks=lambda: iter([self.container.data[self.name]]))

    def delete_blob(self, **kwargs):
        assert self.name.endswith(".publication-lock")
        del self.container.data[self.name]


class Container:
    def __init__(self):
        self.data, self.writes = {}, []

    def get_container_properties(self):
        return SimpleNamespace(public_access=None)

    def get_blob_client(self, name):
        return Blob(self, name)


def prepared(tmp_path):
    key = "mlops/v1/master/environments/dev/datasets/example/versions/v1"
    with publication(tmp_path, key) as staging:
        (staging / "data.csv").write_text("id,value\n1,3\n")
        finish(staging, {"kind": "test"})
    return publication_plan(tmp_path, [key], account_url="https://examplelake.blob.core.windows.net", container="lake3")


def test_publishes_actual_bytes_and_commit_marker_last_then_idempotently_reuses(tmp_path):
    plan = prepared(tmp_path)
    container = Container()
    assert publish(tmp_path, plan, container_client=container)["written"] == 2
    assert container.writes[-1].endswith("/_SUCCESS.json")
    assert publish(tmp_path, plan, container_client=container)["reused"] == 2


def test_conflicting_existing_content_is_not_overwritten(tmp_path):
    plan = prepared(tmp_path)
    container = Container()
    name = plan["publications"][0]["files"][0]["blob"]
    container.data[name] = b"other"
    with pytest.raises(ValueError, match="differs"):
        publish(tmp_path, plan, container_client=container)
    assert container.data[name] == b"other"
    assert not any(name.endswith("/_SUCCESS.json") for name in container.data)


def test_modified_plan_or_local_content_cannot_publish(tmp_path):
    plan = prepared(tmp_path)
    changed = deepcopy(plan)
    changed["target"] = "https://otherlake.blob.core.windows.net/lake3"
    with pytest.raises(ValueError, match="plan changed"):
        publish(tmp_path, changed, container_client=Container())
    (tmp_path / plan["publications"][0]["files"][0]["blob"]).write_text("changed")
    with pytest.raises(ValueError):
        publish(tmp_path, plan, container_client=Container())


def test_original_payload_filenames_need_not_be_lake_identifiers(tmp_path):
    key = "mlops/v1/master/environments/dev/datasets/docs/versions/v1"
    with publication(tmp_path, key) as staging:
        (staging / "notes with spaces.txt").write_text("original data")
        finish(staging, {"kind": "documents"})
    plan = publication_plan(tmp_path, [key], account_url="https://examplelake.blob.core.windows.net", container="lake3")
    container = Container()
    assert publish(tmp_path, plan, container_client=container)["written"] == 2
    assert container.data[key + "/notes with spaces.txt"] == b"original data"


def test_existing_commit_is_checked_before_uploading_any_new_payload(tmp_path):
    first = prepared(tmp_path / "first")
    container = Container()
    publish(tmp_path / "first", first, container_client=container)
    before = dict(container.data)
    key = first["publications"][0]["key"]
    with publication(tmp_path / "second", key) as staging:
        (staging / "data.csv").write_text("id,value\n1,3\n")
        (staging / "extra.csv").write_text("id,value\n2,4\n")
        finish(staging, {"kind": "test"})
    second = publication_plan(tmp_path / "second", [key], account_url="https://examplelake.blob.core.windows.net", container="lake3")
    with pytest.raises(ValueError, match="commit marker"):
        publish(tmp_path / "second", second, container_client=container)
    assert container.data == before


def test_shared_lake_domains_and_stream_checkpoint_stability():
    lake = SharedLake("spider-001", "dev")
    first = lake.areas(project="001", use_case="vision", dataset="images", version="v1",
                       run_id="run1", snapshot_id="s1", model_version="1", serving="streaming")
    later = lake.areas(project="001", use_case="vision", dataset="images", version="v2",
                       run_id="run2", snapshot_id="s2", model_version="2", serving="streaming")
    assert first["checkpoint"] == later["checkpoint"]
    assert first["output"] != later["output"]
    assert "/master/" in first["shared_silver"]
    assert first["project_in"].endswith("/datasets/images/versions/v1/in")
    assert all(first[name] for name in ("image_assets", "rag_chunks", "fine_tuning_snapshot", "online_capture"))


def test_atomic_publication_retries_only_bounded_windows_rename_errors(tmp_path, monkeypatch):
    original = Path.rename
    attempts = []
    def busy_once(source, target):
        if source.name.startswith(".publishing-"):
            attempts.append(source)
            if len(attempts) == 1:
                error = PermissionError("Transient file lock")
                error.winerror = 32
                raise error
        return original(source, target)
    monkeypatch.setattr(Path, "rename", busy_once)
    monkeypatch.setattr("ml_model_factory.lake_flow.time.sleep", lambda _: None)
    prepared(tmp_path)
    assert len(attempts) == 2
