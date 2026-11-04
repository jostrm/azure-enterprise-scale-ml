"""Offline immutable shared-lake ingestion using real local bytes."""

from pathlib import Path
import shutil
from uuid import uuid4

import pandas as pd
import pytest

from azure_esml.domain_layer.lake_ingestion import SharedLakeIngestion
from azure_esml.domain_layer.shared_lake import SharedLake
from ml_model_factory.config import load_json, write_json
from ml_model_factory.data import sha256
from ml_model_factory.lake import local_key_path
from ml_model_factory.lake_flow import file_inventory, verified_manifest


@pytest.fixture
def workdir():
    root = Path.cwd() / ".sli-tests"
    work = root / uuid4().hex[:12]
    work.mkdir(parents=True)
    yield work
    shutil.rmtree(work)
    if root.exists() and not any(root.iterdir()):
        root.rmdir()


@pytest.fixture
def loader(workdir):
    return SharedLakeIngestion(workdir / "lake", SharedLake("factory1", "dev"))


def payload(workdir, folder="source", files=None):
    directory = workdir / folder
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in (files if files is not None else {"table.csv": "id,value\n1,20\n2,30\n"}).items():
        path = directory.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return directory


def provenance(directory):
    return {
        "provider": "kaggle", "kind": "dataset", "slug": "owner/example", "version": 7,
        "license": "Explicit test fixture; not downloaded Kaggle data",
        "files": file_inventory(directory),
    }


def master(loader, version):
    return local_key_path(loader.root, loader.layout.master("example", version))


def test_initial_preserves_selected_files_and_raw_bronze(loader, workdir):
    source = payload(workdir)
    evidence = provenance(source)
    write_json(source / "provenance.json", evidence)
    result = loader.ingest("example", "v1", source, provenance=evidence)
    release = master(loader, "v1")
    manifest = verified_manifest(release)
    assert result["status"] == "committed"
    assert manifest["download_provenance_verified"] is True
    assert manifest["source_files"] == evidence["files"]
    assert not (release / "landing" / "provenance.json").exists()
    assert sha256(release / "landing" / "table.csv") == sha256(source / "table.csv")
    assert (release / "bronze" / "raw" / "table.csv").read_bytes() == (source / "table.csv").read_bytes()
    assert not (release / "bronze" / "data.parquet").exists()
    bronze = load_json(release / "bronze" / "source-index.json")
    assert bronze["byte_preserving"] is True and bronze["transformations"] == []
    assert load_json(release / "changes" / "manifest.json")["added"] == evidence["files"]
    assert load_json(release / "provenance.json") == evidence


def test_explicit_file_input_and_nested_kaggle_hash(loader, workdir):
    source = payload(workdir, files={"nested/train.csv": "id,value\n1,2\n"})
    result = loader.ingest("example", "v1", source / "nested" / "train.csv", provenance=provenance(source))
    assert result["manifest"]["source_files"] == {"train.csv": sha256(source / "nested" / "train.csv")}


def test_delta_retains_omitted_files_replaces_updates_and_deletes_only_new_release(loader, workdir):
    source = payload(workdir, files={
        "images/keep.bin": b"keep", "images/update.bin": b"old",
        "documents/delete.txt": "deleted by explicit request", "notes with spaces.txt": "hello",
    })
    evidence = {"provider": "local", "source": "test-fixture"}
    loader.ingest("example", "v1", source, provenance=evidence)
    previous_inventory = file_inventory(master(loader, "v1"))
    delta = payload(workdir, "delta", {"images/update.bin": b"new", "images/added.bin": b"added"})
    result = loader.ingest(
        "example", "v2", delta, provenance=evidence, mode="delta", previous_version="v1",
        deleted_files=("documents/delete.txt",),
        watermark={"start": "2026-09-13T00:00:00Z", "end": "2026-09-14T00:00:00Z"},
    )
    release = master(loader, "v2")
    assert (release / "landing" / "images" / "keep.bin").read_bytes() == b"keep"
    assert (release / "landing" / "images" / "update.bin").read_bytes() == b"new"
    assert (release / "landing" / "images" / "added.bin").read_bytes() == b"added"
    assert not (release / "landing" / "documents" / "delete.txt").exists()
    assert file_inventory(master(loader, "v1")) == previous_inventory
    assert (master(loader, "v1") / "landing" / "documents" / "delete.txt").exists()
    changes = load_json(release / "changes" / "manifest.json")
    assert set(changes["added"]) == {"images/added.bin"}
    assert set(changes["updated"]) == {"images/update.bin"}
    assert set(changes["deleted"]) == {"documents/delete.txt"}
    assert set(changes["unchanged"]) == {"images/keep.bin", "notes with spaces.txt"}
    assert changes["watermark"] == {"start": "2026-09-13T00:00:00Z", "end": "2026-09-14T00:00:00Z"}
    assert file_inventory(release / "changes" / "files") == file_inventory(delta)
    assert result["manifest"]["signature"]["previous_manifest_sha256"] == sha256(master(loader, "v1") / "_SUCCESS.json")


