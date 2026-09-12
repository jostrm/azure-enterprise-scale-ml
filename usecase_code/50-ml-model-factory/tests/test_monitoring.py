"""Real deterministic drift calculations; Azure publication is a service simulation."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from ml_model_factory.monitoring import data_drift, image_statistics, monitor, performance_signal
from ml_model_factory.monitoring_export import add_evaluation_metrics, publish_model_report, summary_tags, validate_report
from ml_model_factory.config import write_json


NOW = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)
SCENARIO = {
    "name": "example", "model_name": "example-model", "task": "classification",
    "features": ["x", "category"], "target": "label", "categorical_features": ["category"],
    "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/data", "file": "data.csv", "version": 1},
}
CONTEXT = {"aifactory": "spider-001", "project": "001", "environment_name": "dev"}
CONFIG = {
    "model_version": "1", "reference_window": {"start": "2026-08-01T00:00:00Z", "end": "2026-08-15T00:00:00Z"},
    "window": {"start": "2026-09-10T00:00:00Z", "end": "2026-09-11T12:00:00Z"}, "max_age_hours": 24,
}


def frames():
    reference = pd.DataFrame({"x": np.linspace(-2, 2, 200), "category": ["a", "b"] * 100})
    return reference, reference.copy()


def labels(task="classification", error=0.0):
    truth = np.tile([0, 1], 100) if task == "classification" else np.linspace(0, 10, 200)
    baseline = pd.DataFrame({"request_id": [f"reference-{i}" for i in range(200)],
                             "actual": truth, "prediction": truth, "model_version": "1"})
    predictions = pd.DataFrame({"request_id": [f"current-{i}" for i in range(200)],
                                "prediction": truth.copy(), "model_version": "1"})
    if task == "classification":
        count = int(error * len(truth))
        predictions.loc[:count-1, "prediction"] = 1 - predictions.loc[:count-1, "prediction"] if count else predictions.loc[:count-1, "prediction"]
    else:
        predictions["prediction"] = predictions["prediction"] + error
    observed = pd.DataFrame({"request_id": predictions["request_id"], "label": truth,
                             "observed_at": "2026-09-11T23:00:00Z"})
    return baseline, predictions, observed


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_unchanged_data_and_labeled_performance_are_healthy(environment):
    reference, current = frames()
    baseline, predictions, observed = labels()
    report = monitor(SCENARIO, {**CONTEXT, "environment_name": environment}, reference, current,
                     CONFIG, reference_outcomes=baseline, predictions=predictions, labels=observed, now=NOW)
    assert report["summary"] == {"status": "healthy", "data_drift": "healthy", "concept_drift": "healthy"}
    assert report["scope"]["environment"] == environment
    tags = summary_tags(report, now=NOW)
    assert tags["mon_subject_version"] == "1" and tags["mon_status"] == "healthy"
    assert "model-factory" in tags["mon_source"]


def test_covariate_shift_is_not_claimed_as_concept_drift():
    reference, current = frames()
    current["x"] += 10
    report = monitor(SCENARIO, CONTEXT, reference, current, CONFIG, now=NOW)
    assert report["summary"]["data_drift"] == "drift"
    assert report["summary"]["concept_drift"] == "unknown"
    assert report["details"]["data_drift"]["features"][0]["value"] > 0.25
    assert "predictions are not labels" in report["details"]["concept_drift"]["reason"]


def test_label_concept_signal_detected_without_covariate_shift():
    baseline, predictions, observed = labels(error=0.5)
    report = monitor(SCENARIO, CONTEXT, *frames(), CONFIG,
                     reference_outcomes=baseline, predictions=predictions, labels=observed, now=NOW)
    assert report["summary"]["data_drift"] == "healthy"
    assert report["summary"]["concept_drift"] == "drift"
    assert report["details"]["concept_drift"]["confidence_interval_95"][0] > 0
    assert "not proof" in report["details"]["concept_drift"]["interpretation"]


@pytest.mark.parametrize("task", ["regression", "forecasting"])
def test_continuous_performance_degradation(task):
    scenario = {**SCENARIO, "task": task}
    if task == "forecasting":
        scenario["forecast"] = {"time_column": "date", "frequency": "D", "horizon": 3}
    baseline, predictions, observed = labels(task, error=5)
    report = monitor(scenario, CONTEXT, *frames(), CONFIG,
                     reference_outcomes=baseline, predictions=predictions, labels=observed, now=NOW)
    assert report["summary"]["concept_drift"] == "drift"
    assert report["details"]["concept_drift"]["metric"] == "normalized_mae_increase"


def test_stale_and_sparse_never_look_healthy():
    reference, current = frames()
    stale = {**CONFIG, "max_age_hours": 1}
    report = monitor(SCENARIO, CONTEXT, reference, current, stale, now=NOW)
    assert set(report["summary"].values()) == {"stale"}
    report = monitor(SCENARIO, CONTEXT, reference, current.head(5), CONFIG, now=NOW)
    assert report["summary"]["data_drift"] == "insufficient_data"
    assert report["summary"]["status"] != "healthy"


def test_insufficient_labels_cannot_clear_concept_alert():
    baseline, predictions, observed = labels(error=0.5)
    report = monitor(SCENARIO, CONTEXT, *frames(), CONFIG,
                     reference_outcomes=baseline, predictions=predictions, labels=observed.head(10), now=NOW)
    assert report["summary"]["concept_drift"] == "insufficient_data"


@pytest.mark.parametrize("fault", ["other_model", "duplicate", "foreign_label", "overlap", "future_label", "naive_label"])
def test_invalid_label_alignment_is_rejected(fault):
    baseline, predictions, observed = labels()
    if fault == "other_model":
        predictions.loc[0, "model_version"] = "2"
    elif fault == "duplicate":
        observed.loc[0, "request_id"] = observed.loc[1, "request_id"]
    elif fault == "foreign_label":
        observed.loc[0, "request_id"] = "not-in-window"
    elif fault == "overlap":
        baseline.loc[0, "request_id"] = predictions.loc[0, "request_id"]
    elif fault == "future_label":
        observed.loc[0, "observed_at"] = "2030-01-01T00:00:00Z"
    else:
        observed.loc[0, "observed_at"] = "2026-09-11T23:00:00"
    with pytest.raises(ValueError):
        monitor(SCENARIO, CONTEXT, *frames(), CONFIG, reference_outcomes=baseline,
                predictions=predictions, labels=observed, now=NOW)


def test_categorical_new_values_and_missingness_are_visible():
    reference, current = frames()
    current["category"] = "unseen"
    current["x"] = np.nan
    drift = data_drift(reference, current, ["x", "category"], ["category"], {})
    assert drift["status"] == "drift"
    assert drift["features"][1]["metric"] == "js_divergence"
    assert drift["features"][1]["value"] == pytest.approx(1.0)
    assert drift["features"][0]["missing_fraction_change"] == 1.0


def test_invalid_schema_infinities_and_future_window():
    reference, current = frames()
    missing = monitor(SCENARIO, CONTEXT, reference, current.drop(columns="x"), CONFIG, now=NOW)
    assert missing["summary"]["data_drift"] == "unknown"
    current.loc[0, "x"] = np.inf
    with pytest.raises(ValueError, match="Infinite"):
        monitor(SCENARIO, CONTEXT, reference, current, CONFIG, now=NOW)
    with pytest.raises(ValueError, match="future"):
        monitor(SCENARIO, CONTEXT, *frames(), {**CONFIG, "window": {
            "start": "2026-09-10T00:00:00Z", "end": "2030-01-01T00:00:00Z"}}, now=NOW)


@pytest.mark.parametrize("task", ["image_classification", "image_classification_multilabel",
                                 "image_object_detection", "image_instance_segmentation"])
def test_vision_fixed_features_and_explicit_performance_limit(task):
    scenario = {**SCENARIO, "task": task}
    report = monitor(scenario, CONTEXT, *frames(), {**CONFIG, "features": ["x"]}, now=NOW)
    assert report["summary"]["data_drift"] == "healthy"
    assert report["summary"]["concept_drift"] == ("unknown" if task == "image_classification" else "not_supported")
    unsupported = monitor(scenario, CONTEXT, *frames(), CONFIG, now=NOW)
    assert unsupported["summary"]["data_drift"] == "not_supported"


def test_real_image_summary_shift():
    import base64
    import io
    from PIL import Image
    def encoded(color):
        stream = io.BytesIO()
        Image.new("RGB", (16, 16), color).save(stream, format="PNG")
        return base64.b64encode(stream.getvalue()).decode("ascii")
    before = pd.DataFrame({"image_base64": [encoded("black")] * 100})
    after = pd.DataFrame({"image_base64": [encoded("white")] * 100})
    report = monitor({**SCENARIO, "task": "image_object_detection"}, CONTEXT, before, after,
                     {**CONFIG, "image_statistics": True}, now=NOW)
    assert report["summary"]["data_drift"] == "drift"
    assert report["summary"]["concept_drift"] == "not_supported"


def test_reports_are_bounded_finite_and_credential_free():
    report = monitor(SCENARIO, CONTEXT, *frames(), CONFIG, now=NOW)
    assert validate_report(report, now=NOW) is report
    with pytest.raises(ValueError):
        summary_tags(report, "https://example.blob.core.windows.net/data/report.json?sig=secret", now=NOW)
    report["metrics"][0]["value"] = float("nan")
    with pytest.raises(ValueError):
        validate_report(report, now=NOW)


def test_all_numeric_evaluation_metrics_are_exposed_without_becoming_current_health():
    report = monitor(SCENARIO, CONTEXT, *frames(), CONFIG, now=NOW)
    summary = report["summary"].copy()
    add_evaluation_metrics(report, {"accuracy": 0.8, "f1_weighted": 0.79, "custom_metric": 5.0})
    rows = [metric for metric in report["metrics"] if metric["name"].startswith("evaluation_reference.")]
    assert len(rows) == 3 and all(metric["status"] == "unknown" for metric in rows)
    assert report["summary"] == summary
    with pytest.raises(ValueError):
        add_evaluation_metrics(report, {"prompt": "private raw text"})


def test_publish_updates_exact_model_scope_without_overwriting_identity(tmp_path):
    report = monitor(SCENARIO, CONTEXT, *frames(), CONFIG, now=NOW)
    # Publish validation uses actual UTC; keep windows historical and exercise stale tags.
    report_file = tmp_path / "report.json"
    write_json(report_file, report)
    runtime = {**CONTEXT, "subscription_id": "00000000-0000-0000-0000-000000000001",
               "tenant_id": "00000000-0000-0000-0000-000000000002", "resource_group": "rg",
               "workspace_name": "ws", "compute": "cpu", "lake": {
                   "aifactory": "spider-001", "project": "001", "environment": "dev", "use_case": "example",
                   "dataset": "data", "data_version": "v1", "snapshot_id": "s1", "run_id": "r1", "model_version": "1",
                   "storage": {"account_url": "https://example.blob.core.windows.net", "container": "models"}}}
    model = SimpleNamespace(tags={"aifactory": "spider-001", "project": "001", "environment": "dev",
                                   "use_case": "example", "quality_gate": "passed", "mon_old": "remove"},
                            id="model-id", name="example-model", version="1")
    client = MagicMock()
    client.models.get.return_value = model
    client.models.create_or_update.side_effect = lambda value: value
    service = MagicMock()
    with patch("ml_model_factory.azureml._client", return_value=client), patch(
        "azure.storage.blob.BlobServiceClient", return_value=service
    ):
        result = publish_model_report(report_file, runtime)
    assert result["model_id"] == "model-id"
    assert model.tags["quality_gate"] == "passed" and model.tags["aifactory"] == "spider-001"
    assert "mon_old" not in model.tags
    assert model.tags["mon_subject_version"] == "1"
    client.models.get.assert_called_once_with(name="example-model", version="1")


def test_cli_emits_report_and_tag_preview_without_cloud_calls(tmp_path):
    from ml_model_factory.cli import main
    reference, current = frames()
    current["x"] += 10
    baseline, predictions, observed = labels(error=0.4)
    for name, frame in (("reference", reference), ("current", current), ("outcomes", baseline),
                        ("predictions", predictions), ("labels", observed)):
        frame.to_parquet(tmp_path / (name + ".parquet"), index=False)
    write_json(tmp_path / "scenario.json", SCENARIO)
    write_json(tmp_path / "context.json", CONTEXT)
    write_json(tmp_path / "config.json", CONFIG)
    write_json(tmp_path / "metrics.json", {"accuracy": 0.9, "f1_weighted": 0.89})
    args = ["monitor", "--scenario", str(tmp_path / "scenario.json"), "--context", str(tmp_path / "context.json"),
            "--config", str(tmp_path / "config.json"), "--reference", str(tmp_path / "reference.parquet"),
            "--current", str(tmp_path / "current.parquet"), "--reference-outcomes", str(tmp_path / "outcomes.parquet"),
            "--predictions", str(tmp_path / "predictions.parquet"), "--labels", str(tmp_path / "labels.parquet"),
            "--evaluation-metrics", str(tmp_path / "metrics.json"), "--output", str(tmp_path / "out")]
    with patch("ml_model_factory.azureml._client") as azure, patch("azure.storage.blob.BlobServiceClient") as storage:
        assert main(args) == 0
        assert main(["monitor-publish", "--report", str(tmp_path / "out/report.json")]) == 0
        azure.assert_not_called()
        storage.assert_not_called()
    report = json.loads((tmp_path / "out/report.json").read_text())
    assert report["scope"] == {"aifactory": "spider-001", "project": "001", "environment": "dev"}
    assert len(report["input_hashes"]) == 6
    assert any(metric["name"] == "evaluation_reference.f1_weighted" for metric in report["metrics"])


def test_both_factory_reports_follow_the_shared_json_schema():
    import jsonschema
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "monitoring.schema.json").read_text())
    jsonschema.validate(monitor(SCENARIO, CONTEXT, *frames(), CONFIG, now=NOW), schema)
    agent_fixture = root.parent / "40-agent-factory/tests/fixtures/monitoring-agent-v1.json"
    jsonschema.validate(json.loads(agent_fixture.read_text()), schema)


@pytest.mark.parametrize("conflict", ["scope", "version", "task", "newer-window", "newer-assessment"])
def test_publication_rejects_wrong_or_older_model_report_before_blob_writes(conflict, tmp_path):
    report = monitor(SCENARIO, CONTEXT, *frames(), CONFIG, now=NOW)
    file = tmp_path / "report.json"
    write_json(file, report)
    runtime = {**CONTEXT, "subscription_id": "00000000-0000-0000-0000-000000000001",
               "tenant_id": "00000000-0000-0000-0000-000000000002", "resource_group": "rg",
               "workspace_name": "ws", "compute": "cpu", "lake": {
                   "project": "001", "environment": "dev", "use_case": "example", "dataset": "data",
                   "data_version": "v1", "snapshot_id": "s1", "run_id": "r1",
                   "storage": {"account_url": "https://example.blob.core.windows.net", "container": "models"}}}
    tags = {"aifactory": "spider-001", "project": "001", "environment": "dev",
            "use_case": "example", "task_type": "classification"}
    version = "1"
    if conflict == "scope":
        tags["project"] = "002"
    elif conflict == "version":
        version = "2"
    elif conflict == "task":
        tags["task_type"] = "regression"
    elif conflict == "newer-window":
        tags["mon_window_end"] = "2026-09-12T00:00:00Z"
    else:
        tags.update(mon_window_end=report["window"]["end"], mon_checked_at="2026-09-12T01:00:00Z")
    client = MagicMock()
    client.models.get.return_value = SimpleNamespace(name="example-model", version=version, tags=tags)
    with patch("ml_model_factory.azureml._client", return_value=client), patch("azure.storage.blob.BlobServiceClient") as blob:
        with pytest.raises(ValueError):
            publish_model_report(file, runtime)
    blob.assert_not_called()
    client.models.create_or_update.assert_not_called()
