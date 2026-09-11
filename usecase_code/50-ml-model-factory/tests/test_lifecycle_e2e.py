"""Real local lifecycles, not Azure/ADF/Databricks service execution.

Only Kaggle's network-download boundary is simulated. All source rows, images,
annotations and later observations are generated test fixtures, not live Kaggle
data or accuracy evidence. Preparation, fitting, evaluation, MLflow loading and
lake publication execute their production implementations.
"""

import base64
import json
import math
import shutil
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from ml_model_factory.config import TASKS, load_json, write_json
from ml_model_factory.data import ingest, sha256
from ml_model_factory.lake import LakeLayout, local_key_path
from ml_model_factory.lake_flow import (
    capture_source,
    feedback_in_lake,
    finish,
    infer_in_lake,
    publication,
    train_in_lake,
    verified_manifest,
)
from test_vision import image, make_jsonl, scenario as vision_scenario


ROOT = Path(__file__).resolve().parents[1]
ALL_TASKS = (
    "classification", "regression", "forecasting", "image_classification",
    "image_classification_multilabel", "image_object_detection",
    "image_instance_segmentation",
)
SPLITS = ("train", "validation", "test")
EXECUTION_SCOPE = (
    "real-local-execution; generated-labeled-fixtures; simulated-Kaggle-network; "
    "no-Azure-ADF-Databricks-service-execution"
)


@contextmanager
def local_workspace():
    path = ROOT / ".test-artifacts" / f"lifecycle-{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()


@pytest.fixture
def workspace(record_property):
    record_property("execution_scope", EXECUTION_SCOPE)
    with local_workspace() as path:
        yield path


def checksums(directory):
    """Include completion markers when checking that committed IDs never change."""
    return {
        path.relative_to(directory).as_posix(): sha256(path)
        for path in directory.rglob("*") if path.is_file()
    }


def assert_committed(directory, kind):
    marker = directory / "_SUCCESS.json"
    assert marker.is_file()
    manifest = load_json(marker)
    actual = checksums(directory)
    del actual["_SUCCESS.json"]
    assert manifest["schema"] == "ml-model-factory-publication/v1"
    assert manifest["state"] == "committed"
    assert manifest["kind"] == kind
    assert manifest["files"] == actual
    assert actual and all(len(digest) == 64 for digest in actual.values())
    assert verified_manifest(directory) == manifest
    return manifest


def generated_source(workspace, task):
    raw = workspace / "generated-network-fixture"
    raw.mkdir(parents=True)
    if task.startswith("image_"):
        definition = vision_scenario(
            task, "image_folder" if task == "image_classification" else "jsonl"
        )
        if task == "image_classification":
            for index in range(10):
                image(raw / ("red" if index % 2 == 0 else "blue") / f"{index}.png", index)
        else:
            make_jsonl(raw, task)
        definition["quality"] = {"min_accuracy": 0.0} if task.startswith(
            "image_classification"
        ) else {"min_map": 0.0}
    else:
        definition = {
            "name": "generated-lifecycle", "task": task, "target": "label",
            "features": ["signal", "cohort"], "categorical_features": ["cohort"],
            "sensitive_features": ["cohort"],
            "split": {"seed": 42, "test_size": .2, "validation_size": .2,
                      "group_column": "entity"},
            "quality": {"min_accuracy": 0.0} if task == "classification" else {"max_mae": 1000.0},
        }
        if task == "forecasting":
            rows = [
                {"series": series, "time": timestamp, "signal": day % 4,
                 "label": float(10 * series + day % 4)}
                for series in range(3)
                for day, timestamp in enumerate(pd.date_range("2026-01-01", periods=24, freq="D"))
            ]
            definition.update({
                "features": ["signal"], "categorical_features": [], "sensitive_features": [],
                "split": {"seed": 42, "test_size": .2, "validation_size": .2},
                "forecast": {"series_columns": ["series"], "time_column": "time",
                             "frequency": "D", "horizon": 4},
                "custom": {"algorithm": "seasonal_naive", "seasonal_period": 4},
            })
        else:
            rows = [
                {"entity": f"entity-{index // 4}", "signal": float(index % 4),
                 "cohort": "red" if index % 2 else "blue",
                 "label": index % 2 if task == "classification" else float(3 * (index % 4) + index / 100)}
                for index in range(120)
            ]
        pd.DataFrame(rows).to_csv(raw / "raw.csv", index=False)
    definition["dataset"] = {
        "provider": "kaggle", "kind": "dataset", "slug": "fixture/generated",
        "version": 1, "file": "." if task.startswith("image_") else "raw.csv",
        "license": "generated-test-fixture",
    }
    return definition, raw


