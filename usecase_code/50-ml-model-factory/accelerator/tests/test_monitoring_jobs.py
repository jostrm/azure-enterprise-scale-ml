"""Offline recurrence definitions and real monitor commands; cloud creation is mocked."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml

from ml_model_factory.config import TASKS, write_json
from scripts.monitoring_job import ROOT, create_schedule, load_monitoring_schedule, main, render


SCENARIO = {
    "name": "example", "model_name": "example-model", "task": "classification",
    "target": "label", "features": ["x"], "categorical_features": [],
    "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/data", "version": 1},
}
RUNTIME = {
    "subscription_id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
    "resource_group": "existing-rg", "workspace_name": "existing-workspace", "compute": "existing-cpu",
    "aifactory": "factory-001", "project": "001", "environment_name": "dev", "credential": "azure_cli",
    "lake": {
        "aifactory": "factory-001", "project": "001", "environment": "dev", "use_case": "example",
        "dataset": "data", "data_version": "v1", "snapshot_id": "snapshot-1", "run_id": "run-1",
        "model_version": "7",
        "storage": {"account_url": "https://example.blob.core.windows.net", "container": "models"},
    },
}
INPUTS = {
    "config_uri": "azureml://datastores/observations/paths/monitoring/current.json",
    "reference_uri": "azureml:reference:1",
    "current_uri": "azureml://datastores/observations/paths/monitoring/current.parquet",
}
PERFORMANCE = {
    "reference_outcomes_uri": "azureml:baseline_outcomes:1",
    "predictions_uri": "azureml://datastores/observations/paths/monitoring/predictions.parquet",
    "labels_uri": "azureml://datastores/observations/paths/monitoring/observed-labels.parquet",
}


def documents(tmp_path, **options):
    runtime = options.pop("runtime", deepcopy(RUNTIME))
    scenario = options.pop("scenario", deepcopy(SCENARIO))
    rendered = render(runtime, scenario, tmp_path, **(INPUTS | options))
    return rendered, yaml.safe_load(Path(rendered["job"]).read_text(encoding="utf-8")), yaml.safe_load(
        Path(rendered["schedule"]).read_text(encoding="utf-8"))


def test_scheduled_reports_can_expose_all_reference_evaluation_metrics(tmp_path):
    _, job, _ = documents(tmp_path, evaluation_metrics_uri="azureml:evaluation_metrics:1")
    assert job["inputs"]["evaluation_metrics"]["path"] == "azureml:evaluation_metrics:1"
    assert "--evaluation-metrics" in job["jobs"]["monitor"]["command"]
    assert "publish" not in job["jobs"]


@pytest.mark.parametrize("task", sorted(TASKS))
@pytest.mark.parametrize("performance", [False, True])
def test_seven_model_types_load_as_real_v2_pipeline_schedules(tmp_path, task, performance):
    from azure.ai.ml import load_job
    from azure.ai.ml.entities import JobSchedule, RecurrenceTrigger

    scenario = {**SCENARIO, "task": task}
    if task == "forecasting":
        scenario["forecast"] = {"time_column": "date", "frequency": "D", "horizon": 3}
    paths, job, schedule = documents(tmp_path, scenario=scenario, **(PERFORMANCE if performance else {}))
    loaded = load_job(paths["job"])
    assert loaded.type == "pipeline"
    assert loaded.settings.force_rerun is True
    assert loaded.inputs["config"].mode == "download"
    assert loaded.inputs["config"].path == INPUTS["config_uri"]
    assert loaded.jobs["monitor"].identity.type == "managed_identity"
    assert loaded.jobs["monitor"].component.environment.conda_file["dependencies"][0] == "python=3.10"
    recurring = load_monitoring_schedule(paths["schedule"])
    assert isinstance(recurring, JobSchedule)
    assert isinstance(recurring.trigger, RecurrenceTrigger)
    assert recurring.create_job.type == "pipeline"
    assert recurring.trigger.interval == 24
    assert schedule["create_job"] == "./job.yml"
    assert "publish" not in job["jobs"]
    assert job["tags"]["task_type"] == task
    assert "path" not in job["outputs"]["report"]
    optional = {"reference_outcomes", "predictions", "labels"}
    assert optional.issubset(job["inputs"]) if performance else not optional.intersection(job["inputs"])
    command = job["jobs"]["monitor"]["command"]
    assert "--no-deps --no-build-isolation" in command
    assert "pip install" in command and "ml_model_factory monitor" in command
    assert "--labels" in command if performance else "--labels" not in command
    assert "--execute" not in command and "monitor-publish" not in command


def test_publication_is_explicit_and_pins_scope_model_version_and_managed_identity(tmp_path):
    runtime = deepcopy(RUNTIME)
    runtime["managed_identity_client_id"] = "00000000-0000-0000-0000-000000000003"
    paths, job, schedule = documents(tmp_path, runtime=runtime, publish=True, **PERFORMANCE)
    context = json.loads((tmp_path / "context.json").read_text(encoding="utf-8"))
    assert context["credential"] == "managed_identity"
    assert context["lake"]["model_version"] == "7"
    assert {key: schedule["tags"][key] for key in ("aifactory", "project", "environment")} == {
        "aifactory": "factory-001", "project": "001", "environment": "dev"}
    assert schedule["tags"]["monitoring_model_version"] == "7"
    assert schedule["tags"]["monitoring_publish"] == "true"
    publish = job["jobs"]["publish"]
    assert publish["inputs"]["report"] == "${{parent.jobs.monitor.outputs.report}}"
    assert publish["inputs"]["runtime"] == "${{parent.inputs.context}}"
    assert publish["command"].endswith('--runtime "${{inputs.runtime}}" --execute')
    assert 'monitor-publish --report "${{inputs.report}}/report.json"' in publish["command"]
    assert publish["identity"] == {
        "type": "managed", "client_id": runtime["managed_identity_client_id"]}
    loaded = load_monitoring_schedule(paths["schedule"])
    assert loaded.create_job.jobs["publish"].identity.client_id == runtime["managed_identity_client_id"]
    assert loaded.create_job.settings.continue_on_step_failure is False


@pytest.mark.parametrize("fault", ["scope", "scope_conflict", "lake", "version", "alias", "storage", "use_case"])
def test_publish_requires_an_explicit_safe_existing_target(tmp_path, fault):
    runtime = deepcopy(RUNTIME)
    if fault == "scope":
        del runtime["aifactory"]
        del runtime["lake"]["aifactory"]
    elif fault == "scope_conflict":
        runtime["lake"]["project"] = "999"
    elif fault == "lake":
        del runtime["lake"]
    elif fault == "version":
        del runtime["lake"]["model_version"]
    elif fault == "alias":
        runtime["lake"]["model_version"] = "latest"
    elif fault == "storage":
        del runtime["lake"]["storage"]["account_url"]
    else:
        runtime["lake"]["use_case"] = "another-use-case"
    with pytest.raises(ValueError):
        documents(tmp_path, runtime=runtime, publish=True)
    assert not list(tmp_path.iterdir())


def test_minimal_report_runtime_has_no_publication_requirement(tmp_path):
    runtime = {key: value for key, value in RUNTIME.items() if key != "lake"}
    _, job, _ = documents(tmp_path, runtime=runtime)
    assert set(job["jobs"]) == {"monitor"}


def test_bundle_whitelists_runtime_and_source_and_has_no_training_dependencies(tmp_path):
    runtime, scenario = deepcopy(RUNTIME), deepcopy(SCENARIO)
    runtime.update(client_secret="NEVER_COPY_SECRET", environment_variables={"TOKEN": "NEVER_COPY_SECRET"},
                   input_data="secret-dataset-path", unexpected={"password": "NEVER_COPY_SECRET"})
    runtime["lake"]["storage"]["account_key"] = "NEVER_COPY_SECRET"
    scenario["dataset"]["credentials"] = "NEVER_COPY_SECRET"
    scenario["environment_variables"] = {"TOKEN": "NEVER_COPY_SECRET"}
    paths, _, _ = documents(tmp_path, runtime=runtime, scenario=scenario)
    source = Path(paths["source"])
    assert set(path.name for path in source.iterdir()) == {"pyproject.toml", "scripts", "ml_model_factory"}
    assert set(path.name for path in (source / "scripts").iterdir()) == {"monitoring_job.py"}
    assert all(path.suffix == ".py" for path in (source / "ml_model_factory").iterdir())
    assert not list(source.rglob("*.json"))
    assert all("NEVER_COPY_SECRET" not in path.read_text(encoding="utf-8")
               for path in tmp_path.rglob("*") if path.is_file())
    environment = yaml.safe_load((tmp_path / "environments" / "monitoring.yml").read_text(encoding="utf-8"))
    dependencies = next(item["pip"] for item in environment["dependencies"] if isinstance(item, dict))
    assert not any(value.startswith(("azure-", "mlflow", "scikit-learn", "torch")) for value in dependencies)
    assert "Pillow>=11,<13" in dependencies


@pytest.mark.parametrize("bad", [
    "", None, "local.parquet", "azureml:current@latest", "azureml:current:latest",
    "https://example.blob.core.windows.net/data/current.parquet?sig=secret",
    "https://user:password@example.blob.core.windows.net/data/current.parquet",
    "http://example.blob.core.windows.net/data/current.parquet",
    "https://thirdparty.example/data.parquet", "azureml://datastores/data/paths/../private.parquet",
    "azureml://datastores/data/paths/folder/", "azureml://datastores/data/paths/a;injected",
])
def test_remote_inputs_are_explicit_and_never_copy_credentials_or_local_snapshots(tmp_path, bad):
    with pytest.raises(ValueError):
        documents(tmp_path, current_uri=bad)
    assert not list(tmp_path.iterdir())


def test_labels_are_optional_but_never_inferred(tmp_path):
    with pytest.raises(ValueError, match="Observed labels"):
        documents(tmp_path, labels_uri=PERFORMANCE["labels_uri"])
    _, job, _ = documents(tmp_path, predictions_uri=PERFORMANCE["predictions_uri"])
    assert "predictions" in job["inputs"] and "labels" not in job["inputs"]


def test_recurrence_preserves_period_time_zone_and_bounds(tmp_path):
    paths, _, schedule = documents(
        tmp_path, interval_hours=6, time_zone="W. Europe Standard Time",
        start_time="2026-10-01T08:00:00", end_time="2026-12-01T08:00:00",
    )
    assert schedule["trigger"] == {
        "type": "recurrence", "frequency": "hour", "interval": 6, "time_zone": "W. Europe Standard Time",
        "start_time": "2026-10-01T08:00:00", "end_time": "2026-12-01T08:00:00",
    }
    loaded = load_monitoring_schedule(paths["schedule"])
    assert loaded.trigger.time_zone == "W. Europe Standard Time"
    assert loaded.trigger.interval == 6


@pytest.mark.parametrize("options", [
    {"interval_hours": 0}, {"interval_hours": -1}, {"interval_hours": 1.5}, {"interval_hours": True},
    {"time_zone": ""}, {"start_time": "tomorrow"}, {"start_time": "2026-10-01"},
    {"start_time": "2026-10-02T00:00:00Z", "end_time": "2026-10-01T00:00:00Z"},
    {"start_time": "2026-10-01T00:00:00Z", "end_time": "2026-10-02T00:00:00"},
    {"publish": "false"},
])
def test_invalid_recurrence_or_publication_flag_fails_before_writing(tmp_path, options):
    with pytest.raises(ValueError):
        documents(tmp_path, **options)
    assert not list(tmp_path.iterdir())


def test_existing_bundles_are_not_overwritten(tmp_path):
    documents(tmp_path)
    before = (tmp_path / "job.yml").read_bytes()
    with pytest.raises(ValueError, match="new empty"):
        documents(tmp_path, publish=True)
    assert (tmp_path / "job.yml").read_bytes() == before


def test_preview_is_offline_and_only_execute_uses_public_sdk_schedule_create(tmp_path):
    paths, _, _ = documents(tmp_path)
    client = MagicMock()
    client.schedules.begin_create_or_update.return_value.result.return_value = SimpleNamespace(
        name="created-monitor", id="created-monitor-id",
    )
    with patch("ml_model_factory.azureml._client", return_value=client) as get_client:
        preview = create_schedule(paths["schedule"], deepcopy(RUNTIME))
        assert preview["preview_only"] is True and preview["cloud_created"] is False
        get_client.assert_not_called()
        result = create_schedule(paths["schedule"], deepcopy(RUNTIME), execute=True)
        get_client.assert_called_once_with(RUNTIME)
    assert result["cloud_created"] is True
    submitted = client.schedules.begin_create_or_update.call_args.args[0]
    assert submitted.create_job.type == "pipeline" and submitted.trigger.frequency == "hour"


def test_create_rejects_cross_scope_before_any_cloud_request(tmp_path):
    paths, _, _ = documents(tmp_path)
    runtime = deepcopy(RUNTIME)
    runtime["project"] = runtime["lake"]["project"] = "999"
    with patch("ml_model_factory.azureml._client") as client, pytest.raises(ValueError, match="differs"):
        create_schedule(paths["schedule"], runtime, execute=True)
    client.assert_not_called()


def test_python_creation_api_requires_a_boolean_opt_in(tmp_path):
    with patch("ml_model_factory.azureml._client") as client, pytest.raises(ValueError, match="boolean"):
        create_schedule(tmp_path / "schedule.yml", RUNTIME, execute="false")
    client.assert_not_called()


def _run_rendered_monitor(bundle: Path, job: dict, local_inputs: dict[str, Path], output: Path):
    command = job["jobs"]["monitor"]["command"].split(" && ", 1)[1]
    for key, path in local_inputs.items():
        command = command.replace("${{inputs." + key + "}}", str(path))
    command = command.replace("${{outputs.report}}", str(output))
    argv = shlex.split(command)
    argv[0] = sys.executable
    result = subprocess.run(argv, cwd=bundle / "source", text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads((output / "report.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("performance", [False, True])
def test_rendered_command_executes_and_dataops_config_not_job_time_controls_freshness(tmp_path, performance):
    bundle = tmp_path / "bundle with spaces"
    _, job, _ = documents(bundle, **(PERFORMANCE if performance else {}))
    frame = pd.DataFrame({"x": np.linspace(-2, 2, 200)})
    reference, current = tmp_path / "reference.parquet", tmp_path / "current.parquet"
    frame.to_parquet(reference, index=False)
    frame.to_parquet(current, index=False)
    config = tmp_path / "dataops-config.json"
    monitoring = {
        "model_version": "7",
        "reference_window": {"start": "2000-01-01T00:00:00Z", "end": "2000-02-01T00:00:00Z"},
        "window": {"start": "2000-03-01T00:00:00Z", "end": "2000-03-02T00:00:00Z"},
        "max_age_hours": 24,
    }
    write_json(config, monitoring)
    original_config = config.read_bytes()
    local_inputs = {
        "scenario": bundle / "scenario.json", "context": bundle / "context.json",
        "config": config, "reference": reference, "current": current,
    }
    if performance:
        truth = np.tile([0, 1], 100)
        data = {
            "reference_outcomes": pd.DataFrame({
                "request_id": [f"reference-{i}" for i in range(200)], "actual": truth,
                "prediction": truth, "model_version": "7",
            }),
            "predictions": pd.DataFrame({
                "request_id": [f"current-{i}" for i in range(200)], "prediction": truth, "model_version": "7",
            }),
            "labels": pd.DataFrame({
                "request_id": [f"current-{i}" for i in range(200)], "label": truth,
                "observed_at": "2000-03-03T00:00:00Z",
            }),
        }
        for key, values in data.items():
            local_inputs[key] = tmp_path / f"{key}.parquet"
            values.to_parquet(local_inputs[key], index=False)
    report = _run_rendered_monitor(bundle, job, local_inputs, tmp_path / "old-window-report")
    assert report["schema"] == "aifactory.monitoring/v1"
    assert report["subject"]["version"] == "7"
    assert report["window"] == monitoring["window"]
    assert set(report["summary"].values()) == {"stale"}
    assert config.read_bytes() == original_config
    assert (tmp_path / "old-window-report" / "tags.json").is_file()
    rerun = _run_rendered_monitor(bundle, job, local_inputs, tmp_path / "old-window-rerun")
    assert set(rerun["summary"].values()) == {"stale"}
    assert rerun["expires_at"] == report["expires_at"]
    assert config.read_bytes() == original_config

    # Only DataOps advancing the observed input window makes a subsequent run current.
    now = datetime.now(timezone.utc)
    monitoring["window"] = {
        "start": (now - timedelta(hours=2)).isoformat(), "end": (now - timedelta(hours=1)).isoformat(),
    }
    if performance:
        data["labels"]["observed_at"] = (now - timedelta(minutes=30)).isoformat()
        data["labels"].to_parquet(local_inputs["labels"], index=False)
    write_json(config, monitoring)
    updated_config = config.read_bytes()
    fresh = _run_rendered_monitor(bundle, job, local_inputs, tmp_path / "new-window-report")
    assert fresh["window"] == {key: value.replace("+00:00", "Z") for key, value in monitoring["window"].items()}
    assert fresh["summary"]["data_drift"] == "healthy"
    assert fresh["summary"]["concept_drift"] == ("healthy" if performance else "unknown")
    assert config.read_bytes() == updated_config


def test_cli_render_is_offline_and_reports_exact_output_paths(tmp_path, capsys):
    runtime, scenario, output = tmp_path / "runtime.json", tmp_path / "scenario.json", tmp_path / "bundle"
    write_json(runtime, RUNTIME)
    write_json(scenario, SCENARIO)
    with patch("ml_model_factory.azureml._client") as client:
        assert main([
            "render", "--runtime", str(runtime), "--scenario", str(scenario),
            "--output", str(output), "--interval-hours", "12",
            *[part for key, value in INPUTS.items() for part in ("--" + key.replace("_", "-"), value)],
        ]) == 0
        client.assert_not_called()
    result = json.loads(capsys.readouterr().out)
    assert result["job"] == str(output / "job.yml") and result["cloud_created"] is False
    assert result["publish"] is False


def test_environment_ranges_match_parent_dependency_contract():
    tomllib = pytest.importorskip("tomllib")

    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    from scripts.monitoring_job import AZURE_DEPENDENCIES
    assert AZURE_DEPENDENCIES == manifest["project"]["optional-dependencies"]["azure"]