def test_idempotent_exact_retry_and_immutable_conflicting_retry(loader, workdir):
    source = payload(workdir)
    evidence = {"provider": "local"}
    loader.ingest("example", "v1", source, provenance=evidence)
    before = file_inventory(master(loader, "v1"))
    assert loader.ingest("example", "v1", source, provenance=evidence)["reused"]
    (source / "table.csv").write_text("id,value\n1,99\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Immutable"):
        loader.ingest("example", "v1", source, provenance=evidence)
    assert before == file_inventory(master(loader, "v1"))


def test_empty_and_redundant_delta_commit_no_change_audit(loader, workdir):
    source = payload(workdir)
    evidence = {"provider": "local"}
    initial = loader.ingest("example", "v1", source, provenance=evidence)
    empty = payload(workdir, "empty", {})
    for version, selected in (("v2", empty), ("v3", source)):
        result = loader.ingest(
            "example", version, selected, provenance=evidence, mode="delta", previous_version="v1",
        )
        assert result["status"] == "no_changes"
        assert result["manifest"]["source_files"] == initial["manifest"]["source_files"]
        assert not file_inventory(master(loader, version) / "changes" / "files")
        verified_manifest(master(loader, version))


def test_deletion_only_delta_can_publish_empty_snapshot(loader, workdir):
    source = payload(workdir)
    evidence = {"provider": "local"}
    loader.ingest("example", "v1", source, provenance=evidence)
    result = loader.ingest(
        "example", "v2", payload(workdir, "empty", {}), provenance=evidence, mode="delta",
        previous_version="v1", deleted_files=("table.csv",),
    )
    assert result["manifest"]["source_files"] == {}
    assert file_inventory(master(loader, "v2") / "landing") == {}
    assert (master(loader, "v1") / "landing" / "table.csv").is_file()


@pytest.mark.parametrize("field,value", [
    ("files", {}), ("files", {"table.csv": "0" * 64}), ("slug", ""),
    ("version", None), ("version", "latest"), ("kind", "unknown"), ("license", None),
])
def test_invalid_kaggle_provenance_rejected_without_publication(loader, workdir, field, value):
    source = payload(workdir)
    evidence = provenance(source)
    evidence[field] = value
    with pytest.raises(ValueError, match="Kaggle"):
        loader.ingest("example", "v1", source, provenance=evidence)
    assert not master(loader, "v1").exists()


@pytest.mark.parametrize("deleted", ["../outside", "/absolute", "C:/absolute", "nested\\file", ".", "a//b", "a/../b"])
def test_unsafe_deletions_rejected(loader, workdir, deleted):
    with pytest.raises(ValueError, match="relative|traversal|ambiguous"):
        loader.ingest("example", "v2", payload(workdir), provenance={"provider": "local"},
                      mode="delta", previous_version="v1", deleted_files=(deleted,))
    assert not master(loader, "v2").exists()


def test_missing_or_conflicting_deletions_and_changed_source_identity(loader, workdir):
    source = payload(workdir)
    evidence = {"provider": "local", "slug": "one"}
    loader.ingest("example", "v1", source, provenance=evidence)
    for deleted, match in [(("absent.csv",), "absent"), (("table.csv",), "both supplied")]:
        with pytest.raises(ValueError, match=match):
            loader.ingest("example", "v2", source, provenance=evidence, mode="delta",
                          previous_version="v1", deleted_files=deleted)
    with pytest.raises(ValueError, match="same source"):
        loader.ingest("example", "v2", source, provenance={**evidence, "slug": "two"},
                      mode="delta", previous_version="v1")


def test_tampered_previous_publication_rejected(loader, workdir):
    source = payload(workdir)
    evidence = {"provider": "local"}
    loader.ingest("example", "v1", source, provenance=evidence)
    (master(loader, "v1") / "landing" / "table.csv").write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="files changed"):
        loader.ingest("example", "v2", source, provenance=evidence, mode="delta", previous_version="v1")
    assert not master(loader, "v2").exists()


def test_source_mutation_during_copy_rolls_back(loader, workdir, monkeypatch):
    source = payload(workdir)
    original_copy = shutil.copy2

    def mutate_and_copy(src, dst, *args, **kwargs):
        Path(src).write_bytes(b"changed during capture")
        return original_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr("azure_esml.domain_layer.lake_ingestion.shutil.copy2", mutate_and_copy)
    with pytest.raises(ValueError, match="Source changed"):
        loader.ingest("example", "v1", source, provenance={"provider": "local"})
    assert not master(loader, "v1").exists()
    assert not list(loader.root.rglob("*.lock"))
    assert not list(loader.root.rglob(".publishing-*"))


