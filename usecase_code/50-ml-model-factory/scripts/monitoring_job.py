"""Render recurring Azure ML v2 monitoring; only `create --execute` contacts Azure.

DataOps must publish real monitoring JSON (window, reference_window, immutable
model_version) and the explicitly selected Parquet inputs before each recurrence.
The config URI is downloaded again, never replaced by the job's wall clock.
Updating a schedule or rerunning old files does not make their windows fresh.
Publish a consistent input set before changing the config; use a new schedule
revision for new immutable asset URIs. This is not an ingestion/labeling pipeline.

The source bundle contains only package Python, pyproject, this script, and
allowlisted scenario/runtime JSON. Compute uses its assigned managed identity,
not a developer's Azure CLI login. Assign its data-read/output-write permissions;
--publish additionally requires existing-model update and Blob write permission.
Set runtime.managed_identity_client_id for a user-assigned compute identity.
One publisher per model version is required; avoid overlapping publications.

render --runtime runtime.json --scenario scenario.json --config-uri URI
       --reference-uri URI --current-uri URI --output outputs/monitoring
       --interval-hours 24 [--time-zone UTC] [--start-time 2026-10-01T08:00:00]
       [--reference-outcomes-uri URI --predictions-uri URI --labels-uri URI]
       [--publish]
create --runtime runtime.json --schedule outputs/monitoring/schedule.yml [--execute]

Equivalent CLI v2 after review:
az ml schedule create --file <schedule.yml> --subscription <subscription>
    --resource-group <resource-group> --workspace-name <workspace>
No schedule is created by rendering. Without start-time, Azure runs the first
job when the schedule is created. Times/zones affect recurrence, not data windows.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit
from uuid import UUID

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_model_factory.config import load_json, validate_runtime, validate_scenario, write_json
from ml_model_factory.lake import LakeLayout
from ml_model_factory.tags import assert_scope, scope_tags


SCHEMAS = "https://azuremlschemas.azureedge.net/latest/"
AZURE_DEPENDENCIES = [
    "azure-ai-ml>=1.30,<2", "azure-identity>=1.25,<2", "azure-storage-blob>=12.25,<13",
]


def _safe_runtime(runtime: dict, scenario: dict, publish: bool) -> dict:
    validate_runtime(runtime)
    scope = scope_tags(runtime, require=True)
    result = {key: runtime[key] for key in (
        "subscription_id", "tenant_id", "resource_group", "workspace_name", "compute",
    )}
    result.update(aifactory=scope["aifactory"], project=scope["project"],
                  environment_name=scope["environment"], credential="managed_identity")
    if runtime.get("managed_identity_client_id"):
        result["managed_identity_client_id"] = str(UUID(runtime["managed_identity_client_id"]))
    if "lake" in runtime:
        layout = LakeLayout.from_config(runtime["lake"], scenario)
        if layout.use_case != scenario["name"]:
            raise ValueError("Monitoring lake use_case must match the selected scenario")
        lake = {key: getattr(layout, key) for key in (
            "project", "environment", "use_case", "dataset", "data_version", "snapshot_id",
            "run_id", "serving", "pipeline_id", "pipeline_version", "prefix",
        )}
        lake["aifactory"] = scope["aifactory"]
        if layout.model_version is not None:
            lake["model_version"] = layout.model_version
        lake["storage"] = {key: getattr(layout, key) for key in (
            "account_url", "container", "datastore",
        ) if getattr(layout, key) is not None}
        result["lake"] = lake
    if publish:
        lake = result.get("lake", {})
        if not lake.get("model_version"):
            raise ValueError("--publish requires an immutable runtime.lake.model_version")
        if not all(lake.get("storage", {}).get(key) for key in ("account_url", "container")):
            raise ValueError("--publish requires an existing lake Blob account_url and container")
    return result


def _safe_scenario(scenario: dict) -> dict:
    validate_scenario(scenario)
    result = {key: scenario[key] for key in (
        "name", "task", "model_name", "target", "features", "categorical_features",
    ) if key in scenario}
    result["dataset"] = {key: scenario["dataset"][key] for key in (
        "provider", "kind", "slug", "file", "version",
    ) if key in scenario["dataset"]}
    if "forecast" in scenario:
        result["forecast"] = {key: scenario["forecast"][key] for key in (
            "time_column", "frequency", "horizon", "series_columns",
        ) if key in scenario["forecast"]}
    return validate_scenario(result)


def _input_uri(value: str) -> dict:
    if (not isinstance(value, str) or not value or any(char.isspace() for char in value)
            or any(char in value for char in ("?", "#", "\\", "'", '"', "$", "`", ";"))):
        raise ValueError("Inputs require explicit credential-free Azure URIs, not local files or SAS")
    if re.fullmatch(r"azureml:[A-Za-z0-9_-]+:[A-Za-z0-9_.-]+", value):
        if value.rsplit(":", 1)[1].lower() in ("latest", "active", "production", "champion"):
            raise ValueError("Data assets require an explicit version, not an alias")
    else:
        url = urlsplit(value)
        if (url.scheme not in ("azureml", "https") or not url.netloc or not url.path
                or url.username or url.password or url.query or url.fragment or url.port
                or not re.fullmatch(r"[A-Za-z0-9_./=-]+", url.path)
                or any(part in (".", "..") for part in url.path.split("/"))):
            raise ValueError("Inputs require credential-free Azure ML data/datastore or Azure Blob URIs")
        if url.scheme == "https" and not re.fullmatch(
            r"[a-z0-9]{3,24}\.(blob|dfs)\.core\.(windows\.net|usgovcloudapi\.net|chinacloudapi\.cn)",
            url.hostname or "",
        ):
            raise ValueError("HTTPS inputs must identify an Azure Blob or ADLS endpoint")
        if url.scheme == "azureml" and url.netloc not in ("datastores", "subscriptions", "registries"):
            raise ValueError("Expected an Azure ML datastore or fully qualified data asset URI")
        if value.endswith("/"):
            raise ValueError("Monitoring inputs must identify individual files, not folders")
    return {"type": "uri_file", "path": value, "mode": "download"}


def _trigger(interval_hours: int, time_zone: str, start_time: str | None, end_time: str | None) -> dict:
    if isinstance(interval_hours, bool) or not isinstance(interval_hours, int) or interval_hours < 1:
        raise ValueError("interval_hours must be a positive integer")
    if (not isinstance(time_zone, str) or not time_zone.strip() or len(time_zone) > 100
            or any(ord(char) < 32 for char in time_zone)):
        raise ValueError("time_zone must be an Azure recurrence time-zone name, for example UTC")
    result = {"type": "recurrence", "frequency": "hour", "interval": interval_hours, "time_zone": time_zone}
    for key, value in (("start_time", start_time), ("end_time", end_time)):
        if value is not None:
            if not isinstance(value, str) or "T" not in value:
                raise ValueError(f"{key} must be an ISO date-time")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            result[key] = value
    if start_time and end_time:
        try:
            valid = datetime.fromisoformat(start_time.replace("Z", "+00:00")) < datetime.fromisoformat(
                end_time.replace("Z", "+00:00"))
        except TypeError as exc:
            raise ValueError("Schedule start/end times must use consistent offsets") from exc
        if not valid:
            raise ValueError("Schedule end_time must follow start_time")
    return result


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def render(
    runtime: dict, scenario: dict, output: Path, *, config_uri: str, reference_uri: str,
    current_uri: str, interval_hours: int = 24, reference_outcomes_uri: str | None = None,
    predictions_uri: str | None = None, labels_uri: str | None = None,
    evaluation_metrics_uri: str | None = None,
    time_zone: str = "UTC", start_time: str | None = None, end_time: str | None = None,
    name: str | None = None, publish: bool = False, source: Path = ROOT,
) -> dict:
    """Render portable definitions and a whitelist-only code bundle without SDK/network access."""
    if not isinstance(publish, bool):
        raise ValueError("publish must be an explicit boolean")
    scenario = _safe_scenario(scenario)
    runtime = _safe_runtime(runtime, scenario, publish)
    trigger = _trigger(interval_hours, time_zone, start_time, end_time)
    scope = scope_tags(runtime, require=True)
    if name is None:
        identity = "-".join([*scope.values(), scenario["name"], runtime.get("lake", {}).get("model_version", "report")])
        name = f"monitor-{identity[:45]}-{hashlib.sha256(identity.encode()).hexdigest()[:8]}"
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,127}", name):
        raise ValueError("Schedule name must be a safe identifier of at most 128 characters")
    if labels_uri is not None and (predictions_uri is None or reference_outcomes_uri is None):
        raise ValueError("Observed labels require explicit predictions and reference outcomes")
    inputs = {key: {"type": "uri_file", "path": f"./{key}.json", "mode": "download"}
              for key in ("scenario", "context")}
    inputs.update({key: _input_uri(value) for key, value in (
        ("config", config_uri), ("reference", reference_uri), ("current", current_uri),
        ("reference_outcomes", reference_outcomes_uri), ("predictions", predictions_uri),
        ("labels", labels_uri),
        ("evaluation_metrics", evaluation_metrics_uri),
    ) if value is not None})
    if not {"config", "reference", "current"}.issubset(inputs):
        raise ValueError("Explicit config, reference and current URIs are required")

    environment = {
        "image": "mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest",
        "conda_file": "./environments/monitoring.yml",
    }
    identity = {"type": "managed"}
    if runtime.get("managed_identity_client_id"):
        identity["client_id"] = runtime["managed_identity_client_id"]
    install = "python -m pip install --no-deps --no-build-isolation ."
    command = install + " && python -m ml_model_factory monitor " + " ".join(
        f'--{key.replace("_", "-")} "${{{{inputs.{key}}}}}"' for key in inputs
    ) + ' --output "${{outputs.report}}"'
    jobs = {"monitor": {
        "type": "command", "code": "./source", "environment": environment,
        "identity": identity,
        "inputs": {key: f"${{{{parent.inputs.{key}}}}}" for key in inputs},
        "outputs": {"report": "${{parent.outputs.report}}"}, "command": command,
    }}
    if publish:
        jobs["publish"] = {
            "type": "command", "code": "./source", "environment": environment,
            "identity": identity,
            "inputs": {"report": "${{parent.jobs.monitor.outputs.report}}",
                       "runtime": "${{parent.inputs.context}}"},
            "command": install + " && python -m ml_model_factory monitor-publish"
                       ' --report "${{inputs.report}}/report.json" --runtime "${{inputs.runtime}}" --execute',
        }
    tags = {**scope, "use_case": scenario["name"], "task_type": scenario["task"],
            "monitoring_publish": str(publish).lower()}
    if runtime.get("lake", {}).get("model_version"):
        tags["monitoring_model_version"] = runtime["lake"]["model_version"]
    compute = runtime["compute"]
    job = {
        "$schema": SCHEMAS + "pipelineJob.schema.json", "type": "pipeline",
        "display_name": name, "experiment_name": name, "tags": tags,
        "settings": {
            "default_compute": compute if compute.startswith("azureml:") else "azureml:" + compute,
            "force_rerun": True, "continue_on_step_failure": False,
        },
        "inputs": inputs, "outputs": {"report": {"type": "uri_folder", "mode": "upload"}}, "jobs": jobs,
    }
    schedule = {
        "$schema": SCHEMAS + "schedule.schema.json", "name": name,
        "description": "Observed-window monitoring; DataOps owns config/data freshness. No automatic retraining.",
        "tags": tags, "trigger": trigger, "create_job": "./job.yml",
    }
    source, output = Path(source).resolve(), Path(output).resolve()
    package = source / "ml_model_factory"
    code_files = [source / "pyproject.toml", source / "scripts" / "monitoring_job.py",
                  *sorted(package.glob("*.py"))]
    environment_path = source / "environments" / "monitoring.yml"
    for path in [*code_files, environment_path]:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError(f"Bundle source must be a regular project file: {path.name}")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Monitoring output must be a new empty directory; do not overwrite earlier definitions")
    output.mkdir(parents=True, exist_ok=True)
    for path in code_files:
        destination = output / "source" / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    conda = yaml.safe_load(environment_path.read_text(encoding="utf-8"))
    if publish:
        next(item["pip"] for item in conda["dependencies"] if isinstance(item, dict)).extend(AZURE_DEPENDENCIES)
    _write_yaml(output / "environments" / "monitoring.yml", conda)
    write_json(output / "scenario.json", scenario)
    write_json(output / "context.json", runtime)
    _write_yaml(output / "job.yml", job)
    _write_yaml(output / "schedule.yml", schedule)
    return {"job": str(output / "job.yml"), "schedule": str(output / "schedule.yml"),
            "source": str(output / "source"), "publish": publish, "cloud_created": False}


def load_monitoring_schedule(path: Path):
    """Load rendered YAML with public SDK v2 classes (1.35 has no public load_schedule)."""
    from azure.ai.ml import load_job
    from azure.ai.ml.entities import JobSchedule, RecurrenceTrigger

    path = Path(path).resolve()
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    trigger = dict(document["trigger"])
    if trigger.pop("type", None) != "recurrence":
        raise ValueError("Expected a recurrence monitoring schedule")
    job = load_job(path.parent / document["create_job"])
    if job.type != "pipeline":
        raise ValueError("Azure ML schedules require a pipeline job")
    return JobSchedule(name=document["name"], trigger=RecurrenceTrigger(**trigger), create_job=job,
                       description=document.get("description"), tags=document.get("tags"))


def create_schedule(path: Path, runtime: dict, *, execute: bool = False) -> dict:
    """Preview by default; --execute authorizes the recurring cloud job/compute costs."""
    if not isinstance(execute, bool):
        raise ValueError("execute must be an explicit boolean")
    validate_runtime(runtime)
    schedule = load_monitoring_schedule(path)
    assert_scope(schedule.tags, runtime)
    if not execute:
        return {"preview_only": True, "name": schedule.name, "cloud_created": False}
    from ml_model_factory.azureml import _client

    created = _client(runtime).schedules.begin_create_or_update(schedule).result()
    return {"name": created.name, "id": created.id, "cloud_created": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    rendering = commands.add_parser("render", help="Write local job/schedule definitions; never contact Azure")
    rendering.add_argument("--runtime", type=Path, required=True)
    rendering.add_argument("--scenario", type=Path, required=True)
    for key in ("config", "reference", "current"):
        rendering.add_argument(f"--{key}-uri", required=True)
    for key in ("reference-outcomes", "predictions", "labels", "evaluation-metrics"):
        rendering.add_argument(f"--{key}-uri")
    rendering.add_argument("--output", type=Path, required=True)
    rendering.add_argument("--interval-hours", type=int, default=24)
    rendering.add_argument("--time-zone", default="UTC", help="Azure recurrence zone, not a data-window override")
    rendering.add_argument("--start-time", help="ISO date-time; absent means the first run occurs at schedule creation")
    rendering.add_argument("--end-time")
    rendering.add_argument("--name")
    rendering.add_argument("--publish", action="store_true", help="Add explicit Blob/model-summary publication via compute MSI")
    creating = commands.add_parser("create", help="Preview or explicitly create a recurring Azure ML schedule")
    creating.add_argument("--runtime", type=Path, required=True)
    creating.add_argument("--schedule", type=Path, required=True)
    creating.add_argument("--execute", action="store_true", help="Create/update schedule and incur recurring compute charges")
    args = vars(parser.parse_args(argv))
    action = args.pop("action")
    try:
        runtime = load_json(args.pop("runtime"))
        if action == "render":
            result = render(runtime, load_json(args.pop("scenario")), **args)
        else:
            result = create_schedule(args.pop("schedule"), runtime, **args)
    except (ValueError, FileNotFoundError, ModuleNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
