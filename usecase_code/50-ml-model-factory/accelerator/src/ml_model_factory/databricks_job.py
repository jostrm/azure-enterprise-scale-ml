"""Invoke an existing Databricks job from an Azure ML v2 command component."""

import argparse
import hashlib
import os
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4

from .config import load_json, write_json

IMMUTABLE_MODEL = re.compile(r"(?:runs:/[^?#]+/model|models:/[^/@?#]+/[1-9][0-9]*)")


def _validate_host(host: str) -> None:
    url = urlsplit(host)
    if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".azuredatabricks.net")
            or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
        raise ValueError("host must be an HTTPS Azure Databricks workspace URL without credentials")


def _immutable_model_uri(value: str) -> str:
    if not isinstance(value, str) or not IMMUTABLE_MODEL.fullmatch(value):
        raise ValueError("model_uri must be an immutable runs:/.../model or numeric models:/name/version URI")
    return value


def _read_model_uri_file(path: Path) -> str:
    return _immutable_model_uri(Path(path).read_text(encoding="utf-8").strip())


def _default_token(task_key: str, only_tasks: list[str] | None) -> str:
    run_id = os.environ.get("AZUREML_RUN_ID")
    if not run_id:
        return uuid4().hex
    material = json.dumps({"azureml_run_id": run_id, "task_key": task_key, "only": only_tasks or []}, sort_keys=True)
    return "aml-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:60]


def _state_value(state, name):
    value = getattr(state, name, None)
    return getattr(value, "value", value)


def _task(run, task_key):
    tasks = [task for task in (getattr(run, "tasks", None) or []) if getattr(task, "task_key", None) == task_key]
    if len(tasks) != 1:
        raise ValueError(f"Run must expose exactly one task named {task_key!r}")
    return tasks[0]


def _success(task) -> bool:
    state = getattr(task, "state", None)
    result = _state_value(state, "result_state")
    lifecycle = _state_value(state, "life_cycle_state") or _state_value(state, "lifecycle_state")
    return result == "SUCCESS" or (result is None and lifecycle in (None, "TERMINATED"))


def _running(task) -> bool:
    state = getattr(task, "state", None)
    lifecycle = _state_value(state, "life_cycle_state") or _state_value(state, "lifecycle_state")
    return lifecycle in {"RUNNING", "PENDING", "QUEUED"} and _state_value(state, "result_state") is None


def _wait_for_running(client, run_id, *, task_key, timeout_seconds, train_task_key="train-evaluate"):
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    last = None
    while datetime.now(timezone.utc) < deadline:
        run = client.jobs.get_run(run_id)
        last = run
        try:
            train = _task(run, train_task_key)
            train_ready = _success(train)
        except ValueError:
            train_ready = True
        stream = _task(run, task_key)
        if train_ready and _running(stream):
            return run
        failed = [task for task in (getattr(run, "tasks", None) or [])
                  if _state_value(getattr(task, "state", None), "result_state") not in (None, "SUCCESS")]
        if failed:
            raise ValueError("Databricks run failed before the streaming task reached RUNNING")
        time.sleep(5)
    raise TimeoutError(f"Databricks run {run_id} did not reach streaming RUNNING within {timeout_seconds}s; last={last!r}")


def _task_output(client, task) -> tuple[str | None, dict | None]:
    notebook = client.jobs.get_run_output(task.run_id).notebook_output
    if notebook is None or notebook.truncated or not notebook.result:
        raise ValueError("The selected notebook did not return a complete result")
    result_text = notebook.result
    parsed = None
    try:
        parsed = json.loads(result_text)
    except Exception:
        pass
    return result_text, parsed if isinstance(parsed, dict) else None


def run_existing_job(host: str, workspace_resource_id: str, job_id: int, parameters: dict,
                     output: Path, *, task_key: str, timeout_seconds: int = 3600,
                     client_id: str | None = None, idempotency_token: str | None = None,
                     client=None, wait_for: str = "terminated", only_tasks: list[str] | None = None) -> dict:
    if wait_for not in {"running", "terminated"}:
        raise ValueError("wait_for must be running or terminated")
    if client is None:
        from databricks.sdk import WorkspaceClient
        client = WorkspaceClient(
            host=host, auth_type="azure-msi", azure_workspace_resource_id=workspace_resource_id,
            azure_use_msi=True, **({"azure_client_id": client_id} if client_id else {}),
        )
    token = idempotency_token or _default_token(task_key, only_tasks)
    if len(token) > 64:
        raise ValueError("Databricks idempotency tokens must contain at most 64 characters")
    waiter = client.jobs.run_now(job_id=job_id, job_parameters=parameters, idempotency_token=token, **({"only": only_tasks} if only_tasks else {}))
    if wait_for == "running":
        run_id = getattr(waiter, "run_id", None) or getattr(getattr(waiter, "response", None), "run_id", None)
        if not run_id:
            raise ValueError("Databricks SDK did not return a run_id for streaming monitoring")
        run = _wait_for_running(client, run_id, task_key=task_key, timeout_seconds=timeout_seconds)
        result = {"run_id": run_id, "host": host, "idempotency_token": token, "task_key": task_key,
                  "wait_for": "running", "state": "RUNNING"}
        output = Path(output)
        write_json(output / "result.json", result)
        return result
    completed = waiter.result(timeout=timedelta(seconds=timeout_seconds))
    tasks = [task for task in (completed.tasks or []) if not _success(task)]
    if tasks:
        raise ValueError("Databricks run completed without all tasks succeeding")
    task = _task(completed, task_key)
    if not getattr(task, "run_id", None):
        raise ValueError(f"Completed job task {task_key!r} has no task run_id")
    result_text, parsed = _task_output(client, task)
    model_uri = result_text if result_text.startswith(("runs:/", "models:/")) else None
    if model_uri is None and isinstance(parsed, dict) and isinstance(parsed.get("model_uri"), str):
        model_uri = _immutable_model_uri(parsed["model_uri"])
    result = {"run_id": completed.run_id, "task_run_id": task.run_id, "host": host,
              "idempotency_token": token, "task_key": task_key, "notebook_output": result_text,
              "wait_for": "terminated"}
    if model_uri:
        result["model_uri"] = model_uri
    if parsed:
        result["receipt"] = parsed
        for key in ("endpoint", "version", "state"):
            if key in parsed:
                result[key] = parsed[key]
    output = Path(output)
    write_json(output / "result.json", result)
    if model_uri:
        (output / "model_uri.txt").write_text(model_uri + "\n", encoding="utf-8")
    return result