def test_source_overlap_and_empty_initial_rejected(loader, workdir):
    empty = payload(workdir, "empty", {})
    with pytest.raises(ValueError, match="at least one"):
        loader.ingest("example", "v1", empty, provenance={"provider": "local"})
    for source in (workdir, loader.root, loader.root / "input"):
        with pytest.raises(ValueError, match="overlap"):
            loader.ingest("example", "v1", source, provenance={"provider": "local"})


def test_source_marker_is_data_not_silently_discarded(loader, workdir):
    source = payload(workdir, files={"_SUCCESS.json": '{"upstream":true}', "README.txt": "source documentation"})
    result = loader.ingest("example", "v1", source, provenance={"provider": "local"})
    assert set(result["manifest"]["source_files"]) == {"_SUCCESS.json", "README.txt"}
    assert (master(loader, "v1") / "landing" / "_SUCCESS.json").read_bytes() == (source / "_SUCCESS.json").read_bytes()
    verified_manifest(master(loader, "v1"))


def test_source_symlink_rejected(loader, workdir):
    source = payload(workdir)
    linked = workdir / "linked"
    try:
        linked.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    with pytest.raises(ValueError, match="links"):
        loader.ingest("example", "v1", linked, provenance={"provider": "local"})
    nested = source / "linked.csv"
    nested.symlink_to(source / "table.csv")
    with pytest.raises(ValueError, match="links"):
        loader.ingest("example", "v1", source, provenance={"provider": "local"})


def test_initial_and_delta_mode_requirements(loader, workdir):
    source = payload(workdir)
    for options in (
        {"mode": "append"}, {"previous_version": "old"}, {"deleted_files": ("file",)},
        {"mode": "delta"}, {"mode": "delta", "previous_version": "v1"},
    ):
        with pytest.raises(ValueError):
            loader.ingest("example", "v1", source, provenance={"provider": "local"}, **options)
    with pytest.raises(FileNotFoundError):
        loader.ingest("example", "v2", source, provenance={"provider": "local"},
                      mode="delta", previous_version="missing")


def test_raw_bronze_preserves_empty_tabular_input_but_silver_rejects(loader, workdir):
    source = payload(workdir, files={"empty.csv": "id,value\n"})
    loader.ingest("example", "v1", source, provenance={"provider": "local"})
    assert (master(loader, "v1") / "bronze" / "raw" / "empty.csv").read_bytes() == b"id,value\n"
    with pytest.raises(ValueError, match="records|nonempty"):
        silver(loader)
    assert not local_key_path(loader.root, loader.layout.product("example", "silver1")).exists()


def test_different_factory_cannot_reuse_master_publication(loader, workdir):
    source = payload(workdir)
    evidence = {"provider": "local"}
    loader.ingest("example", "v1", source, provenance=evidence)
    other = SharedLakeIngestion(loader.root, SharedLake("factory2", "dev"))
    with pytest.raises(ValueError, match="different source or scope"):
        other.ingest("example", "v1", source, provenance=evidence)


def table(workdir, name, records):
    path = workdir / f"{name}.parquet"
    pd.DataFrame(records).to_parquet(path, index=False)
    return path


def initial_rows(loader, workdir, *, watermark=None):
    frame = pd.DataFrame({"id": [1, 2, 3], "value": [10, 20, 30], "name": ["one", "two", "three"]})
    source = table(workdir, "initial", frame)
    loader.ingest_rows("example", "v1", source, provenance={"provider": "manual", "license": "test fixture"},
                       primary_key=["id"], watermark=watermark)
    return frame


