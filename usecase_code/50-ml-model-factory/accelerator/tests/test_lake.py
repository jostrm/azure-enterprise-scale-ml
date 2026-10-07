import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from ml_model_factory.data import prepare
from ml_model_factory.lake import LakeLayout, lake_manifest
from ml_model_factory.lake_flow import (
    capture_source, feedback_in_lake, infer_in_lake, train_in_lake, verified_manifest,
)


CONFIG = {
    "project": "001", "environment": "dev", "use_case": "fixture", "dataset": "fixture-data",
    "data_version": "v1", "snapshot_id": "s1", "run_id": "r1",
    "serving": "batch", "model_version": "m1",
    "storage": {"account_url": "https://examplelake.blob.core.windows.net",
                "container": "ml-model-factory", "datastore": "lake"},
}
SCENARIO = {
    "name": "fixture", "task": "classification", "target": "label",
    "features": ["age", "sex"], "categorical_features": ["sex"], "sensitive_features": ["sex"],
    "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/generated",
                "file": "input.csv", "version": 1, "license": "test-fixture"},
    "split": {"seed": 42, "validation_size": 0.2, "test_size": 0.2},
    "quality": {"min_accuracy": 0.0},
}


def raw_table(path):
    frame = pd.DataFrame({"age": range(100), "sex": ["f", "m"] * 50, "label": [1, 0] * 50})
    frame.to_csv(path, index=False)
    return frame


@pytest.mark.parametrize("task", [
    "classification", "regression", "forecasting", "image_classification",
    "image_classification_multilabel", "image_object_detection", "image_instance_segmentation",
])
@pytest.mark.parametrize("serving", ["batch", "online", "streaming"])
def test_layout_is_technology_and_task_neutral(task, serving):
    layout = LakeLayout.from_config({**CONFIG, "serving": serving}, {"name": "fixture", "task": task})
    keys = layout.as_dict()
    assert keys["scope"] == "mlops/v1/projects/project001/environments/dev"
    assert "/datasets/fixture-data/versions/v1/" in keys["landing"]
    assert "/training/snapshots/s1/gold" in keys["training_gold"]
    assert f"/inference/{serving}/models/m1/runs/r1/in" in keys["input"]
    assert "azure-automl" not in str(keys) and task not in keys["scope"]
    assert layout.azureml_uri("training_model").startswith("azureml://datastores/lake/paths/")
    assert layout.blob_uri("landing").startswith("https://examplelake.blob.core.windows.net/ml-model-factory/")


def test_dataset_reuse_and_checkpoint_are_independent_of_training_run_and_model():
    one = LakeLayout.from_config(CONFIG)
    two = LakeLayout.from_config({**CONFIG, "run_id": "r2", "model_version": "m2"})
    for key in ("dataset_root", "training_gold", "checkpoint"):
        assert one.key(key) == two.key(key)
    assert one.key("training_model") != two.key("training_model")
    assert one.key("output") != two.key("output")
    assert not one.key("feedback").startswith(one.key("inference_root") + "/")
    assert not one.key("dataset_quarantine").startswith(one.key("dataset_root") + "/")
    assert one.key("checkpoint") != LakeLayout.from_config({**CONFIG, "pipeline_version": "v2"}).key("checkpoint")


@pytest.mark.parametrize("field,value", [
    ("project", "../001"), ("environment", "stage"), ("dataset", "../other"),
    ("run_id", "C:\\escape"), ("snapshot_id", "CON"), ("prefix", "projects"),
    ("prefix", "mlops/../other"), ("model_version", "latest"), ("serving", "realtime"),
    ("prefix", "mlops/v1?sig=credential"), ("prefix", "mlops/v1#fragment"),
])
def test_invalid_keys_fail_closed(field, value):
    with pytest.raises(ValueError):
        LakeLayout.from_config({**CONFIG, field: value})