def run_job(host: str, workspace_resource_id: str, job_id: int, parameters: dict,
            output: Path, *, task_key: str = "train-evaluate", timeout_seconds: int = 3600,
            client_id: str | None = None, idempotency_token: str | None = None,
            wait_for: str = "terminated", only_tasks: list[str] | None = None) -> dict:
    _validate_host(host)
    if "/providers/Microsoft.Databricks/workspaces/" not in workspace_resource_id:
        raise ValueError("Provide the existing Azure Databricks workspace ARM resource ID")
    if job_id < 1 or timeout_seconds < 1:
        raise ValueError("job_id and timeout_seconds must be positive")
    if task_key == "train-evaluate" and not parameters.get("input_path", "").startswith(("wasbs://", "abfss://", "/Volumes/")):
        raise ValueError("Pass a Databricks-readable data URI, not an Azure ML mounted local path")
    return run_existing_job(host, workspace_resource_id, job_id, parameters, output, task_key=task_key,
                            timeout_seconds=timeout_seconds, client_id=client_id,
                            idempotency_token=idempotency_token, wait_for=wait_for, only_tasks=only_tasks)


def _load_parameters(args) -> dict:
    sources = [bool(args.job_parameters), bool(args.job_parameters_file)]
    if sum(sources) > 1:
        raise ValueError("Use only one of --job-parameters or --job-parameters-file")
    if args.job_parameters_file:
        parameters = load_json(args.job_parameters_file)
    elif args.job_parameters:
        parameters = json.loads(args.job_parameters)
        if not isinstance(parameters, dict):
            raise ValueError("--job-parameters must be a JSON object")
    else:
        missing = [name for name in ("scenario_path", "input_uri", "artifact_root", "experiment_path") if not getattr(args, name)]
        if missing:
            raise ValueError("legacy invocation requires --scenario-path --input-uri --artifact-root --experiment-path")
        parameters = {
            "scenario_path": args.scenario_path, "input_path": args.input_uri,
            "artifact_root": args.artifact_root, "experiment_path": args.experiment_path,
        }
    if args.model_uri_file:
        parameters["model_uri"] = _read_model_uri_file(args.model_uri_file)
    return parameters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("host", "workspace-resource-id", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--job-id", required=True, type=int)
    parser.add_argument("--task-key", default="train-evaluate")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--wait-for", choices=("running", "terminated"), default="terminated")
    parser.add_argument("--only-task", action="append", dest="only_tasks", help="Run only the named Databricks task; repeat for multiple tasks")
    parser.add_argument("--client-id")
    parser.add_argument("--idempotency-token")
    parser.add_argument("--job-parameters", help="JSON object of Databricks job parameters")
    parser.add_argument("--job-parameters-file", type=Path, help="JSON file of Databricks job parameters")
    parser.add_argument("--model-uri-file", type=Path, help="Read model_uri.txt from a previous step output and inject model_uri")
    for name in ("scenario-path", "input-uri", "artifact-root", "experiment-path"):
        parser.add_argument("--" + name)
    parser.add_argument("--model-context-file", type=Path, help="JSON file supplying factory/project/environment identity")
    args = parser.parse_args()
    try:
        parameters = _load_parameters(args)
        if args.model_context_file:
            from .tags import scope_tags
            parameters["model_context"] = json.dumps(scope_tags(load_json(args.model_context_file), require=True))
        run_job(args.host, args.workspace_resource_id, args.job_id, parameters,
            Path(args.output), task_key=args.task_key, timeout_seconds=args.timeout_seconds,
            client_id=args.client_id, idempotency_token=args.idempotency_token, wait_for=args.wait_for, only_tasks=args.only_tasks)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