def test_row_initial_and_keyed_cdc_create_real_snapshot_and_preserve_raw_changes(loader, workdir):
    before = initial_rows(loader, workdir)
    previous_hash = sha256(master(loader, "v1") / "_SUCCESS.json")
    changes = table(workdir, "delta", {
        "id": [1, 2, 4], "value": [11, None, 40], "name": ["ONE", None, "four"],
        "_operation": ["upsert", "delete", "upsert"],
    })
    result = loader.ingest_rows("example", "v2", changes, provenance={"provider": "manual"},
                                primary_key=["id"], previous_version="v1")
    release = master(loader, "v2")
    snapshot = pd.read_parquet(release / "landing" / "data.parquet").sort_values("id").reset_index(drop=True)
    expected = pd.DataFrame({"id": [1, 3, 4], "value": [11, 30, 40], "name": ["ONE", "three", "four"]})
    pd.testing.assert_frame_equal(snapshot, expected)
    pd.testing.assert_frame_equal(pd.read_parquet(master(loader, "v1") / "landing" / "data.parquet"), before)
    assert sha256(master(loader, "v1") / "_SUCCESS.json") == previous_hash
    assert sha256(release / "changes" / "files" / changes.name) == sha256(changes)
    changes_manifest = load_json(release / "changes" / "manifest.json")
    assert changes_manifest["added"] == [{"id": 4}]
    assert changes_manifest["updated"] == [{"id": 1}]
    assert changes_manifest["deleted"] == [{"id": 2}]
    assert changes_manifest["unchanged"] == 1
    assert result["path"] == loader.layout.master("example", "v2")
    assert result["state"] == "committed"
    assert result["manifest"]["signature"]["previous_manifest_sha256"] == previous_hash
    assert loader.ingest_rows(
        "example", "v2", changes, provenance={"provider": "manual"},
        primary_key=["id"], previous_version="v1",
    )["state"] == "reused"


@pytest.mark.parametrize("keys", [[1, 1], [1, None]])
def test_initial_row_primary_keys_must_be_unique_nonnull(loader, workdir, keys):
    source = table(workdir, "invalid", {"id": keys, "value": [1, 2]})
    with pytest.raises(ValueError, match="Primary keys"):
        loader.ingest_rows("example", "v1", source, provenance={"provider": "manual"}, primary_key=["id"])
    assert not master(loader, "v1").exists()


def test_row_sequence_selects_latest_and_rejects_ambiguous_ties(loader, workdir):
    initial_rows(loader, workdir)
    source = table(workdir, "ordered", {
        "id": [1, 1], "value": [15, 11], "name": ["last", "first"],
        "_operation": ["upsert", "upsert"], "seq": [5, 1],
    })
    options = {"provenance": {"provider": "manual"}, "primary_key": ["id"], "previous_version": "v1"}
    with pytest.raises(ValueError, match="unique"):
        loader.ingest_rows("example", "v2", source, **options)
    result = loader.ingest_rows("example", "v2", source, sequence_column="seq", **options)
    snapshot = pd.read_parquet(master(loader, "v2") / "landing" / "data.parquet")
    assert snapshot.loc[snapshot["id"] == 1, "value"].item() == 15
    assert "seq" not in snapshot
    assert load_json(master(loader, "v2") / "changes" / "manifest.json")["superseded_records"] == 1
    tied = table(workdir, "tied", {
        "id": [1, 1], "value": [11, 12], "name": ["first", "second"],
        "_operation": ["upsert", "upsert"], "seq": [1, 1],
    })
    with pytest.raises(ValueError, match="ties"):
        loader.ingest_rows("example", "v3", tied, sequence_column="seq", **options)
    assert result["state"] == "committed"
    assert not master(loader, "v3").exists()


@pytest.mark.parametrize("records,match", [
    ({"id": [1], "value": [20], "name": ["one"], "new": [1], "_operation": ["upsert"]}, "unexpected columns"),
    ({"id": [1], "value": [20], "_operation": ["upsert"]}, "every data column"),
    ({"id": ["1"], "value": [20], "name": ["one"], "_operation": ["upsert"]}, "dtype"),
    ({"id": [1], "value": [20.25], "name": ["one"], "_operation": ["upsert"]}, "lossy"),
    ({"id": [None], "value": [20], "name": ["one"], "_operation": ["upsert"]}, "null"),
    ({"id": [1], "value": [20], "name": ["one"], "_operation": ["insert"]}, "upsert/delete"),
    ({"id": [1], "value": [20], "name": ["one"]}, "upsert/delete"),
    ({"id": [99], "_operation": ["delete"]}, "absent"),
])
def test_row_cdc_schema_and_operations_reject_without_commit(loader, workdir, records, match):
    initial_rows(loader, workdir)
    source = table(workdir, "invalid", records)
    with pytest.raises(ValueError, match=match):
        loader.ingest_rows("example", "v2", source, provenance={"provider": "manual"},
                           primary_key=["id"], previous_version="v1")
    assert not master(loader, "v2").exists()
    verified_manifest(master(loader, "v1"))


def test_row_cdc_empty_and_redundant_requests_report_no_changes(loader, workdir):
    before = initial_rows(loader, workdir)
    records = before.copy()
    records["_operation"] = "upsert"
    for version, selected in (("v2", records.iloc[:0]), ("v3", records.iloc[[0]])):
        source = table(workdir, version, selected)
        result = loader.ingest_rows("example", version, source, provenance={"provider": "manual"},
                                    primary_key=["id"], previous_version="v1")
        assert result["status"] == "no_changes"
        actual = pd.read_parquet(master(loader, version) / "landing" / "data.parquet")
        pd.testing.assert_frame_equal(actual.sort_values("id").reset_index(drop=True), before)