def ingest_generated(definition, raw, output):
    # This is the sole test double: neither live Kaggle access nor a fake ingest.
    with patch("kagglehub.dataset_download", return_value=str(raw)) as download, patch(
        "kagglehub.competition_download",
        side_effect=AssertionError("Generated dataset tests must not contact competitions"),
    ) as competition:
        selected = ingest(definition, output)
    download.assert_called_once_with("fixture/generated/versions/1")
    competition.assert_not_called()
    provenance = load_json(output / "provenance.json")
    assert provenance["provider"] == "kaggle"
    assert provenance["slug"] == "fixture/generated"
    assert provenance["version"] == 1
    assert provenance["license"] == "generated-test-fixture"
    assert provenance["files"] == checksums(raw)
    assert provenance["downloaded_at"]
    for name, digest in provenance["files"].items():
        assert sha256(output / name) == digest
    return selected


def lake_config(definition, **changes):
    return {
        "project": "001", "environment": "dev", "use_case": definition["name"],
        "dataset": "generated-test-fixture", "data_version": "v1",
        "snapshot_id": "snapshot1", "run_id": "train1", "model_version": "model1",
        "serving": "batch", **changes,
    }


@pytest.fixture(scope="module", params=ALL_TASKS)
def trained_lifecycle(request):
    """Train once per task; all three serving-path variants reuse this model."""
    with local_workspace() as workspace:
        definition, raw = generated_source(workspace, request.param)
        selected = ingest_generated(definition, raw, workspace / "download")
        config = lake_config(definition)
        root = workspace / "lake"
        layout = LakeLayout.from_config(config, definition)
        source = capture_source(definition, layout, selected, root)
        captured = checksums(layout.local_path(root, "dataset_root"))
        trained = train_in_lake(definition, config, selected, root)
        assert checksums(layout.local_path(root, "dataset_root")) == captured
        yield SimpleNamespace(
            task=request.param, definition=definition, raw=raw, selected=selected,
            workspace=workspace, config=config, root=root, layout=layout,
            source=source, trained=trained, model=Path(trained["model"]),
        )


def generated_requests(lifecycle):
    """Observations come only from preexisting fixture truth, never predictions."""
    if lifecycle.task.startswith("image_"):
        paths = sorted(lifecycle.raw.rglob("*.png"))[:2]
        features = pd.DataFrame({
            "image_base64": [base64.b64encode(path.read_bytes()).decode("ascii") for path in paths]
        })
        if lifecycle.task == "image_classification":
            truth = [path.parent.name for path in paths]
        else:
            annotations = {
                row["image_url"]: row["label"]
                for row in map(json.loads, (lifecycle.raw / "annotations.jsonl").read_text().splitlines())
            }
            truth = [json.dumps(annotations[path.name], sort_keys=True) for path in paths]
    else:
        held_out = pd.read_parquet(
            lifecycle.layout.local_path(lifecycle.root, "training_gold") / "test" / "data.parquet"
        )
        rows = held_out.groupby("series", sort=True).tail(1) if lifecycle.task == "forecasting" else held_out.head(3)
        truth = rows["label"].tolist()
        features = rows.drop(columns="label").reset_index(drop=True)
    features.insert(0, "request_id", [f"fixture-request-{i}" for i in range(len(features))])
    observed = pd.DataFrame({
        "request_id": features["request_id"], "label": truth,
        "observed_at": "2026-03-01T00:00:00Z",
    })
    return features, observed