def test_local_training_and_unlabeled_inference_are_separate(tmp_path):
    raw = tmp_path / "raw.csv"
    frame = raw_table(raw)
    root = tmp_path / "lake"
    trained = train_in_lake(SCENARIO, CONFIG, raw, root)
    layout = LakeLayout.from_config(CONFIG)
    verified_manifest(layout.local_path(root, "training_run"))
    assert trained["state"] == "committed"
    assert (layout.local_path(root, "training_gold") / "test" / "data.parquet").exists()
    incoming = frame.head(4).drop(columns="label")
    incoming.insert(0, "request_id", ["a", "b", "c", "d"])
    incoming.to_csv(tmp_path / "requests.csv", index=False)
    result = infer_in_lake(SCENARIO, {**CONFIG, "run_id": "score1"}, tmp_path / "requests.csv",
                           Path(trained["model"]), root)
    scored = pd.read_parquet(Path(result["output"]) / "predictions.parquet")
    assert scored["request_id"].tolist() == ["a", "b", "c", "d"]
    assert set(scored["model_version"]) == {"m1"}
    assert "label" not in scored
    feedback = pd.DataFrame({"request_id": ["a"], "label": [1], "observed_at": ["2026-01-01T00:00:00Z"]})
    feedback.to_csv(tmp_path / "labels.csv", index=False)
    observed = feedback_in_lake(SCENARIO, {
        **CONFIG, "run_id": "score1", "feedback_version": "f1", "feedback_source": "generated-test-observation",
    }, tmp_path / "labels.csv", root)
    assert observed["training_eligible"] is False
    inference_layout = LakeLayout.from_config({**CONFIG, "run_id": "score1"})
    verified_manifest(inference_layout.local_path(root, "inference_root"))
    labeled_requests = incoming.copy()
    labeled_requests["label"] = frame.head(4)["label"].to_numpy()
    labeled_requests.to_csv(tmp_path / "labeled-requests.csv", index=False)
    with pytest.raises(ValueError, match="labels"):
        infer_in_lake(SCENARIO, {**CONFIG, "run_id": "badscore"}, tmp_path / "labeled-requests.csv",
                      Path(trained["model"]), root)
    with pytest.raises(ValueError, match="already exists"):
        train_in_lake(SCENARIO, CONFIG, raw, root)
    reused = train_in_lake(SCENARIO, {**CONFIG, "run_id": "r2"}, raw, root)
    assert reused["state"] == "committed"
    verified_manifest(layout.local_path(root, "dataset_root"))
    verified_manifest(layout.local_path(root, "training_snapshot"))


def test_bad_labels_quarantine_references_without_rewriting_source(tmp_path):
    raw = tmp_path / "raw.csv"
    frame = raw_table(raw)
    frame.loc[0, "label"] = None
    frame.to_csv(raw, index=False)
    root = tmp_path / "lake"
    layout = LakeLayout.from_config(CONFIG)
    with pytest.raises(ValueError, match="target"):
        train_in_lake(SCENARIO, CONFIG, raw, root)
    issues = list(layout.local_path(root, "dataset_quarantine").rglob("issue.json"))
    assert len(issues) == 1
    assert json.loads(issues[0].read_text())["raw_rows_copied"] is False
    assert not layout.local_path(root, "training_run").exists()
    verified_manifest(layout.local_path(root, "dataset_root"))


def test_modified_dataset_version_and_snapshot_are_rejected(tmp_path):
    raw = tmp_path / "raw.csv"
    frame = raw_table(raw)
    root = tmp_path / "lake"
    layout = LakeLayout.from_config(CONFIG)
    capture_source(SCENARIO, layout, raw, root)
    frame.loc[0, "age"] = 999
    frame.to_csv(raw, index=False)
    with pytest.raises(ValueError, match="different content"):
        capture_source(SCENARIO, layout, raw, root)