def test_row_delete_only_snapshot_can_be_empty_then_repopulated(loader, workdir):
    initial_rows(loader, workdir)
    source = table(workdir, "delete", {"id": [1, 2, 3], "_operation": ["delete"] * 3})
    result = loader.ingest_rows("example", "v2", source, provenance={"provider": "manual"},
                                primary_key=["id"], previous_version="v1")
    assert result["manifest"]["rows"] == 0
    empty = pd.read_parquet(master(loader, "v2") / "landing" / "data.parquet")
    assert empty.empty and list(empty.columns) == ["id", "value", "name"]
    source = table(workdir, "repopulate", {"id": [4], "value": [40], "name": ["four"], "_operation": ["upsert"]})
    loader.ingest_rows("example", "v3", source, provenance={"provider": "manual"},
                       primary_key=["id"], previous_version="v2")
    assert len(pd.read_parquet(master(loader, "v3") / "landing" / "data.parquet")) == 1


def test_composite_primary_key_and_custom_operation(loader, workdir):
    source = table(workdir, "initial", {"group": ["a", "b"], "id": [1, 1], "value": [10, 20]})
    loader.ingest_rows("example", "v1", source, provenance={"provider": "manual"}, primary_key=["group", "id"])
    source = table(workdir, "delta", {"group": ["a"], "id": [1], "op": ["delete"]})
    loader.ingest_rows("example", "v2", source, provenance={"provider": "manual"},
                       primary_key=["group", "id"], operation_column="op", previous_version="v1")
    snapshot = pd.read_parquet(master(loader, "v2") / "landing" / "data.parquet")
    assert snapshot.to_dict("records") == [{"group": "b", "id": 1, "value": 20}]


def test_row_missing_parent_contract_drift_and_conflicting_replay(loader, workdir):
    initial_rows(loader, workdir)
    source = table(workdir, "delta", {"id": [1], "value": [15], "name": ["one"], "_operation": ["upsert"]})
    with pytest.raises(FileNotFoundError):
        loader.ingest_rows("example", "v2", source, provenance={"provider": "manual"},
                           primary_key=["id"], previous_version="absent")
    with pytest.raises(ValueError, match="primary key"):
        loader.ingest_rows("example", "v2", source, provenance={"provider": "manual"},
                           primary_key=["name"], previous_version="v1")
    loader.ingest_rows("example", "v2", source, provenance={"provider": "manual"},
                       primary_key=["id"], previous_version="v1")
    changed = pd.read_parquet(source)
    changed["value"] = 99
    changed.to_parquet(source, index=False)
    with pytest.raises(ValueError, match="Immutable"):
        loader.ingest_rows("example", "v2", source, provenance={"provider": "manual"},
                           primary_key=["id"], previous_version="v1")
    with pytest.raises(ValueError, match="ingest_rows"):
        loader.ingest("example", "v3", source, provenance={"provider": "manual"},
                      mode="delta", previous_version="v1")


@pytest.mark.parametrize("watermark", [
    {"start": "2026-09-13T00:00:00", "end": "2026-09-14T00:00:00"},
    {"start": "2026-09-13T00:00:00+02:00", "end": "2026-09-14T00:00:00+02:00"},
    {"start": "2026-09-14T00:00:00Z", "end": "2026-09-13T00:00:00Z"},
    {"start": "2026-09-13T00:00:00Z", "end": "2026-09-13T00:00:00Z"},
    {"start": "invalid", "end": "2026-09-14T00:00:00Z"},
    {"sequence": 1},
])
def test_invalid_watermarks_fail_before_commit(loader, workdir, watermark):
    with pytest.raises(ValueError, match="watermark"):
        loader.ingest("example", "v1", payload(workdir), provenance={"provider": "manual"}, watermark=watermark)
    assert not master(loader, "v1").exists()