def test_local_training_executes_every_phase_with_verified_provenance(trained_lifecycle, record_property):
    record_property("execution_scope", EXECUTION_SCOPE)
    case = trained_lifecycle
    assert set(ALL_TASKS) == TASKS
    assert case.trained["state"] == "committed"
    source_root = case.layout.local_path(case.root, "dataset_root")
    source = assert_committed(source_root, "source")
    assert source["download_provenance_verified"] is True
    assert source["declared_source"] == case.definition["dataset"]
    provenance = load_json(case.workspace / "download" / "provenance.json")
    assert load_json(source_root / "download-provenance.json") == provenance
    for name, digest in provenance["files"].items():
        assert sha256(source_root / "landing" / name) == digest
    silver = load_json(source_root / "silver" / "source-contract.json")
    if case.task.startswith("image_"):
        assert silver["status"] == "requires-task-specific-annotation-validation"
        assert load_json(source_root / "bronze" / "source-index.json")["images"] == source["source_files"]
    else:
        assert silver["status"] == "validated" and silver["learned_preprocessing"] == "none"
        pd.testing.assert_frame_equal(
            pd.read_parquet(source_root / "bronze" / "data.parquet"),
            pd.read_parquet(source_root / "silver" / "data.parquet"),
        )

    snapshot_root = case.layout.local_path(case.root, "training_snapshot")
    snapshot = assert_committed(snapshot_root, "training-snapshot")
    assert snapshot["signature"]["source_manifest_sha256"] == sha256(source_root / "_SUCCESS.json")
    gold = case.layout.local_path(case.root, "training_gold")
    prepared = load_json(gold / "manifest.json")
    assert prepared["task"] == case.task
    assert all(prepared["split_rows"][split] > 0 for split in SPLITS)
    identities = []
    tables = {}
    for split in SPLITS:
        assert (gold / split / "MLTable").is_file()
        filename = "annotations.jsonl" if case.task.startswith("image_") else "data.parquet"
        assert prepared["split_sha256"][split] == sha256(gold / split / filename)
        if case.task.startswith("image_"):
            rows = [json.loads(line) for line in (gold / split / filename).read_text().splitlines()]
            assert len(rows) == prepared["split_rows"][split]
            identities.append({row["sha256"] for row in rows})
            for row in rows:
                assert row["label"] is not None
                assert sha256(gold / split / row["image"]) == row["sha256"]
        else:
            rows = tables[split] = pd.read_parquet(gold / split / filename)
            assert len(rows) == prepared["split_rows"][split] and rows["label"].notna().all()
            identities.append(set(zip(rows["series"], rows["time"])) if case.task == "forecasting"
                              else set(rows["entity"]))
    assert all(identities[a].isdisjoint(identities[b]) for a, b in ((0, 1), (0, 2), (1, 2)))
    if case.task == "forecasting":
        assert prepared["split_policy"] == "chronological-per-series"
        for series in range(3):
            times = [tables[split].loc[tables[split]["series"] == series, "time"] for split in SPLITS]
            assert times[0].max() < times[1].min() <= times[1].max() < times[2].min()
            assert len(times[1]) == len(times[2]) == case.definition["forecast"]["horizon"]
    elif not case.task.startswith("image_"):
        assert prepared["split_policy"] == "entity-group-disjoint"
    assert sum(prepared["split_rows"].values()) == (10 if case.task.startswith("image_")
                                                 else len(pd.read_csv(case.selected)))

    training_root = case.layout.local_path(case.root, "training_run")
    training = assert_committed(training_root, "training-run")
    assert training["run_id"] == "train1" and training["snapshot_id"] == "snapshot1"
    assert load_json(training_root / "lineage.json")["source_snapshot_sha256"] == sha256(snapshot_root / "_SUCCESS.json")
    factory = load_json(case.model / "factory.json")
    assert factory["mode"] == "custom" and factory["scenario"] == case.definition
    assert "model/MLmodel" in training["files"]
    assert load_json(training_root / "evaluation" / "quality-gate.json")["passed"] is True
    metrics = load_json(training_root / "evaluation" / "metrics.json")
    assert metrics and all(math.isfinite(value) for value in metrics.values())
    report = load_json(training_root / "evaluation" / "responsible-ai.json")
    assert report["test_rows"] == prepared["split_rows"]["test"]
    if case.task.startswith("image_"):
        assert factory["optimizer_steps"] == 1
        assert factory["image_presentations"] == 2
        assert len(factory["training_loss"]) == 1 and math.isfinite(factory["training_loss"][0])
        assert factory["pretrained"] is False
        assert (case.model / factory["checkpoint"]).is_file()
    elif case.task == "forecasting":
        assert factory["baseline"] is True
        assert metrics["mae"] == 0.0
    else:
        assert factory["training_rows"] == prepared["split_rows"]["train"]

    before = checksums(case.root)
    with pytest.raises(ValueError, match="already exists"):
        train_in_lake(case.definition, case.config, case.selected, case.root)
    with pytest.raises(ValueError, match="overwrite"):
        ingest(case.definition, case.workspace / "download")
    assert checksums(case.root) == before


