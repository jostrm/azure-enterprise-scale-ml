"""Render, create and run multi-task Databricks jobs and Azure ML Databricks steps."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import shlex
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import yaml

from .config import load_json, write_json
from .layout import PACKAGE, source_root, write_bundle_metadata
from .storage_selection import validate_job_storage
from .tags import build_tags, scope_tags

PATTERNS = {"batch", "online", "streaming"}
TASK_KEYS = {"batch": "batch-score", "online": "register-serve", "streaming": "stream-score"}
NOTEBOOKS = {"batch": "batch_score", "online": "serve", "streaming": "stream_score"}
PLACEHOLDER = re.compile(r"<[^>]+>|\$\{(?!\{)[^}]+\}")
API_OMIT = {"unresolved"}


def _host(host: str) -> None:
    url = urlsplit(host)
    if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".azuredatabricks.net")
            or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
        raise ValueError("host must be an HTTPS Azure Databricks workspace URL without credentials")


_ARM = re.compile(r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Databricks/workspaces/[^/]+")
_TASK_KEY = re.compile(r"[A-Za-z0-9_-]{1,100}")


def _workspace_resource_id(value: str) -> None:
    if not isinstance(value, str) or not _ARM.fullmatch(value):
        raise ValueError("workspace_resource_id must be an Azure Databricks workspace ARM resource ID")


def _task_key(value: str) -> str:
    if not isinstance(value, str) or not _TASK_KEY.fullmatch(value):
        raise ValueError("Databricks task keys must match [A-Za-z0-9_-]{1,100}")
    return value


def _client_id(value: str | None) -> None:
    if value:
        UUID(value)


def _q(value) -> str:
    return shlex.quote(str(value))


def _unresolved(value, path=""):
    found = []
    if isinstance(value, str) and PLACEHOLDER.search(value):
        found.append(path or "$")
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_unresolved(item, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_unresolved(item, f"{path}[{index}]"))
    return found


def _reject_new_cluster(job):
    if isinstance(job, dict):
        if "new_cluster" in job:
            raise ValueError("Databricks job rendering refuses new_cluster definitions; use existing_cluster_id")
        for value in job.values():
            _reject_new_cluster(value)
    elif isinstance(job, list):
        for value in job:
            _reject_new_cluster(value)


def _setting(settings, pattern, key, default=""):
    section = (settings or {}).get(pattern, {})
    return str(section.get(key, default))


def render_job(scenario: dict, template: dict, pattern: str, *, settings: dict, scenario_path: str, orchestration: str = "databricks") -> dict:
    if pattern not in PATTERNS:
        raise ValueError(f"pattern must be one of {sorted(PATTERNS)}")
    if orchestration not in {"databricks", "azureml"}:
        raise ValueError("orchestration must be databricks or azureml")
    job = deepcopy(template)
    _reject_new_cluster(job)
    if not job.get("tasks"):
        raise ValueError("template must contain the train-evaluate task")
    train = job["tasks"][0]
    if train.get("task_key") != "train-evaluate" or "existing_cluster_id" not in train:
        raise ValueError("first template task must be train-evaluate on an existing cluster")
    params = {p["name"]: p.get("default", "") for p in job.get("parameters", [])}
    params["scenario_path"] = scenario_path
    if orchestration == "azureml":
        params.setdefault("model_uri", "")
    job["parameters"] = [{"name": k, "default": str(v)} for k, v in params.items()]
    train["notebook_task"].setdefault("base_parameters", {})["scenario_path"] = "{{job.parameters.scenario_path}}"
    task_key = TASK_KEYS[pattern]
    task = {
        "task_key": task_key,
        "existing_cluster_id": train["existing_cluster_id"],
        "depends_on": [{"task_key": "train-evaluate"}],
        "notebook_task": {
            "notebook_path": re.sub(r"/train$", f"/{NOTEBOOKS[pattern]}", train["notebook_task"]["notebook_path"]),
            "base_parameters": {
                "scenario_path": scenario_path,
                "model_uri": "{{job.parameters.model_uri}}" if orchestration == "azureml" else "{{tasks.train-evaluate.values.model_uri}}",
                "lake_config": "{{job.parameters.lake_config}}",
            },
        },
        "libraries": deepcopy(train.get("libraries", [])),
    }
    p = task["notebook_task"]["base_parameters"]
    if pattern == "batch":
        p.update(input_table=_setting(settings, "batch", "input_table", "<catalog>.<schema>.<input_table>"),
                 output_table=_setting(settings, "batch", "output_table", "<catalog>.<schema>.<predictions_table>"),
                 prediction_type=_setting(settings, "batch", "prediction_type", "double"),
                 env_manager=_setting(settings, "batch", "env_manager", "local"),
                 model_mode=_setting(settings, "batch", "model_mode", "custom"))
    elif pattern == "online":
        p.update(registered_model_name=_setting(settings, "online", "registered_model_name", "<catalog>.<schema>.<model>"),
                 endpoint_name=_setting(settings, "online", "endpoint_name", f"{scenario['name']}-endpoint"),
                 workload_size=_setting(settings, "online", "workload_size", "Small"),
                 scale_to_zero=_setting(settings, "online", "scale_to_zero", "true"),
                 model_context="{{job.parameters.model_context}}",
                 sample_request=_setting(settings, "online", "sample_request", ""))
    else:
        p.update(eventhubs_namespace=_setting(settings, "streaming", "eventhubs_namespace", "<eventhubs-namespace>"),
                 eventhub_name=_setting(settings, "streaming", "eventhub_name", "<eventhub-name>"),
                 secret_scope=_setting(settings, "streaming", "secret_scope", "<secret-scope>"),
                 connection_string_secret=_setting(settings, "streaming", "connection_string_secret", "<secret-name>"),
                 checkpoint=_setting(settings, "streaming", "checkpoint", ""),
                 checkpoint_root=_setting(settings, "streaming", "checkpoint_root", "<checkpoint-root>"),
                 output_table=_setting(settings, "streaming", "output_table", "<catalog>.<schema>.<stream_predictions>"),
                 payload_schema_json=_setting(settings, "streaming", "payload_schema_json", "<spark-schema-json>"),
                 prediction_type=_setting(settings, "streaming", "prediction_type", "double"),
                 trigger_interval=_setting(settings, "streaming", "trigger_interval", "30 seconds"),
                 env_manager=_setting(settings, "streaming", "env_manager", "local"),
                 model_mode=_setting(settings, "streaming", "model_mode", "custom"))
        task["timeout_seconds"] = 0
    job.setdefault("tasks", []).append(task)
    job.setdefault("tags", {})["inference_pattern"] = pattern
    job["tags"]["orchestration"] = orchestration
    unresolved = sorted(set(_unresolved(job)))
    if unresolved:
        job["unresolved"] = unresolved
    return job


def _client(host, auth, client=None, *, workspace_resource_id=None):
    _host(host)
    if auth not in {"azure-cli", "azure-msi"}:
        raise ValueError("auth must be azure-cli or azure-msi")
    if auth == "azure-msi" and not workspace_resource_id:
        raise ValueError("--workspace-resource-id is required for azure-msi authentication")
    if client is not None:
        return client
    from databricks.sdk import WorkspaceClient
    if auth == "azure-msi":
        return WorkspaceClient(host=host, auth_type="azure-msi", azure_use_msi=True,
                               azure_workspace_resource_id=workspace_resource_id)
    return WorkspaceClient(host=host, auth_type="azure-cli")


def _api_spec(spec: dict) -> dict:
    return {key: deepcopy(value) for key, value in spec.items() if key not in API_OMIT}


def create_job(spec: dict, *, host: str, auth: str = "azure-cli", execute: bool = False,
               client=None, workspace_resource_id: str | None = None) -> dict:
    _host(host)
    _reject_new_cluster(spec)
    unresolved = spec.get("unresolved") or _unresolved(spec)
    if unresolved:
        raise ValueError(f"Resolve Databricks job placeholders first: {unresolved}")
    body = _api_spec(spec)
    if not execute:
        return {"preview_only": True, "host": host, "auth": auth, "job": body.get("name"),
                "tasks": [t["task_key"] for t in body.get("tasks", [])]}
    c = _client(host, auth, client, workspace_resource_id=workspace_resource_id)
    result = c.api_client.do("POST", "/api/2.1/jobs/create", body=body)
    return {"preview_only": False, "job_id": result.get("job_id") if isinstance(result, dict) else getattr(result, "job_id")}


def _state_value(state, name):
    value = getattr(state, name, None)
    return getattr(value, "value", value)


def _task_state(task):
    state = getattr(task, "state", None)
    return _state_value(state, "life_cycle_state") or _state_value(state, "lifecycle_state"), _state_value(state, "result_state")


def _task(run, key):
    matches = [task for task in (getattr(run, "tasks", None) or []) if getattr(task, "task_key", None) == key]
    if len(matches) != 1:
        raise ValueError(f"Run must expose exactly one task named {key!r}")
    return matches[0]


def _success(task):
    lifecycle, result = _task_state(task)
    return result == "SUCCESS" or (result is None and lifecycle in (None, "TERMINATED"))


def _failures(run):
    failed = []
    for task in getattr(run, "tasks", None) or []:
        _, result = _task_state(task)
        if result not in (None, "SUCCESS"):
            failed.append(task)
    return failed


def _receipts(client, run):
    receipts = {}
    for task in getattr(run, "tasks", None) or []:
        if not getattr(task, "run_id", None):
            continue
        output = client.jobs.get_run_output(task.run_id)
        notebook = getattr(output, "notebook_output", None)
        receipts[task.task_key] = {"run_id": task.run_id, "notebook_output": getattr(notebook, "result", None),
                                   "truncated": getattr(notebook, "truncated", False)}
    return receipts


def _wait_running(client, run_id, *, train_task_key="train-evaluate", stream_task_key="stream-score", wait_seconds=600):
    deadline = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
    last = None
    while datetime.now(timezone.utc) < deadline:
        run = client.jobs.get_run(run_id)
        last = run
        try:
            train = _task(run, train_task_key)
            train_ready = _success(train)
        except ValueError:
            train_ready = True
        stream = _task(run, stream_task_key)
        lifecycle, result = _task_state(stream)
        if train_ready and lifecycle in {"RUNNING", "PENDING", "QUEUED"} and result is None:
            return run
        if _failures(run):
            raise ValueError("Databricks run failed before stream-score reached RUNNING")
        time.sleep(5)
    raise TimeoutError(f"Databricks stream-score did not reach RUNNING within {wait_seconds}s; last={last!r}")


def _read_receipt(path: Path | None):
    if not path or not Path(path).exists():
        return None
    return load_json(Path(path))


def _archive_receipt(path: Path):
    if path.exists():
        archive = path.with_name(path.name + "." + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + ".archive")
        path.replace(archive)


def _write_receipt(path: Path | None, value: dict) -> None:
    if path:
        write_json(Path(path), value)


def _receipt_token(receipt: Path | None, *, new_run: bool, job_id: int, only_tasks: list[str] | None) -> str:
    path = Path(receipt) if receipt else None
    current = _read_receipt(path)
    if current and current.get("status") != "succeeded":
        if new_run:
            _archive_receipt(path)
        elif current.get("idempotency_token"):
            return current["idempotency_token"]
        else:
            raise ValueError("Existing non-succeeded receipt has no reusable token; pass --new-run to archive it")
    material = json.dumps({"job_id": job_id, "only": only_tasks or [], "salt": uuid4().hex}, sort_keys=True)
    return "cli-" + __import__("hashlib").sha256(material.encode("utf-8")).hexdigest()[:60]


def run_job(job_id: int, *, host: str, auth: str = "azure-cli", parameters: dict | None = None,
            execute: bool = False, wait_seconds: int = 600, client=None, wait_for: str = "terminated",
            workspace_resource_id: str | None = None, only_tasks: list[str] | None = None,
            receipt: Path | None = None, new_run: bool = False) -> dict:
    _host(host)
    if wait_for not in {"running", "terminated"}:
        raise ValueError("wait_for must be running or terminated")
    if job_id < 1 or wait_seconds < 1:
        raise ValueError("job_id and wait_seconds must be positive")
    if not execute:
        return {"preview_only": True, "host": host, "auth": auth, "job_id": job_id,
                "parameters": parameters or {}, "wait_for": wait_for, "only_tasks": only_tasks or []}
    c = _client(host, auth, client, workspace_resource_id=workspace_resource_id)
    token = _receipt_token(receipt, new_run=new_run, job_id=job_id, only_tasks=only_tasks)
    _write_receipt(receipt, {"status": "intent", "job_id": job_id, "idempotency_token": token, "only_tasks": only_tasks or []})
    waiter = c.jobs.run_now(job_id=job_id, job_parameters=parameters or {}, idempotency_token=token, **({"only": only_tasks} if only_tasks else {}))
    run_id = getattr(waiter, "run_id", None) or getattr(getattr(waiter, "response", None), "run_id", None)
    if run_id:
        _write_receipt(receipt, {"status": "submitted", "job_id": job_id, "run_id": run_id, "idempotency_token": token, "only_tasks": only_tasks or []})
    try:
        if wait_for == "running":
            if not run_id:
                raise ValueError("Databricks SDK did not return a run_id for streaming monitoring")
            run = _wait_running(c, run_id, wait_seconds=wait_seconds)
            result = {"preview_only": False, "run_id": run_id, "state": "RUNNING", "tasks": _receipts(c, run)}
            _write_receipt(receipt, {"status": "running", "run_id": run_id, "idempotency_token": token, "only_tasks": only_tasks or []})
            return result
        completed = waiter.result(timeout=timedelta(seconds=wait_seconds))
    except TimeoutError as exc:
        _write_receipt(receipt, {"status": "timed_out", "job_id": job_id, "run_id": run_id, "idempotency_token": token, "only_tasks": only_tasks or []})
        raise TimeoutError(f"Databricks run timed out; run_id={run_id}") from exc
    if _failures(completed) or any(not _success(task) for task in getattr(completed, "tasks", None) or []):
        _write_receipt(receipt, {"status": "failed", "run_id": completed.run_id, "idempotency_token": token, "only_tasks": only_tasks or []})
        raise ValueError("Databricks run completed without all tasks succeeding")
    result = {"preview_only": False, "run_id": completed.run_id, "tasks": _receipts(c, completed)}
    _write_receipt(receipt, {"status": "succeeded", "run_id": completed.run_id, "idempotency_token": token, "only_tasks": only_tasks or []})
    return result


def _copy_bundle(source: Path, output: Path):
    code = output / "code"
    pkg = code / "ml_model_factory"
    pkg.mkdir(parents=True, exist_ok=True)
    for path in (source / PACKAGE).glob("*.py"):
        shutil.copyfile(path, pkg / path.name)
    write_bundle_metadata(source, code / "pyproject.toml")
    env = output / "environments"
    env.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / "accelerator" / "environments" / "azureml-databricks.yml", env / "azureml-databricks.yml")
    return code


def _write_params(code: Path, name: str, value: dict) -> str:
    path = code / "params" / f"{name}.json"
    write_json(path, value)
    return f"params/{name}.json"


def _environment(databricks: dict):
    if "environment" in databricks:
        env = databricks["environment"]
        if isinstance(env, str):
            if not env.startswith("azureml:"):
                raise ValueError("databricks.environment string must be a pinned azureml:<name>:<version> asset")
            return env
        if isinstance(env, dict):
            return deepcopy(env)
        raise ValueError("databricks.environment must be a pinned Azure ML asset string or environment object")
    return {"image": "mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest",
            "conda_file": "./environments/azureml-databricks.yml"}


def render_databricks_pipeline(scenario: dict, runtime: dict, output: Path, *, pattern: str,
                               databricks: dict, source: Path | None = None) -> dict:
    if pattern not in PATTERNS:
        raise ValueError(f"pattern must be one of {sorted(PATTERNS)}")
    required = {"host", "workspace_resource_id", "job_id"}
    missing = required - set(databricks)
    if missing:
        raise ValueError(f"databricks config missing {sorted(missing)}")
    _host(databricks["host"])
    _workspace_resource_id(databricks["workspace_resource_id"])
    _client_id(databricks.get("client_id"))
    source = source_root(source)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Databricks pipeline output directory must be empty")
    code = _copy_bundle(source, output)
    timeout = int(databricks.get("timeout_seconds", 3600))
    if timeout < 1:
        raise ValueError("timeout_seconds must be positive")
    env = _environment(databricks)
    require_scope = bool(scope_tags(runtime))
    tags = build_tags(scenario, runtime, engine="databricks", require_scope=require_scope)
    train_params = deepcopy(databricks.get("train_parameters", {}))
    pattern_params = deepcopy(databricks.get(f"{pattern}_parameters", {}))
    train_file = _write_params(code, "train", train_params)
    pattern_file = _write_params(code, pattern, pattern_params)
    base = ["python -m ml_model_factory.databricks_job", "--host", _q(databricks["host"]),
            "--workspace-resource-id", _q(databricks["workspace_resource_id"]), "--job-id", _q(int(databricks["job_id"])),
            "--timeout-seconds", _q(timeout)]
    if databricks.get("client_id"):
        base.extend(["--client-id", _q(databricks["client_id"])])
    identity = {"type": "managed"}
    if databricks.get("client_id"):
        identity["client_id"] = databricks["client_id"]

    def step(command, *, with_input=False):
        component = {"type": "command", "code": "./code", "environment": env, "is_deterministic": False,
                     "command": command, "outputs": {"result": {"type": "uri_folder"}}}
        job_step = {"type": "command", "component": component, "identity": identity,
                    "limits": {"timeout": timeout + 600}, "outputs": {"result": {"type": "uri_folder"}}}
        if with_input:
            component["inputs"] = {"train_result": {"type": "uri_folder"}}
            job_step["inputs"] = {"train_result": "${{parent.jobs.train.outputs.result}}"}
        return job_step

    train_task_key = _task_key(databricks.get("train_task_key", "train-evaluate"))
    pattern_task_key = _task_key(databricks.get("task_key", TASK_KEYS[pattern]))
    train_cmd = " ".join([*base, "--task-key", _q(train_task_key), "--only-task", _q(train_task_key),
                          "--output", _q("${{outputs.result}}"), "--job-parameters-file", _q(train_file)])
    wait_for = "running" if pattern == "streaming" else "terminated"
    pattern_cmd = " ".join([*base, "--task-key", _q(pattern_task_key), "--only-task", _q(pattern_task_key),
                            "--wait-for", _q(wait_for), "--output", _q("${{outputs.result}}"),
                            "--job-parameters-file", _q(pattern_file),
                            "--model-uri-file", _q("${{inputs.train_result}}/model_uri.txt")])
    job = {
        "$schema": "https://azuremlschemas.azureedge.net/latest/pipelineJob.schema.json",
        "type": "pipeline", "display_name": f"{scenario['name']}-databricks-{pattern}",
        "tags": tags,
        "jobs": {"train": step(train_cmd), pattern: step(pattern_cmd, with_input=True)},
        "settings": {"default_compute": "azureml:" + runtime.get("compute", "cpu"), "force_rerun": True},
    }
    validate_job_storage(job, runtime)
    unresolved = sorted(set(_unresolved({"job": job, "databricks": databricks, "params": {"train": train_params, pattern: pattern_params}})))
    manifest = {"schema": "ml-model-factory-databricks-pipeline/v1", "pattern": pattern,
                "limitations": ["MSI needs Databricks job-run permission", "Databricks job must already exist",
                                "Model remains in Databricks MLflow/UC registry"],
                "unresolved": unresolved}
    write_json(output / "manifest.json", manifest)
    (output / "pipeline.yml").write_text(yaml.safe_dump(job, sort_keys=False), encoding="utf-8")
    return {"pipeline": str(output / "pipeline.yml"), "manifest": str(output / "manifest.json"), "unresolved": unresolved}


def _render(args):
    spec = render_job(load_json(args.scenario), load_json(args.template), args.pattern,
                      settings=load_json(args.settings), scenario_path=args.scenario_path, orchestration=args.orchestration)
    write_json(args.output, spec)
    return {"job": str(args.output), "unresolved": spec.get("unresolved", [])}


def _create(args):
    return create_job(load_json(args.job), host=args.host, auth=args.auth, execute=args.execute,
                      workspace_resource_id=args.workspace_resource_id)


def _run(args):
    return run_job(args.job_id, host=args.host, auth=args.auth,
                   parameters=load_json(args.parameters) if args.parameters else None,
                   execute=args.execute, wait_seconds=args.wait_seconds, wait_for=args.wait_for,
                   workspace_resource_id=args.workspace_resource_id, only_tasks=args.only_tasks,
                   receipt=args.receipt, new_run=args.new_run)


def _pipeline(args):
    return render_databricks_pipeline(load_json(args.scenario), load_json(args.runtime), args.output,
                                      pattern=args.pattern, databricks=load_json(args.databricks), source=args.source)


def _add_render_parser(parent, name="render"):
    render = parent.add_parser(name, help="Render a Databricks multi-task job")
    render.add_argument("--scenario", required=True, type=Path); render.add_argument("--pattern", required=True, choices=sorted(PATTERNS))
    render.add_argument("--template", required=True, type=Path); render.add_argument("--settings", required=True, type=Path)
    render.add_argument("--scenario-path", required=True); render.add_argument("--output", required=True, type=Path)
    render.add_argument("--orchestration", choices=("databricks", "azureml"), default="databricks")
    render.set_defaults(handler=_render)
    return render


def _add_create_parser(parent, name="create"):
    create = parent.add_parser(name, help="Create a rendered Databricks job (preview by default)")
    create.add_argument("--job", required=True, type=Path); create.add_argument("--host", required=True)
    create.add_argument("--auth", choices=("azure-cli", "azure-msi"), default="azure-cli")
    create.add_argument("--workspace-resource-id")
    create.add_argument("--execute", action="store_true")
    create.set_defaults(handler=_create)
    return create


def _add_run_parser(parent, name="run"):
    run = parent.add_parser(name, help="Run a Databricks job (preview by default)")
    run.add_argument("--job-id", required=True, type=int); run.add_argument("--host", required=True)
    run.add_argument("--auth", choices=("azure-cli", "azure-msi"), default="azure-cli"); run.add_argument("--parameters", type=Path)
    run.add_argument("--workspace-resource-id")
    run.add_argument("--wait-for", choices=("running", "terminated"), default="terminated")
    run.add_argument("--only-task", action="append", dest="only_tasks", help="Run only the named Databricks task; repeat for multiple tasks")
    run.add_argument("--wait-seconds", type=int, default=600); run.add_argument("--receipt", type=Path)
    run.add_argument("--new-run", action="store_true"); run.add_argument("--execute", action="store_true")
    run.set_defaults(handler=_run)
    return run


def _add_pipeline_render_parser(parent, name="render"):
    pipe = parent.add_parser(name, help="Render Azure ML pipeline with Databricks job steps")
    pipe.add_argument("--scenario", required=True, type=Path); pipe.add_argument("--runtime", required=True, type=Path)
    pipe.add_argument("--pattern", required=True, choices=sorted(PATTERNS)); pipe.add_argument("--databricks", required=True, type=Path)
    pipe.add_argument("--output", required=True, type=Path); pipe.add_argument("--source", type=Path)
    pipe.set_defaults(handler=_pipeline)
    return pipe


def add_commands(commands) -> None:
    job = commands.add_parser("databricks-job", help="Render/create/run Databricks jobs")
    job_sub = job.add_subparsers(dest="databricks_job_command", required=True)
    _add_render_parser(job_sub); _add_create_parser(job_sub); _add_run_parser(job_sub)
    pipe = commands.add_parser("databricks-pipeline", help="Render Azure ML Databricks-step pipelines")
    pipe_sub = pipe.add_subparsers(dest="databricks_pipeline_command", required=True)
    _add_pipeline_render_parser(pipe_sub)