@pytest.mark.parametrize("row_mode", [False, True])
def test_watermark_advances_only_in_contiguous_committed_versions(loader, workdir, row_mode):
    first = {"start": "2026-09-13T00:00:00Z", "end": "2026-09-14T00:00:00Z"}
    second = {"start": first["end"], "end": "2026-09-15T00:00:00Z"}
    gap = {"start": "2026-09-16T00:00:00Z", "end": "2026-09-17T00:00:00Z"}
    if row_mode:
        records = initial_rows(loader, workdir, watermark=first).iloc[:0]
        records["_operation"] = pd.Series(dtype="object")
        source = table(workdir, "delta", records)
        ingest = loader.ingest_rows
        options = {"primary_key": ["id"]}
    else:
        loader.ingest("example", "v1", payload(workdir), provenance={"provider": "manual"}, watermark=first)
        source = payload(workdir, "empty", {})
        ingest, options = loader.ingest, {"mode": "delta"}
    with pytest.raises(ValueError, match="contiguous"):
        ingest("example", "v2", source, provenance={"provider": "manual"},
               previous_version="v1", watermark=gap, **options)
    assert not master(loader, "v2").exists()
    assert verified_manifest(master(loader, "v1"))["watermark"] == first
    result = ingest("example", "v2", source, provenance={"provider": "manual"},
                    previous_version="v1", watermark=second, **options)
    assert result["status"] == "no_changes"
    assert result["manifest"]["watermark"] == second
    result = ingest("example", "v3", source, provenance={"provider": "manual"}, previous_version="v2", **options)
    assert result["manifest"]["watermark"] == second


def silver(loader):
    return loader.publish_silver(
        "example", "v1", "silver1", required_columns=["id", "value"], owner="dataset-team",
        allowed_projects=("001", "002"), primary_key=("id",),
        table_format="parquet",
    )


def test_shared_silver_reused_by_two_projects_and_raw_master_onboarding(loader, workdir):
    source = payload(workdir)
    loader.ingest("example", "v1", source, provenance=provenance(source))
    product = silver(loader)
    product_root = local_key_path(loader.root, product["path"])
    contract = load_json(product_root / "contract.json")
    assert contract["owner"] == "dataset-team"
    assert contract["allowed_projects"] == ["001", "002"]
    assert contract["learned_preprocessing"] is False
    assert contract["transformations"] == []
    assert contract["source_manifest_sha256"] == sha256(master(loader, "v1") / "_SUCCESS.json")
    assert (product_root / "silver" / "MLTable").is_file()
    assert silver(loader)["state"] == "reused"
    for project in ("001", "002"):
        result = loader.onboard(project, "example", "input1", source_version="v1",
                                source_kind="silver", product_version="silver1")
        project_root = local_key_path(loader.root, result["path"])
        assert file_inventory(project_root / "in") == file_inventory(product_root / "silver")
        assert load_json(project_root / "source-binding.json")["contract_sha256"] == sha256(product_root / "contract.json")
        assert loader.onboard(project, "example", "input1", source_version="v1",
                              source_kind="silver", product_version="silver1")["state"] == "reused"
    with pytest.raises(ValueError, match="not approved"):
        loader.onboard("003", "example", "input1", source_version="v1", source_kind="silver", product_version="silver1")
    raw = loader.onboard("003", "example", "raw1", source_version="v1")
    assert file_inventory(local_key_path(loader.root, raw["path"]) / "in") == file_inventory(master(loader, "v1") / "landing")
    assert raw["state"] == "committed"


def test_silver_requires_schema_owner_and_explicit_project_approval(loader, workdir):
    loader.ingest("example", "v1", payload(workdir), provenance={"provider": "manual"})
    base = {"required_columns": ["id"], "owner": "owner", "allowed_projects": ("001",)}
    for changed in (
        {"required_columns": ["missing"]}, {"required_columns": []}, {"owner": ""},
        {"allowed_projects": ()}, {"allowed_projects": ("1",)}, {"primary_key": ("absent",)},
    ):
        with pytest.raises(ValueError):
            loader.publish_silver("example", "v1", "silver1", **{**base, **changed})
    assert not local_key_path(loader.root, loader.layout.product("example", "silver1")).exists()
    source = payload(workdir, "duplicate", {"table.csv": "id,value\n1,2\n1,3\n"})
    loader.ingest("example", "v2", source, provenance={"provider": "manual"})
    with pytest.raises(ValueError, match="unique"):
        loader.publish_silver("example", "v2", "silver1", **base, primary_key=("id",))


def test_silver_does_not_claim_opaque_files_are_valid_tabular(loader, workdir):
    source = payload(workdir, files={"images/a.bin": b"image bytes", "documents/a.jsonl": '{"a":1}\n'})
    loader.ingest("example", "v1", source, provenance={"provider": "manual"})
    with pytest.raises(ValueError, match="CSV or only Parquet"):
        silver(loader)