@pytest.mark.parametrize("serving", ["batch", "online", "streaming"])
def test_local_unlabeled_serving_and_observed_feedback_reuse_one_model(
    trained_lifecycle, serving, record_property
):
    import mlflow.pyfunc
    from ml_model_factory.evaluation import prediction_vector

    record_property("execution_scope", EXECUTION_SCOPE)
    record_property("serving_scope", f"{serving}-lake-path; local-pyfunc-not-hosted-service")
    case = trained_lifecycle
    config = {**case.config, "serving": serving, "run_id": f"infer-{serving}"}
    layout = LakeLayout.from_config(config, case.definition)
    requests, observations = generated_requests(case)
    incoming = case.workspace / f"{serving}-requests.parquet"
    labels = case.workspace / f"{serving}-observations.csv"
    requests.to_parquet(incoming, index=False)
    # Persist generated truth before inference so no model output supplies labels.
    observations.to_csv(labels, index=False)
    training_before = checksums(case.layout.local_path(case.root, "training_snapshot"))
    model_before = checksums(case.model.parent)
    result = infer_in_lake(case.definition, config, incoming, case.model, case.root)
    assert result["state"] == "committed" and result["rows"] == len(requests)
    inference_root = layout.local_path(case.root, "inference_root")
    inference = assert_committed(inference_root, "inference-run")
    assert inference["training_run"] == "train1" and inference["model_version"] == "model1"
    assert inference_root != case.model.parent
    assert sha256(inference_root / "_SUCCESS.json") != sha256(case.model.parent / "_SUCCESS.json")
    assert sha256(layout.local_path(case.root, "input") / incoming.name) == sha256(incoming)
    features = pd.read_parquet(layout.local_path(case.root, "inference_gold") / "features.parquet")
    assert "label" not in features and "request_id" not in features
    predictions = pd.read_parquet(Path(result["output"]) / "predictions.parquet")
    assert set(predictions) == {"request_id", "prediction", "model_version", "run_id"}
    assert predictions["request_id"].tolist() == requests["request_id"].tolist()
    assert predictions["request_id"].is_unique
    assert set(predictions["model_version"]) == {"model1"}
    assert set(predictions["run_id"]) == {config["run_id"]}
    assert predictions["prediction"].notna().all()
    loaded = mlflow.pyfunc.load_model(str(case.model))
    expected = prediction_vector(loaded.predict(features), len(features))
    np.testing.assert_array_equal(predictions["prediction"].to_numpy(), expected)
    lineage = load_json(inference_root / "lineage.json")
    assert lineage["training_run_manifest_sha256"] == sha256(case.model.parent / "_SUCCESS.json")
    assert lineage["model_mlmodel_sha256"] == sha256(case.model / "MLmodel")
    assert lineage["input_sha256"] == sha256(incoming)
    binding_root = local_key_path(case.root, layout.key("use_case_root") + "/models/model1/binding")
    binding = assert_committed(binding_root, "model-version-binding")
    assert binding["binding"] == {"training_manifest_sha256": sha256(case.model.parent / "_SUCCESS.json")}
    assert load_json(binding_root / "model.json") == binding["binding"]

    feedback_config = {**config, "feedback_version": "observed1",
                       "feedback_source": "generated-test-observations-authored-before-scoring"}
    feedback = feedback_in_lake(case.definition, feedback_config, labels, case.root)
    assert feedback["rows"] == len(observations) and feedback["training_eligible"] is False
    feedback_root = local_key_path(case.root, feedback["feedback"])
    manifest = assert_committed(feedback_root, "observed-feedback")
    assert manifest["training_eligible"] is False
    assert manifest["inference_run"] == config["run_id"]
    assert manifest["model_version"] == "model1"
    assert manifest["source_sha256"] == sha256(labels)
    actual = pd.read_parquet(feedback_root / "labels.parquet")
    assert set(actual) == {"request_id", "label", "observed_at"}
    joined = predictions.merge(actual, on="request_id", validate="one_to_one")
    assert len(joined) == len(observations)
    assert joined["label"].tolist() == observations["label"].tolist()
    assert actual["observed_at"].notna().all()
    assert checksums(case.layout.local_path(case.root, "training_snapshot")) == training_before
    assert checksums(case.model.parent) == model_before
    committed_before = checksums(case.root)
    with pytest.raises(ValueError, match="already exists"):
        infer_in_lake(case.definition, config, incoming, case.model, case.root)
    with pytest.raises(ValueError, match="already exists"):
        feedback_in_lake(case.definition, feedback_config, labels, case.root)
    assert checksums(case.root) == committed_before


