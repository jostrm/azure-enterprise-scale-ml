"""Azure ML scheduled micro-batch streaming jobs; rendering never contacts Azure."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

from .azureml import SCHEMAS, _asset, _client, _name, _write_yaml
from .config import load_json, validate_runtime, validate_scenario, write_json
from .lake import LakeLayout
from .layout import PACKAGE, source_root, write_bundle_metadata
from .storage_selection import resolve_storage_selection, selected_profile, validate_job_storage, verify_datastore
from .tags import assert_scope, build_tags, scope_tags

STREAMING_DEPS = ["azure-eventhub>=5.11,<6", "azure-identity>=1.25,<2"]


def _immutable_model(value: str) -> str:
    """Normalize an immutable registered model (azureml:name:version or ARM ID) to azureml:name:version."""
    from .serving import _model_name_version

    if not isinstance(value, str):
        raise ValueError("model_id must be an immutable azureml:name:version reference")
    try:
        name, version = _model_name_version(value.removeprefix("azureml:") if value.startswith("azureml:/") else value)
    except ValueError as exc:
        raise ValueError("model_id must be an immutable azureml:name:version reference or model ARM ID") from exc
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or not re.fullmatch(r"[A-Za-z0-9_.-]+", version)
            or version.lower() in {"latest", "active", "champion", "production"}):
        raise ValueError("model_id must pin an immutable version, not an alias")
    return f"azureml:{name}:{version}"


def _eventhubs(runtime: dict) -> dict:
    settings = (runtime.get("streaming") or {}).get("eventhubs") or {}
    required = {"namespace", "eventhub", "consumer_group"}
    if set(settings) - required or not required.issubset(settings):
        raise ValueError("runtime.streaming.eventhubs must contain namespace, eventhub and consumer_group only")
    namespace = settings["namespace"]
    if (not re.fullmatch(r"[a-z0-9-]{6,50}\.servicebus\.windows\.net", namespace)
            or any(token in namespace for token in ("Endpoint=", "SharedAccessKey", "?", ";"))):
        raise ValueError("Event Hubs namespace must be a credential-free FQDN like name.servicebus.windows.net")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,256}", settings["eventhub"]):
        raise ValueError("Event Hubs name is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._$-]{1,128}", settings["consumer_group"]):
        raise ValueError("Event Hubs consumer group is invalid")
    return settings


def _trigger(interval_minutes: int, start_time: str | None, time_zone: str) -> dict:
    if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int) or interval_minutes < 1:
        raise ValueError("interval_minutes must be a positive integer")
    if not isinstance(time_zone, str) or not time_zone.strip():
        raise ValueError("time_zone is required")
    frequency, interval = ("hour", interval_minutes // 60) if interval_minutes % 60 == 0 else ("minute", interval_minutes)
    result = {"type": "recurrence", "frequency": frequency, "interval": interval, "time_zone": time_zone}
    if start_time is not None:
        datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        result["start_time"] = start_time
    return result


def _copy_bundle(source: Path, output: Path) -> Path:
    package = source / PACKAGE
    code = output / "code"
    for module in sorted(package.rglob("*.py")):
        if "__pycache__" in module.relative_to(package).parts:
            continue
        destination = code / "ml_model_factory" / module.relative_to(package)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module, destination)
    write_bundle_metadata(source, code / "pyproject.toml")
    return code


def _conda(source: Path, output: Path, scenario: dict, runtime: dict, mode: str) -> tuple[Any, str | None]:
    task = scenario["task"]
    pinned = runtime.get("streaming_environment")
    if pinned is not None:
        if not isinstance(pinned, str) or not re.fullmatch(r"azureml:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+", pinned):
            raise ValueError("runtime.streaming_environment must be a pinned azureml:<name>:<version> environment")
        return pinned, None
    if mode == "automl" and task.startswith("image_"):
        raise ValueError("AutoML image streaming needs runtime.streaming_environment pinned to an environment with "
                         "the AutoML image runtime plus azure-eventhub and azure-identity")
    base = "azureml-automl.yml" if mode == "automl" else "azureml-vision.yml" if task.startswith("image_") else "azureml-custom.yml"
    document = yaml.safe_load((source / "accelerator" / "environments" / base).read_text(encoding="utf-8"))
    document["name"] = document.get("name", "model-factory") + "-streaming"
    pip = next(item["pip"] for item in document["dependencies"] if isinstance(item, dict) and "pip" in item)
    for dep in STREAMING_DEPS:
        if dep not in pip:
            pip.append(dep)
    filename = "azureml-streaming-" + ("automl" if mode == "automl" else "vision" if task.startswith("image_") else "custom") + ".yml"
    path = output / "environments" / filename
    _write_yaml(path, document)
    return {"image": "mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest", "conda_file": f"./environments/{filename}"}, filename


def _lake_bindings(scenario: dict, runtime: dict, model_version: str) -> dict:
    lake = runtime.get("lake")
    if not lake:
        raise ValueError("Scheduled stream jobs require runtime.lake with a stable checkpoint binding")
    config = copy.deepcopy(lake)
    config["serving"] = "streaming"
    config["model_version"] = model_version
    layout = LakeLayout.from_config(config, scenario)
    if layout.use_case != scenario["name"]:
        raise ValueError("lake.use_case must match scenario.name")
    datastore = runtime.get("datastore") or layout.datastore
    if not datastore:
        raise ValueError("Scheduled stream jobs require an Azure ML datastore for lake checkpoints")
    return {
        "config": {key: getattr(layout, key) for key in (
            "project", "environment", "use_case", "dataset", "data_version", "snapshot_id", "run_id",
            "serving", "model_version", "pipeline_id", "pipeline_version", "prefix")},
        "checkpoint": layout.azureml_uri("checkpoint", datastore=datastore),
        "predictions": layout.azureml_uri("output", datastore=datastore),
        "layout": layout,
    }


def render_stream_job(scenario: dict, runtime: dict, output: Path, *, model_id: str, mode: str,
                      interval_minutes: int = 15, max_batches: int | None = 1, max_events: int = 1000,
                      timeout_seconds: int = 300, read_timeout_seconds: int = 30, initial_position: str = "latest",
                      name: str | None = None, source: Path | None = None, start_time: str | None = None,
                      time_zone: str = "UTC") -> dict[str, str]:
    scenario = validate_scenario(scenario)
    runtime = validate_runtime(resolve_storage_selection(runtime))
    if mode not in {"custom", "automl"}:
        raise ValueError("mode must be custom or automl")
    if initial_position not in {"latest", "earliest"}:
        raise ValueError("initial_position must be latest or earliest")
    model_id = _immutable_model(model_id)
    if isinstance(timeout_seconds, bool) or int(timeout_seconds) < 1:
        raise ValueError("timeout_seconds must be positive")
    if isinstance(read_timeout_seconds, bool) or int(read_timeout_seconds) < 1:
        raise ValueError("read_timeout_seconds must be positive")
    job_timeout = int(timeout_seconds) + 60
    if interval_minutes * 60 <= job_timeout:
        raise ValueError("recurrence interval must exceed the job timeout to avoid overlapping consumers")
    eventhubs = _eventhubs(runtime)
    model_version = model_id.rsplit(":", 1)[1]
    lake = _lake_bindings(scenario, runtime, model_version)
    trigger = _trigger(interval_minutes, start_time, time_zone)
    scope = scope_tags(runtime, require=True)
    tags = {**build_tags(scenario, runtime, mode=mode, engine="azureml"), "factory_streaming": "scheduled-microbatch"}
    identity = {"type": "managed"}
    if runtime.get("managed_identity_client_id"):
        identity["client_id"] = str(UUID(runtime["managed_identity_client_id"]))
        runtime["managed_identity_client_id"] = identity["client_id"]
    source, output = source_root(source), Path(output).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Stream job output must be a new empty directory")
    output.mkdir(parents=True, exist_ok=True)
    _copy_bundle(source, output)
    write_json(output / "code" / "scenario.json", scenario)
    environment, env_file = _conda(source, output, scenario, runtime, mode)
    safe_runtime = {key: runtime[key] for key in (
        "subscription_id", "tenant_id", "resource_group", "workspace_name", "compute", "datastore",
        "managed_identity_client_id", "aifactory", "project", "environment_name", "use_common_datalake_storage",
        "storage_targets", "storage", "common_resource_group") if key in runtime}
    safe_runtime["streaming"] = {"eventhubs": eventhubs}
    safe_runtime["credential"] = "managed_identity"
    safe_runtime["lake"] = {**lake["config"], "storage": {k: getattr(lake["layout"], k) for k in ("account_url", "container", "datastore") if getattr(lake["layout"], k)}}
    write_json(output / "runtime.json", safe_runtime)
    if name is None:
        seed = "-".join([scope["aifactory"], scope["project"], scope["environment"], scenario["name"], model_version])
        name = f"stream-{_name(seed, 50)}-{hashlib.sha256(seed.encode()).hexdigest()[:8]}"
    args = [
        "python", "-m", "ml_model_factory", "stream-score", "--scenario", "scenario.json",
        "--source", "eventhubs", "--namespace", eventhubs["namespace"], "--eventhub", eventhubs["eventhub"],
        "--consumer-group", eventhubs["consumer_group"], "--credential", "managed_identity",
        "--model-version", model_version, "--mode", mode, "--model", "${{inputs.model}}",
        "--checkpoint", "${{outputs.checkpoint}}/checkpoint.json", "--output", "${{outputs.predictions}}",
        "--max-events", str(int(max_events)), "--timeout-seconds", str(float(read_timeout_seconds)),
        "--initial-position", initial_position,
    ]
    if max_batches is not None:
        args += ["--max-batches", str(int(max_batches))]
    if runtime.get("managed_identity_client_id"):
        args += ["--client-id", runtime["managed_identity_client_id"]]
    command = "python -m pip install --no-deps --no-build-isolation . && " + " ".join(shlex.quote(str(arg)) for arg in args)
    job = {
        "$schema": SCHEMAS + "pipelineJob.schema.json", "type": "pipeline",
        "display_name": name, "experiment_name": name, "tags": tags,
        "settings": {"default_compute": _asset(runtime["compute"]), "force_rerun": True, "continue_on_step_failure": False},
        "inputs": {"model": {"type": "mlflow_model", "path": model_id, "mode": "download"}},
        "outputs": {
            "checkpoint": {"type": "uri_folder", "path": lake["checkpoint"], "mode": "rw_mount"},
            "predictions": {"type": "uri_folder", "path": lake["predictions"], "mode": "rw_mount"},
        },
        "jobs": {"stream_score": {"type": "command", "code": "./code", "environment": environment,
                                    "identity": identity, "limits": {"timeout": job_timeout}, "inputs": {"model": "${{parent.inputs.model}}"},
                                    "outputs": {"checkpoint": "${{parent.outputs.checkpoint}}",
                                                "predictions": "${{parent.outputs.predictions}}"},
                                    "command": command}},
    }
    if runtime.get("datastore"):
        job["settings"]["default_datastore"] = _asset(runtime["datastore"])
    schedule = {"$schema": SCHEMAS + "schedule.schema.json", "name": name,
                "description": "Scheduled Event Hubs micro-batch scoring; minutes latency, not continuous streaming.",
                "tags": tags, "trigger": trigger, "create_job": "./job.yml"}
    manifest = {
        "schema": "ml-model-factory-stream-job/v1", "scenario": scenario["name"], "mode": mode,
        "model_id": model_id, "eventhubs": eventhubs, "files": {},
        "limitations": [
            f"Micro-batch latency is at least the {interval_minutes} minute schedule interval; this is not continuous streaming.",
            "Use one active consumer per checkpoint and consumer group; recurrence interval must exceed job timeout.",
            "The compute/job managed identity needs Event Hubs Data Receiver and storage read/write RBAC.",
            "Blobfuse mount rename semantics are not a storage transaction; use a stable HNS/blob backend and monitor receipts.",
            "With initial_position=latest, the first run anchors each partition to its current last sequence; later runs resume without gaps.",
            "Event Hubs retention must exceed the longest outage you expect to recover from.",
        ],
    }
    files = {"job": str(output / "job.yml"), "schedule": str(output / "schedule.yml"),
             "manifest": str(output / "manifest.json"), "runtime": str(output / "runtime.json"),
             "scenario": str(output / "code" / "scenario.json")}
    if env_file:
        files["environment"] = str(output / "environments" / env_file)
    manifest["files"] = files
    _write_yaml(output / "job.yml", job)
    _write_yaml(output / "schedule.yml", schedule)
    write_json(output / "manifest.json", manifest)
    validate_job_storage(job, runtime)
    return files


def _load_schedule(path: Path):
    from azure.ai.ml import load_job
    from azure.ai.ml.entities import JobSchedule, RecurrenceTrigger
    path = Path(path).resolve()
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    trigger = dict(doc["trigger"])
    if trigger.pop("type", None) != "recurrence":
        raise ValueError("Expected a recurrence stream schedule")
    job = load_job(path.parent / doc["create_job"])
    if job.type != "pipeline":
        raise ValueError("Stream schedules require a pipeline job")
    return JobSchedule(name=doc["name"], trigger=RecurrenceTrigger(**trigger), create_job=job,
                       description=doc.get("description"), tags=doc.get("tags"))


def create_stream_schedule(path: Path, runtime: dict, *, execute: bool = False, client=None) -> dict:
    if not isinstance(execute, bool):
        raise ValueError("execute must be boolean")
    runtime = validate_runtime(runtime)
    schedule = _load_schedule(path)
    assert_scope(schedule.tags, runtime)
    declaration = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    job_doc = yaml.safe_load((Path(path).parent / declaration["create_job"]).read_text(encoding="utf-8"))
    validate_job_storage(job_doc, runtime)
    if not execute:
        return {"preview_only": True, "name": schedule.name, "cloud_created": False}
    client = client or _client(runtime)
    storage = selected_profile(runtime)
    if storage is not None:
        verify_datastore(storage, client.datastores.get(storage["datastore"]))
    created = client.schedules.begin_create_or_update(schedule).result()
    return {"name": created.name, "id": created.id, "cloud_created": True}


def submit_stream_job(path: Path, runtime: dict, *, execute: bool = False, client=None) -> dict:
    if not isinstance(execute, bool):
        raise ValueError("execute must be boolean")
    from azure.ai.ml import load_job
    runtime = validate_runtime(runtime)
    job_doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_job_storage(job_doc, runtime)
    job = load_job(path)
    assert_scope(job.tags or {}, runtime)
    if not execute:
        return {"preview_only": True, "name": getattr(job, "name", None) or job_doc.get("display_name"), "cloud_created": False}
    client = client or _client(runtime)
    storage = selected_profile(runtime)
    if storage is not None:
        verify_datastore(storage, client.datastores.get(storage["datastore"]))
    submitted = client.jobs.create_or_update(job)
    return {"name": submitted.name, "id": submitted.id, "cloud_created": True}


def _render_command(args):
    return render_stream_job(load_json(args.scenario), load_json(args.runtime), args.output, model_id=args.model_id,
                             mode=args.mode, interval_minutes=args.interval_minutes, max_batches=args.max_batches,
                             max_events=args.max_events, timeout_seconds=args.timeout_seconds, read_timeout_seconds=args.read_timeout_seconds,
                             initial_position=args.initial_position)


def _schedule_command(args):
    return create_stream_schedule(args.schedule, load_json(args.runtime), execute=args.execute)


def _submit_command(args):
    return submit_stream_job(args.job, load_json(args.runtime), execute=args.execute)


def add_commands(commands) -> None:
    root = commands.add_parser("stream-job", help="Render, preview, submit or schedule AML stream micro-batch jobs")
    actions = root.add_subparsers(dest="stream_job_action", required=True)
    render = actions.add_parser("render", help="Render offline Azure ML job and schedule YAML")
    render.add_argument("--scenario", required=True, type=Path)
    render.add_argument("--runtime", required=True, type=Path)
    render.add_argument("--model-id", required=True)
    render.add_argument("--mode", required=True, choices=("custom", "automl"))
    render.add_argument("--output", required=True, type=Path)
    render.add_argument("--interval-minutes", type=int, default=15)
    render.add_argument("--max-batches", type=int, default=1)
    render.add_argument("--max-events", type=int, default=1000)
    render.add_argument("--timeout-seconds", type=int, default=300)
    render.add_argument("--read-timeout-seconds", type=int, default=30)
    render.add_argument("--initial-position", choices=("latest", "earliest"), default="latest")
    render.set_defaults(handler=_render_command)
    schedule = actions.add_parser("schedule", help="Preview or create a rendered Azure ML schedule")
    schedule.add_argument("--runtime", required=True, type=Path)
    schedule.add_argument("--schedule", required=True, type=Path)
    schedule.add_argument("--execute", action="store_true")
    schedule.set_defaults(handler=_schedule_command)
    submit = actions.add_parser("submit", help="Preview or submit one bounded stream job")
    submit.add_argument("--runtime", required=True, type=Path)
    submit.add_argument("--job", required=True, type=Path)
    submit.add_argument("--execute", action="store_true")
    submit.set_defaults(handler=_submit_command)