def test_silver_and_binding_immutable_scope_and_source_version_checks(loader, workdir):
    source = payload(workdir)
    loader.ingest("example", "v1", source, provenance={"provider": "manual"})
    silver(loader)
    with pytest.raises(ValueError, match="Immutable"):
        loader.publish_silver("example", "v1", "silver1", required_columns=["id"],
                              owner="other", allowed_projects=("001",))
    for project, options in (
        ("1", {"source_version": "v1"}),
        ("001", {"source_version": "v1", "source_kind": "silver"}),
        ("001", {"source_version": "v2", "source_kind": "silver", "product_version": "silver1"}),
        ("001", {"source_version": "v1", "source_kind": "unknown"}),
        ("001", {"source_version": "v1", "product_version": "silver1"}),
    ):
        with pytest.raises(ValueError):
            loader.onboard(project, "example", "input1", **options)
    loader.onboard("001", "example", "input1", source_version="v1")
    with pytest.raises(ValueError, match="Immutable"):
        loader.onboard("001", "example", "input1", source_version="v1", source_kind="silver", product_version="silver1")
    other = SharedLakeIngestion(loader.root, SharedLake("otherfactory", "dev"))
    with pytest.raises(ValueError, match="scope"):
        other.onboard("001", "example", "input2", source_version="v1", source_kind="silver", product_version="silver1")