@pytest.mark.parametrize("invalid", ["target-labels", "duplicate-request-ids"])
def test_local_invalid_inference_quarantines_without_output(trained_lifecycle, invalid, record_property):
    record_property("execution_scope", EXECUTION_SCOPE)
    case = trained_lifecycle
    requests, observed = generated_requests(case)
    if invalid == "target-labels":
        requests["label"] = observed["label"]
        message = "labels"
    else:
        requests.loc[1, "request_id"] = requests.loc[0, "request_id"]
        message = "unique request_id"
    incoming = case.workspace / f"invalid-{invalid}.parquet"
    requests.to_parquet(incoming, index=False)
    config = {**case.config, "run_id": f"invalid-{invalid}"}
    layout = LakeLayout.from_config(config)
    training_before = checksums(case.model.parent)
    with pytest.raises(ValueError, match=message):
        infer_in_lake(case.definition, config, incoming, case.model, case.root)
    assert not layout.local_path(case.root, "inference_root").exists()
    assert not layout.local_path(case.root, "output").exists()
    issues = list(layout.local_path(case.root, "quarantine").rglob("issue.json"))
    assert len(issues) == 1
    issue = load_json(issues[0])
    assert issue["status"] == "rejected" and issue["raw_rows_copied"] is False
    assert issue["source_reference"] == layout.key("input")
    assert checksums(case.model.parent) == training_before