def test_entity_groups_do_not_cross_gold_splits(tmp_path):
    scenario = copy.deepcopy(SCENARIO)
    scenario["split"]["group_column"] = "customer"
    raw = tmp_path / "raw.csv"
    frame = raw_table(raw)
    frame["customer"] = [f"customer{i // 5}" for i in range(len(frame))]
    frame.to_csv(raw, index=False)
    manifest = prepare(scenario, raw, tmp_path / "gold")
    groups = [set(pd.read_parquet(tmp_path / "gold" / split / "data.parquet")["customer"])
              for split in ("train", "validation", "test")]
    assert all(not groups[i].intersection(groups[j]) for i, j in ((0, 1), (0, 2), (1, 2)))
    assert manifest["split_policy"] == "entity-group-disjoint"


def test_plan_creates_no_directories(tmp_path):
    manifest = lake_manifest(LakeLayout.from_config(CONFIG), SCENARIO)
    assert manifest["contract"]["permissions"].startswith("Blob prefixes are not")
    assert list(tmp_path.iterdir()) == []


def test_blob_publication_is_data_first_manifest_last_and_no_overwrite(tmp_path):
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    from ml_model_factory.lake_storage import publication_plan, publish

    raw = tmp_path / "raw.csv"
    raw_table(raw)
    layout = LakeLayout.from_config(CONFIG)
    root = tmp_path / "lake"
    capture_source(SCENARIO, layout, raw, root)
    plan = publication_plan(layout, root, "dataset_root")
    assert plan["files"][-1]["blob"].endswith("/_SUCCESS.json")
    blobs, writes = {}, []

    class Blob:
        def __init__(self, name):
            self.name = name

        def upload_blob(self, data, *, overwrite, metadata=None):
            assert overwrite is False
            if self.name in blobs:
                raise ResourceExistsError("exists")
            data = data.read() if hasattr(data, "read") else data
            blobs[self.name] = {"data": data, "metadata": metadata or {}}
            writes.append(self.name)
            return {"etag": "test"}

        def get_blob_properties(self):
            if self.name not in blobs:
                raise ResourceNotFoundError("missing")
            return SimpleNamespace(size=len(blobs[self.name]["data"]), metadata=blobs[self.name]["metadata"])

        def delete_blob(self, **kwargs):
            assert kwargs["etag"] == "test"
            del blobs[self.name]

    class Service:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_container_client(self, name):
            assert name == CONFIG["storage"]["container"]
            return self

        def get_container_properties(self):
            return {}

        def get_blob_client(self, name):
            return Blob(name)

    with patch("azure.storage.blob.BlobServiceClient", return_value=Service()):
        result = publish(layout, root, "dataset_root", object())
        assert result["written"] == len(plan["files"])
        assert writes[-1].endswith("/_SUCCESS.json")
        repeated = publish(layout, root, "dataset_root", object())
        assert repeated["written"] == 0
        blobs[plan["files"][0]["blob"]]["metadata"]["sha256"] = "different"
        with pytest.raises(ValueError, match="differs"):
            publish(layout, root, "dataset_root", object())


@pytest.mark.parametrize("task", [
    "image_classification", "image_classification_multilabel",
    "image_object_detection", "image_instance_segmentation",
])
def test_vision_training_and_unlabeled_lake_inference(task, tmp_path):
    import base64
    from test_vision import make_jsonl, scenario

    raw = tmp_path / "raw"
    make_jsonl(raw, task)
    definition = scenario(task, "jsonl")
    config = {**CONFIG, "use_case": definition["name"]}
    root = tmp_path / "lake"
    trained = train_in_lake(definition, config, raw, root)
    requests = pd.DataFrame({
        "request_id": ["image-1"],
        "image_base64": [base64.b64encode((raw / "0.png").read_bytes()).decode("ascii")],
    })
    requests.to_parquet(tmp_path / "requests.parquet", index=False)
    result = infer_in_lake(definition, {**config, "run_id": "infer1"},
                           tmp_path / "requests.parquet", Path(trained["model"]), root)
    output = pd.read_parquet(Path(result["output"]) / "predictions.parquet")
    assert len(output) == 1 and output["request_id"].iloc[0] == "image-1"
    assert isinstance(output["prediction"].iloc[0], str)