def test_product_tampering_rejected_before_project_copy(loader, workdir):
    loader.ingest("example", "v1", payload(workdir), provenance={"provider": "manual"})
    product = silver(loader)
    product_root = local_key_path(loader.root, product["path"])
    (product_root / "silver" / "data.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="files changed"):
        loader.onboard("001", "example", "input1", source_version="v1", source_kind="silver", product_version="silver1")
    assert not local_key_path(loader.root, loader.layout.project("001", "example", "input1")).exists()


def test_exclusive_publication_lock_is_not_overwritten(loader, workdir):
    source = payload(workdir)
    destination = master(loader, "v1")
    destination.parent.mkdir(parents=True)
    lock = destination.with_name(destination.name + ".lock")
    lock.write_text("another publisher", encoding="utf-8")
    with pytest.raises(FileExistsError):
        loader.ingest("example", "v1", source, provenance={"provider": "manual"})
    assert lock.read_text(encoding="utf-8") == "another publisher"
    assert not destination.exists()


def test_transient_windows_commit_rename_is_retried_transactionally(loader, workdir, monkeypatch, caplog):
    original_rename = Path.rename
    denied = []

    def rename_once_denied(path, target):
        if path.name.startswith(".publishing-") and not denied:
            denied.append(path)
            error = PermissionError("transient Windows scanner lock")
            error.winerror = 5
            error.filename = str(path)
            error.filename2 = str(target)
            raise error
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", rename_once_denied)
    result = loader.ingest("example", "v1", payload(workdir), provenance={"provider": "manual"})
    assert result["state"] == "committed"
    assert denied
    assert result.get("publication_retries", 0) >= 1 or "Publication rename is temporarily blocked" in caplog.text
    assert not denied[0].exists()
    verified_manifest(master(loader, "v1"))
    assert not list(loader.root.rglob("*.lock"))


def test_row_source_mutation_during_capture_rolls_back(loader, workdir, monkeypatch):
    source = table(workdir, "initial", {"id": [1], "value": [20]})
    original_copy = shutil.copy2

    def mutate_and_copy(src, dst, *args, **kwargs):
        Path(src).write_bytes(b"changed")
        return original_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr("azure_esml.domain_layer.lake_ingestion.shutil.copy2", mutate_and_copy)
    with pytest.raises(ValueError, match="Source changed"):
        loader.ingest_rows("example", "v1", source, provenance={"provider": "manual"}, primary_key=["id"])
    assert not master(loader, "v1").exists()


def test_row_kaggle_checksums_and_licence_are_preserved(loader, workdir):
    directory = payload(workdir)
    evidence = provenance(directory)
    result = loader.ingest_rows("example", "v1", directory / "table.csv", provenance=evidence, primary_key=["id"])
    assert result["manifest"]["download_provenance_verified"]
    assert load_json(master(loader, "v1") / "provenance.json")["license"] == evidence["license"]
    (directory / "table.csv").write_text("id,value\n1,999\n", encoding="utf-8")
    with pytest.raises(ValueError, match="provenance hash"):
        loader.ingest_rows("example", "v2", directory / "table.csv", provenance=evidence, primary_key=["id"])


def test_shared_silver_multifile_tabular_schema_validation(loader, workdir):
    source = payload(workdir, files={"a.csv": "id,value\n1,20\n", "nested/b.csv": "id,value\n2,30\n"})
    loader.ingest("example", "v1", source, provenance={"provider": "manual"})
    result = silver(loader)
    frame = pd.read_parquet(local_key_path(loader.root, result["path"]) / "silver" / "data.parquet")
    assert frame.to_dict("records") == [{"id": 1, "value": 20}, {"id": 2, "value": 30}]
    bad = payload(workdir, "drift", {"a.csv": "id,value\n1,20\n", "b.csv": "id,other\n2,30\n"})
    loader.ingest("example", "v2", bad, provenance={"provider": "manual"})
    with pytest.raises(ValueError, match="column set"):
        loader.publish_silver("example", "v2", "silver2", required_columns=["id"], owner="owner", allowed_projects=("001",))


def test_master_onboarding_preserves_opaque_formats_and_names(loader, workdir):
    source = payload(workdir, files={
        "images/my image.bin": b"pixels", "documents/review.jsonl": '{"query":"test"}\n',
        "annotations/labels.json": '{"labels":[]}',
    })
    loader.ingest("example", "v1", source, provenance={"provider": "manual"})
    result = loader.onboard("001", "example", "input1", source_version="v1")
    assert file_inventory(local_key_path(loader.root, result["path"]) / "in") == file_inventory(source)


def test_row_numeric_schema_alignment_never_rounds_large_integers(loader, workdir):
    source = table(workdir, "initial", {"id": [1], "value": [1.5]})
    loader.ingest_rows("example", "v1", source, provenance={"provider": "manual"}, primary_key=["id"])
    changes = table(workdir, "delta", {"id": [1], "value": [2**53 + 1], "_operation": ["upsert"]})
    with pytest.raises(ValueError, match="lossy"):
        loader.ingest_rows("example", "v2", changes, provenance={"provider": "manual"},
                           primary_key=["id"], previous_version="v1")
    assert not master(loader, "v2").exists()


@pytest.mark.parametrize("method", ["rows", "silver"])
def test_csv_duplicate_headers_are_rejected_not_silently_renamed(loader, workdir, method):
    source = payload(workdir, files={"table.csv": "id,value,value\n1,2,3\n"})
    with pytest.raises(ValueError, match="column names"):
        if method == "rows":
            loader.ingest_rows("example", "v1", source / "table.csv",
                               provenance={"provider": "manual"}, primary_key=["id"])
        elif method == "silver":
            (source / "other.csv").write_text("id,value\n2,3\n", encoding="utf-8")
            loader.ingest("example", "v1", source, provenance={"provider": "manual"})
            silver(loader)


def test_raw_bronze_preserves_duplicate_headers_without_claiming_validation(loader, workdir):
    source = payload(workdir, files={"table.csv": "id,value,value\n1,2,3\n"})
    loader.ingest("example", "v1", source, provenance={"provider": "manual"})
    assert (master(loader, "v1") / "bronze" / "raw" / "table.csv").read_bytes() == (source / "table.csv").read_bytes()
    assert load_json(master(loader, "v1") / "bronze" / "source-index.json")["status"].startswith("raw-inventory")


def test_new_shared_silver_defaults_to_delta_and_cannot_replace_parquet_release(loader, workdir):
    pytest.importorskip("deltalake", reason="Real Delta verification requires the optional deltalake dependency")
    from azure_esml.base_layer.tables import read_table

    loader.ingest("example", "v1", payload(workdir), provenance={"provider": "manual"})
    options = {"required_columns": ["id", "value"], "owner": "dataset-team",
               "allowed_projects": ("001", "002"), "primary_key": ("id",)}
    product = loader.publish_silver("example", "v1", "delta1", **options)
    path = local_key_path(loader.root, product["silver"])
    frame, table = read_table(path, version=0)
    assert frame["value"].tolist() == [20, 30]
    assert table["format"] == "delta" and table["delta_version"] == 0
    assert product["manifest"]["signature"]["table_format"] == "delta"
    assert load_json(path / "lineage.json")["medallion_stage"] == "silver"
    assert loader.publish_silver("example", "v1", "delta1", **options)["reused"]
    silver(loader)
    with pytest.raises(ValueError, match="Immutable"):
        loader.publish_silver("example", "v1", "silver1", **options)
    with pytest.raises(ValueError, match="table_format"):
        loader.publish_silver("example", "v1", "bad", **options, table_format="foo")


def test_table_format_is_part_of_immutable_silver_identity_even_for_legacy_contracts(loader, workdir):
    from ml_model_factory.lake_flow import finish

    loader.ingest("example", "v1", payload(workdir), provenance={"provider": "manual"})
    product = silver(loader)
    path = local_key_path(loader.root, product["path"])
    manifest = load_json(path / "_SUCCESS.json")
    manifest.pop("files")
    manifest["signature"].pop("table_format")
    finish(path, manifest)
    assert silver(loader)["reused"]
    options = {"required_columns": ["id", "value"], "owner": "dataset-team",
               "allowed_projects": ("001", "002"), "primary_key": ("id",)}
    with pytest.raises(ValueError, match="Immutable"):
        loader.publish_silver("example", "v1", "silver1", **options)
    with pytest.raises(ValueError, match="table_format"):
        loader.publish_silver("example", "v1", "bad", **options, table_format="foo")