@pytest.mark.parametrize("task,damage,message", [
    ("classification", "unlabeled", "target"),
    ("regression", "missing-feature", "missing required columns"),
    ("forecasting", "duplicate-time", "series/timestamp"),
    ("image_classification", "unlabeled-folder", "No labeled images"),
    ("image_classification_multilabel", "missing-annotation", "label"),
    ("image_object_detection", "invalid-box", "Bounding box"),
    ("image_instance_segmentation", "invalid-polygon", "polygon"),
])
def test_local_bad_generated_training_data_is_quarantined(task, damage, message, workspace):
    definition, raw = generated_source(workspace, task)
    if not task.startswith("image_"):
        rows = pd.read_csv(raw / "raw.csv")
        if damage == "unlabeled":
            rows.loc[0, "label"] = None
        elif damage == "missing-feature":
            rows = rows.drop(columns="signal")
        else:
            rows.loc[1, "time"] = rows.loc[0, "time"]
        rows.to_csv(raw / "raw.csv", index=False)
    elif damage == "unlabeled-folder":
        for path in raw.rglob("*.png"):
            path.rename(raw / path.name)
        for directory in list(raw.iterdir()):
            if directory.is_dir():
                directory.rmdir()
    else:
        annotations = raw / "annotations.jsonl"
        rows = [json.loads(line) for line in annotations.read_text().splitlines()]
        if damage == "missing-annotation":
            del rows[0]["label"]
        elif damage == "invalid-box":
            rows[0]["label"][0]["bottomX"] = 2.0
        else:
            rows[0]["label"][0]["polygon"] = [[.1, .1, .8, .8, .2]]
        annotations.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    selected = ingest_generated(definition, raw, workspace / "download")
    root, config = workspace / "lake", lake_config(definition)
    layout = LakeLayout.from_config(config)
    with pytest.raises((ValueError, KeyError), match=message):
        train_in_lake(definition, config, selected, root)
    source = assert_committed(layout.local_path(root, "dataset_root"), "source")
    assert source["download_provenance_verified"] is True
    assert not layout.local_path(root, "training_snapshot").exists()
    assert not layout.local_path(root, "training_run").exists()
    issues = list(layout.local_path(root, "dataset_quarantine").rglob("issue.json"))
    assert len(issues) == 1
    assert load_json(issues[0])["raw_rows_copied"] is False
    assert not list(root.rglob("*.lock")) and not list(root.rglob(".publishing-*"))


@pytest.mark.parametrize("mutation", ["download-checksum", "committed-source"])
def test_local_mutated_source_cannot_reach_training(mutation, workspace):
    definition, raw = generated_source(workspace, "classification")
    selected = ingest_generated(definition, raw, workspace / "download")
    config, root = lake_config(definition), workspace / "lake"
    layout = LakeLayout.from_config(config)
    source = capture_source(definition, layout, selected, root)
    destination = selected if mutation == "download-checksum" else source
    original = destination.read_bytes()
    destination.write_bytes(original + b"\nchanged-after-pinning")
    message = "provenance hashes" if mutation == "download-checksum" else "files changed"
    with pytest.raises(ValueError, match=message):
        train_in_lake(definition, config, selected, root)
    assert not layout.local_path(root, "training_snapshot").exists()
    assert not layout.local_path(root, "training_run").exists()
    assert len(list(layout.local_path(root, "dataset_quarantine").rglob("issue.json"))) == 1
    assert destination.read_bytes() == original + b"\nchanged-after-pinning"


def test_local_quality_gate_failure_preserves_diagnostics_but_never_commits_model(workspace):
    definition, raw = generated_source(workspace, "classification")
    definition["quality"] = {"min_accuracy": 1.1}
    selected = ingest_generated(definition, raw, workspace / "download")
    config, root = lake_config(definition), workspace / "lake"
    layout = LakeLayout.from_config(config)
    with pytest.raises(ValueError, match="quality gate failed"):
        train_in_lake(definition, config, selected, root)
    assert_committed(layout.local_path(root, "dataset_root"), "source")
    assert_committed(layout.local_path(root, "training_snapshot"), "training-snapshot")
    assert not layout.local_path(root, "training_run").exists()
    assert not layout.local_path(root, "training_model").exists()
    rejected = local_key_path(root, layout.key("training_run") + "-rejected")
    assert load_json(rejected / "status.json") == {"state": "rejected", "model_promoted": False}
    assert load_json(rejected / "evaluation" / "quality-gate.json")["passed"] is False
    assert 0 <= load_json(rejected / "evaluation" / "metrics.json")["accuracy"] <= 1
    assert (rejected / "evaluation" / "predictions.parquet").is_file()
    assert not (rejected / "_SUCCESS.json").exists()
    assert not list(root.rglob("MLmodel"))
    assert not list(root.rglob("*.lock")) and not list(root.rglob(".publishing-*"))
    before = checksums(root)
    relaxed = {**definition, "quality": {"min_accuracy": 0.0}}
    with pytest.raises(ValueError, match="already exists"):
        train_in_lake(relaxed, config, selected, root)
    assert checksums(root) == before
    assert not layout.local_path(root, "training_run").exists()


