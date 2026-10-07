import json
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ml_model_factory.config import load_json
from ml_model_factory.databricks_jobs import create_job, render_databricks_pipeline, render_job, run_job

ROOT = Path(__file__).resolve().parents[2]
HOST = "https://adb-123456789.1.azuredatabricks.net"
SCENARIO = {"name": "titanic", "task": "classification", "target": "Survived", "features": ["Pclass"],
            "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "a/b", "version": 1, "file": "train.csv"}}


def template():
    value = load_json(ROOT / "user-config" / "databricks" / "job-template.json")
    value["tasks"][0]["existing_cluster_id"] = "cluster-1"
    for item in value["parameters"]:
        if "<" in item["default"]:
            item["default"] = "resolved"
    return value


def settings():
    return {
        "batch": {"input_table": "cat.sch.input", "output_table": "cat.sch.out", "prediction_type": "double"},
        "online": {"registered_model_name": "cat.sch.model", "endpoint_name": "endpoint"},
        "streaming": {"eventhubs_namespace": "ns", "eventhub_name": "hub", "secret_scope": "scope",
                      "connection_string_secret": "secret", "checkpoint_root": "/Volumes/c/s/v",
                      "output_table": "cat.sch.stream", "payload_schema_json": "{}"},
    }


@pytest.mark.parametrize("pattern,task", [("batch", "batch-score"), ("online", "register-serve"), ("streaming", "stream-score")])
def test_render_job_patterns_use_existing_cluster_and_task_values(pattern, task):
    job = render_job(SCENARIO, template(), pattern, settings=settings(), scenario_path="/Workspace/scenario.json")
    added = job["tasks"][1]
    assert added["task_key"] == task
    assert added["existing_cluster_id"] == "cluster-1"
    assert "new_cluster" not in json.dumps(job)
    assert added["depends_on"] == [{"task_key": "train-evaluate"}]
    assert added["notebook_task"]["base_parameters"]["model_uri"] == "{{tasks.train-evaluate.values.model_uri}}"
    if pattern == "streaming":
        assert added["timeout_seconds"] == 0


def test_render_job_azureml_orchestration_uses_job_model_parameter():
    job = render_job(SCENARIO, template(), "batch", settings=settings(),
                     scenario_path="/Workspace/scenario.json", orchestration="azureml")
    assert next(p for p in job["parameters"] if p["name"] == "model_uri")["default"] == ""
    assert job["tasks"][1]["notebook_task"]["base_parameters"]["model_uri"] == "{{job.parameters.model_uri}}"
    assert job["tags"]["orchestration"] == "azureml"


def test_render_reports_unresolved_and_create_refuses_placeholders():
    job = render_job(SCENARIO, load_json(ROOT / "user-config" / "databricks" / "job-template.json"), "batch",
                     settings={}, scenario_path="<scenario>")
    assert job["unresolved"]
    with pytest.raises(ValueError, match="Resolve"):
        create_job(job, host=HOST, execute=True, client=MagicMock())


def test_create_and_run_preview_and_execute_with_fake_client():
    spec = render_job(SCENARIO, template(), "batch", settings=settings(), scenario_path="/Workspace/scenario.json")
    spec.pop("unresolved", None)
    client = MagicMock()
    client.api_client.do.return_value = {"job_id": 42}
    assert create_job(spec, host=HOST)["preview_only"] is True
    assert create_job(spec, host=HOST, execute=True, client=client)["job_id"] == 42
    client.api_client.do.assert_called_once()
    assert client.api_client.do.call_args.kwargs["body"].get("unresolved") is None
    ok = SimpleNamespace(result_state="SUCCESS", life_cycle_state="TERMINATED")
    completed = SimpleNamespace(run_id=7, tasks=[SimpleNamespace(task_key="train-evaluate", run_id=8, state=ok)])
    client.jobs.run_now.return_value.result.return_value = completed
    client.jobs.get_run_output.return_value.notebook_output = SimpleNamespace(result="runs:/abc/model", truncated=False)
    result = run_job(42, host=HOST, execute=True, client=client, wait_seconds=1, only_tasks=["train-evaluate"])
    assert client.jobs.run_now.call_args.kwargs["only"] == ["train-evaluate"]
    assert result["run_id"] == 7
    assert result["tasks"]["train-evaluate"]["notebook_output"] == "runs:/abc/model"


@pytest.mark.parametrize("pattern", ["batch", "online", "streaming"])
def test_render_databricks_pipeline_loads_offline(tmp_path, pattern):
    runtime = {"subscription_id": "00000000-0000-0000-0000-000000000001", "tenant_id": "00000000-0000-0000-0000-000000000002",
               "resource_group": "rg", "workspace_name": "aml", "compute": "cpu"}
    config = {"host": HOST, "workspace_resource_id": "/subscriptions/0/resourceGroups/rg/providers/Microsoft.Databricks/workspaces/dbw", "job_id": 1,
              "train_parameters": {"input_path": "wasbs://c@s.blob.core.windows.net/train.csv"},
              f"{pattern}_parameters": {"scenario_path": "/Workspace/scenario.json"}}
    rendered = render_databricks_pipeline(SCENARIO, runtime, tmp_path, pattern=pattern, databricks=config, source=ROOT)
    from azure.ai.ml import load_job
    job = load_job(rendered["pipeline"])
    assert job.type == "pipeline"
    document = load_json(tmp_path / "manifest.json")
    yaml_doc = __import__("yaml").safe_load((tmp_path / "pipeline.yml").read_text(encoding="utf-8"))
    step = yaml_doc["jobs"][pattern]
    assert step["inputs"]["train_result"] == "${{parent.jobs.train.outputs.result}}"
    assert "${{parent.jobs.train.outputs.result}}" not in step["component"]["command"]
    assert "--job-parameters-file params/" in step["component"]["command"]
    split = shlex.split(step["component"]["command"])
    assert split[split.index("--host") + 1] == HOST
    assert f"--only-task {config.get('task_key', {'batch': 'batch-score', 'online': 'register-serve', 'streaming': 'stream-score'}[pattern])}" in step["component"]["command"]
    assert "--only-task train-evaluate" in yaml_doc["jobs"]["train"]["component"]["command"]
    assert (tmp_path / "code" / "params" / f"{pattern}.json").is_file()
    manifest = document
    assert "Databricks job must already exist" in manifest["limitations"]



def test_run_streaming_waits_for_train_success_and_stream_running():
    client = MagicMock()
    client.jobs.run_now.return_value.run_id = 99
    ok = SimpleNamespace(result_state="SUCCESS", life_cycle_state="TERMINATED")
    running = SimpleNamespace(result_state=None, life_cycle_state="RUNNING")
    run = SimpleNamespace(run_id=99, tasks=[SimpleNamespace(task_key="train-evaluate", run_id=1, state=ok),
                                           SimpleNamespace(task_key="stream-score", run_id=2, state=running)])
    client.jobs.get_run.return_value = run
    client.jobs.get_run_output.return_value.notebook_output = SimpleNamespace(result="", truncated=False)
    result = run_job(42, host=HOST, execute=True, client=client, wait_for="running", wait_seconds=1, only_tasks=["stream-score"])
    assert client.jobs.run_now.call_args.kwargs["only"] == ["stream-score"]
    assert result["state"] == "RUNNING"
    client.jobs.run_now.assert_called_once()


def test_azure_msi_requires_workspace_resource_id():
    spec = render_job(SCENARIO, template(), "batch", settings=settings(), scenario_path="/Workspace/scenario.json")
    spec.pop("unresolved", None)
    with pytest.raises(ValueError, match="workspace-resource-id"):
        create_job(spec, host=HOST, auth="azure-msi", execute=True, client=None)



def test_render_databricks_pipeline_reports_user_placeholders_not_aml_bindings(tmp_path):
    runtime = {"subscription_id": "00000000-0000-0000-0000-000000000001", "tenant_id": "00000000-0000-0000-0000-000000000002",
               "resource_group": "rg", "workspace_name": "aml", "compute": "cpu"}
    config = {"host": HOST, "workspace_resource_id": "/subscriptions/0/resourceGroups/rg/providers/Microsoft.Databricks/workspaces/dbw",
              "job_id": 1, "train_parameters": {"input_path": "<input>"}, "batch_parameters": {"input_table": "<table>"}}
    result = render_databricks_pipeline(SCENARIO, runtime, tmp_path, pattern="batch", databricks=config, source=ROOT)
    assert result["unresolved"]
    assert not any("parent.jobs" in item for item in result["unresolved"])



def test_run_streaming_only_task_does_not_require_train_task_in_same_run():
    client = MagicMock()
    client.jobs.run_now.return_value.run_id = 101
    running = SimpleNamespace(result_state=None, life_cycle_state="RUNNING")
    run = SimpleNamespace(run_id=101, tasks=[SimpleNamespace(task_key="stream-score", run_id=2, state=running)])
    client.jobs.get_run.return_value = run
    client.jobs.get_run_output.return_value.notebook_output = SimpleNamespace(result="", truncated=False)
    result = run_job(42, host=HOST, execute=True, client=client, wait_for="running", wait_seconds=1, only_tasks=["stream-score"])
    assert result["state"] == "RUNNING"



def test_render_pipeline_rejects_unvalidated_command_values(tmp_path):
    runtime = {"subscription_id": "00000000-0000-0000-0000-000000000001", "tenant_id": "00000000-0000-0000-0000-000000000002",
               "resource_group": "rg", "workspace_name": "aml", "compute": "cpu"}
    bad = {"host": HOST, "workspace_resource_id": "/subscriptions/0/resourceGroups/rg/providers/Microsoft.Databricks/workspaces/dbw",
           "job_id": 1, "client_id": "not-a-uuid"}
    with pytest.raises(ValueError):
        render_databricks_pipeline(SCENARIO, runtime, tmp_path, pattern="batch", databricks=bad, source=ROOT)


def test_run_job_receipt_reuses_token_and_records_timeout(tmp_path):
    receipt = tmp_path / "run.json"
    client = MagicMock()
    client.jobs.run_now.return_value.run_id = 55
    client.jobs.run_now.return_value.result.side_effect = TimeoutError("slow")
    with pytest.raises(TimeoutError, match="55"):
        run_job(42, host=HOST, execute=True, client=client, wait_seconds=1, receipt=receipt, only_tasks=["batch-score"])
    first = load_json(receipt)
    assert first["status"] == "timed_out"
    assert first["run_id"] == 55
    token = first["idempotency_token"]
    client.jobs.run_now.return_value.result.side_effect = TimeoutError("slow again")
    with pytest.raises(TimeoutError):
        run_job(42, host=HOST, execute=True, client=client, wait_seconds=1, receipt=receipt, only_tasks=["batch-score"])
    assert client.jobs.run_now.call_args.kwargs["idempotency_token"] == token


def test_run_job_new_run_archives_non_succeeded_receipt(tmp_path):
    receipt = tmp_path / "run.json"
    receipt.write_text(json.dumps({"status": "timed_out", "idempotency_token": "old"}), encoding="utf-8")
    client = MagicMock()
    ok = SimpleNamespace(result_state="SUCCESS", life_cycle_state="TERMINATED")
    completed = SimpleNamespace(run_id=9, tasks=[SimpleNamespace(task_key="batch-score", run_id=10, state=ok)])
    client.jobs.run_now.return_value.run_id = 9
    client.jobs.run_now.return_value.result.return_value = completed
    client.jobs.get_run_output.return_value.notebook_output = SimpleNamespace(result='{"ok": true}', truncated=False)
    run_job(42, host=HOST, execute=True, client=client, wait_seconds=1, receipt=receipt, only_tasks=["batch-score"], new_run=True)
    assert list(tmp_path.glob("run.json.*.archive"))
    assert load_json(receipt)["status"] == "succeeded"
