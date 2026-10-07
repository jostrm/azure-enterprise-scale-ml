from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock
import json
import shlex

import pytest
import yaml

from ml_model_factory.config import write_json
from ml_model_factory.stream_jobs import render_stream_job, create_stream_schedule, submit_stream_job

SCENARIO = {
    "name": "fixture-stream", "model_name": "fixture-stream", "task": "classification",
    "target": "label", "features": ["x"], "categorical_features": [],
    "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/data", "version": 1},
}
RUNTIME = {
    "subscription_id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
    "resource_group": "rg", "workspace_name": "ws", "compute": "cpu",
    "aifactory": "factory-001", "project": "001", "environment_name": "dev",
    "streaming": {"eventhubs": {"namespace": "exampleeh.servicebus.windows.net", "eventhub": "events", "consumer_group": "$Default"}},
    "lake": {"aifactory": "factory-001", "project": "001", "environment": "dev", "use_case": "fixture-stream",
             "dataset": "data", "data_version": "v1", "snapshot_id": "snapshot1", "run_id": "run1",
             "pipeline_id": "stream", "pipeline_version": "v1",
             "storage": {"datastore": "lake", "account_url": "https://examplest.blob.core.windows.net", "container": "models"}},
    "datastore": "lake",
}

def test_render_stream_job_loads_offline_and_pins_lake_outputs(tmp_path):
    files = render_stream_job(SCENARIO, deepcopy(RUNTIME), tmp_path, model_id="azureml:model:7", mode="custom",
                              interval_minutes=15, timeout_seconds=60)
    from azure.ai.ml import load_job
    job = yaml.safe_load(Path(files["job"]).read_text(encoding="utf-8"))
    loaded = load_job(files["job"])
    assert loaded.type == "pipeline"
    assert job["outputs"]["checkpoint"]["path"].endswith("/operations/streaming/stream/versions/v1/checkpoints/")
    assert "/inference/streaming/models/7/runs/run1/out/" in job["outputs"]["predictions"]["path"]
    command = job["jobs"]["stream_score"]["command"]
    argv = shlex.split(command.split(" && ", 1)[1], posix=True)
    assert argv[argv.index("--consumer-group") + 1] == "$Default"
    assert argv[argv.index("--initial-position") + 1] == "latest"
    assert "--source eventhubs" in command and "--credential managed_identity" in command
    assert "--timeout-seconds 30.0" in command
    assert job["jobs"]["stream_score"]["limits"]["timeout"] == 120
    env = yaml.safe_load((tmp_path / "environments" / "azureml-streaming-custom.yml").read_text(encoding="utf-8"))
    pip = next(item["pip"] for item in env["dependencies"] if isinstance(item, dict))
    assert "azure-eventhub>=5.11,<6" in pip
    manifest = json.loads(Path(files["manifest"]).read_text())
    assert "not continuous streaming" in manifest["limitations"][0]

def test_render_refuses_missing_lake_mutable_model_connection_strings_and_overlaps(tmp_path):
    with pytest.raises(ValueError, match="lake"):
        render_stream_job(SCENARIO, {k: v for k, v in RUNTIME.items() if k != "lake"}, tmp_path / "a",
                          model_id="azureml:model:7", mode="custom")
    with pytest.raises(ValueError, match="immutable"):
        render_stream_job(SCENARIO, deepcopy(RUNTIME), tmp_path / "b", model_id="azureml:model:latest", mode="custom")
    bad = deepcopy(RUNTIME)
    bad["streaming"]["eventhubs"]["namespace"] = "Endpoint=sb://secret"
    with pytest.raises(ValueError, match="namespace"):
        render_stream_job(SCENARIO, bad, tmp_path / "c", model_id="azureml:model:7", mode="custom")
    with pytest.raises(ValueError, match="overlapping"):
        render_stream_job(SCENARIO, deepcopy(RUNTIME), tmp_path / "d", model_id="azureml:model:7", mode="custom",
                          interval_minutes=1, timeout_seconds=60)
    bad_identity = deepcopy(RUNTIME)
    bad_identity["managed_identity_client_id"] = "not-a-uuid"
    with pytest.raises(ValueError):
        render_stream_job(SCENARIO, bad_identity, tmp_path / "e", model_id="azureml:model:7", mode="custom",
                          timeout_seconds=60)
    metachar = deepcopy(RUNTIME)
    metachar["streaming"]["eventhubs"]["eventhub"] = "events;echo-pwned"
    with pytest.raises(ValueError):
        render_stream_job(SCENARIO, metachar, tmp_path / "f", model_id="azureml:model:7", mode="custom",
                          timeout_seconds=60)