def test_local_pinned_model_version_cannot_be_rebound_to_another_real_model(workspace):
    definition, raw = generated_source(workspace, "classification")
    selected = ingest_generated(definition, raw, workspace / "download")
    config, root = lake_config(definition), workspace / "lake"
    first = train_in_lake(definition, config, selected, root)
    incoming = workspace / "requests.csv"
    requests = pd.read_csv(raw / "raw.csv").head(3).drop(columns="label")
    requests.insert(0, "request_id", ["a", "b", "c"])
    requests.to_csv(incoming, index=False)
    infer_in_lake(definition, {**config, "run_id": "first-score"}, incoming, Path(first["model"]), root)
    _, second_raw = generated_source(workspace / "second-source", "classification")
    rows = pd.read_csv(second_raw / "raw.csv")
    rows["label"] = 1 - rows["label"]
    rows.to_csv(second_raw / "raw.csv", index=False)
    second_selected = ingest_generated(definition, second_raw, workspace / "second-download")
    second_config = {**config, "run_id": "train2", "snapshot_id": "snapshot2", "data_version": "v2"}
    second = train_in_lake(definition, second_config, second_selected, root)
    assert sha256(Path(first["model"]) / "model.pkl") != sha256(Path(second["model"]) / "model.pkl")
    before = checksums(root)
    conflict = {**second_config, "run_id": "conflicting-score", "serving": "online"}
    with pytest.raises(ValueError, match="bound to a different model"):
        infer_in_lake(definition, conflict, incoming, Path(second["model"]), root)
    assert checksums(root) == before
    assert not LakeLayout.from_config(conflict).local_path(root, "output").exists()
    fresh = {**conflict, "model_version": "model2"}
    assert infer_in_lake(definition, fresh, incoming, Path(second["model"]), root)["state"] == "committed"
    predicted = pd.read_parquet(
        LakeLayout.from_config(fresh).local_path(root, "output") / "predictions.parquet"
    )
    assert set(predicted["model_version"]) == {"model2"}


@pytest.mark.parametrize("failure", ["missing-marker", "interrupted-before-finish", "interrupted-after-finish"])
def test_local_failed_publication_never_exposes_success_or_overwrites(failure, workspace):
    definition, raw = generated_source(workspace, "classification")
    selected = ingest_generated(definition, raw, workspace / "download")
    root, config = workspace / "lake", lake_config(definition)
    layout = LakeLayout.from_config(config)
    capture_source(definition, layout, selected, root)
    before = checksums(root)
    error = ValueError if failure == "missing-marker" else KeyboardInterrupt
    with pytest.raises(error):
        with publication(root, layout.key("training_run")) as staging:
            (staging / "partial.bin").write_bytes(b"deliberately incomplete local publication")
            if failure == "interrupted-after-finish":
                finish(staging, {"kind": "training-run"})
            if failure != "missing-marker":
                raise KeyboardInterrupt("simulated writer interruption, not a successful training run")
    assert not layout.local_path(root, "training_run").exists()
    assert checksums(root) == before
    assert not list(root.rglob("*.lock")) and not list(root.rglob(".publishing-*"))
    with pytest.raises(ValueError, match="already exists"):
        with publication(root, layout.key("dataset_root")):
            pytest.fail("Immutable source publication unexpectedly allowed replacement")
    assert checksums(root) == before
