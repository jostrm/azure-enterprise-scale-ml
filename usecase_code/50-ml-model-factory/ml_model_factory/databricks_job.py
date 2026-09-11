"""Invoke an existing Databricks job from an Azure ML v2 command component."""

import argparse
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from .config import write_json


def run_job(host: str, workspace_resource_id: str, job_id: int, parameters: dict,
            output: Path, *, task_key: str = "train-evaluate", timeout_seconds: int = 3600,
            client_id: str | None = None, idempotency_token: str | None = None) -> dict:
    from databricks.sdk import WorkspaceClient

    url = urlsplit(host)
    if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".azuredatabricks.net")
            or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
        raise ValueError("host must be an HTTPS Azure Databricks workspace URL without credentials")
    if "/providers/Microsoft.Databricks/workspaces/" not in workspace_resource_id:
        raise ValueError("Provide the existing Azure Databricks workspace ARM resource ID")
    if job_id < 1 or timeout_seconds < 1:
        raise ValueError("job_id and timeout_seconds must be positive")
    if not parameters.get("input_path", "").startswith(("wasbs://", "abfss://", "/Volumes/")):
        raise ValueError("Pass a Databricks-readable data URI, not an Azure ML mounted local path")
    client = WorkspaceClient(
        host=host, auth_type="azure-msi", azure_workspace_resource_id=workspace_resource_id,
        azure_use_msi=True, **({"azure_client_id": client_id} if client_id else {}),
    )
    token = idempotency_token or uuid4().hex
    if len(token) > 64:
        raise ValueError("Databricks idempotency tokens must contain at most 64 characters")
    waiter = client.jobs.run_now(job_id=job_id, job_parameters=parameters, idempotency_token=token)
    # The SDK raises for failure/cancellation and for the bounded completion timeout.
    completed = waiter.result(timeout=timedelta(seconds=timeout_seconds))
    tasks = [task for task in (completed.tasks or []) if task.task_key == task_key]
    if len(tasks) != 1 or not tasks[0].run_id:
        raise ValueError(f"Completed job must expose exactly one notebook task named {task_key!r}")
    notebook = client.jobs.get_run_output(tasks[0].run_id).notebook_output
    if notebook is None or notebook.truncated or not notebook.result:
        raise ValueError("The training notebook did not return a complete model URI")
    model_uri = notebook.result
    if not model_uri.startswith(("runs:/", "models:/")):
        raise ValueError("The training notebook result must be an MLflow model URI")
    result = {"run_id": completed.run_id, "task_run_id": tasks[0].run_id,
              "model_uri": model_uri, "host": host, "idempotency_token": token}
    output = Path(output)
    write_json(output / "result.json", result)
    (output / "model_uri.txt").write_text(model_uri + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("host", "workspace-resource-id", "scenario-path", "input-uri", "artifact-root", "experiment-path", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--job-id", required=True, type=int)
    parser.add_argument("--task-key", default="train-evaluate")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--client-id")
    parser.add_argument("--idempotency-token")
    args = parser.parse_args()
    run_job(args.host, args.workspace_resource_id, args.job_id, {
        "scenario_path": args.scenario_path, "input_path": args.input_uri,
        "artifact_root": args.artifact_root, "experiment_path": args.experiment_path,
    }, Path(args.output), task_key=args.task_key, timeout_seconds=args.timeout_seconds,
        client_id=args.client_id, idempotency_token=args.idempotency_token)


if __name__ == "__main__":
    main()