def test_schedule_and_submit_preview_and_execute_with_injected_clients(tmp_path):
    files = render_stream_job(SCENARIO, deepcopy(RUNTIME), tmp_path, model_id="azureml:model:7", mode="custom",
                              interval_minutes=15, timeout_seconds=60)
    assert create_stream_schedule(files["schedule"], deepcopy(RUNTIME))["preview_only"] is True
    assert submit_stream_job(files["job"], deepcopy(RUNTIME))["preview_only"] is True
    client = MagicMock()
    client.schedules.begin_create_or_update.return_value.result.return_value = SimpleNamespace(name="sched", id="sid")
    client.jobs.create_or_update.return_value = SimpleNamespace(name="job", id="jid")
    assert create_stream_schedule(files["schedule"], deepcopy(RUNTIME), execute=True, client=client)["id"] == "sid"
    assert submit_stream_job(files["job"], deepcopy(RUNTIME), execute=True, client=client)["id"] == "jid"

def test_stream_job_cli_render(tmp_path, capsys):
    runtime, scenario = tmp_path / "runtime.json", tmp_path / "scenario.json"
    write_json(runtime, RUNTIME)
    write_json(scenario, SCENARIO)
    from ml_model_factory import cli
    assert cli.main(["stream-job", "render", "--runtime", str(runtime), "--scenario", str(scenario),
                     "--model-id", "azureml:model:7", "--mode", "custom", "--output", str(tmp_path / "bundle"),
                     "--interval-minutes", "15", "--timeout-seconds", "60", "--read-timeout-seconds", "10"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["job"].endswith("job.yml")


def test_stream_job_environment_is_pinned_or_conda_with_event_hubs(tmp_path):
    image = {"name": "fixture-image", "model_name": "fixture-image", "task": "image_classification",
             "dataset": SCENARIO["dataset"]}
    runtime = deepcopy(RUNTIME)
    runtime["lake"]["use_case"] = "fixture-image"
    with pytest.raises(ValueError, match="streaming_environment"):
        render_stream_job(image, deepcopy(runtime), tmp_path / "a", model_id="azureml:model:7", mode="automl",
                          timeout_seconds=60)
    runtime["streaming_environment"] = "azureml:automl-image-streaming:2"
    files = render_stream_job(image, runtime, tmp_path / "b", model_id="azureml:model:7", mode="automl",
                              timeout_seconds=60)
    job = yaml.safe_load(Path(files["job"]).read_text(encoding="utf-8"))
    assert job["jobs"]["stream_score"]["environment"] == "azureml:automl-image-streaming:2"
    files = render_stream_job(SCENARIO, deepcopy(RUNTIME), tmp_path / "c", model_id="azureml:model:7", mode="automl",
                              timeout_seconds=60)
    env = yaml.safe_load((tmp_path / "c" / "environments" / "azureml-streaming-automl.yml").read_text(encoding="utf-8"))
    pip = next(item["pip"] for item in env["dependencies"] if isinstance(item, dict))
    assert any(item.startswith("azureml-automl-runtime") for item in pip) and "azure-eventhub>=5.11,<6" in pip
    with pytest.raises(ValueError, match="pinned"):
        render_stream_job(SCENARIO, {**deepcopy(RUNTIME), "streaming_environment": "my-env"}, tmp_path / "d",
                          model_id="azureml:model:7", mode="custom", timeout_seconds=60)


def test_registered_model_arm_ids_from_rollout_receipts_are_normalized(tmp_path):
    arm = ("azureml:/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg/providers/"
           "Microsoft.MachineLearningServices/workspaces/ws/models/M02_diabetes/versions/4")
    files = render_stream_job(SCENARIO, deepcopy(RUNTIME), tmp_path, model_id=arm, mode="custom", timeout_seconds=60)
    job = yaml.safe_load(Path(files["job"]).read_text(encoding="utf-8"))
    assert job["inputs"]["model"]["path"] == "azureml:M02_diabetes:4"
    assert "--model-version 4" in job["jobs"]["stream_score"]["command"]
