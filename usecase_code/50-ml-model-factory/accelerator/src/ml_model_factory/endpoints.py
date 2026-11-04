"""Render, deploy, invoke and delete Azure ML online/batch serving definitions explicitly."""

from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from . import serving
from .azureml import SCHEMAS, _asset, _client, _environment, _job_identity, _name, _write_yaml
from .config import load_json, validate_scenario, write_json
from .layout import PACKAGE, source_root, write_bundle_metadata
from .storage_selection import resolve_storage_selection, validate_job_storage
from .tags import assert_scope, build_tags, scope_tags, serving_resource_tags

AUTOML_IMAGE_SCHEMA = "https://learn.microsoft.com/en-us/azure/machine-learning/reference-automl-images-schema?view=azureml-api-2"
INFERENCE_SERVER_DOC = "https://learn.microsoft.com/en-us/azure/machine-learning/how-to-inference-server-http?view=azureml-api-2"


def _task_group(task: str) -> str:
    return "vision" if task.startswith("image_") else task


def _validate_serving(runtime: dict) -> dict:
    settings = runtime.get("serving", {})
    if not isinstance(settings, dict):
        raise ValueError("runtime.serving must be a JSON object")
    for key in ("instance_count", "batch_instance_count"):
        value = settings.get(key, 1)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"runtime.serving.{key} must be a positive integer")
    for key in ("public_network_access", "egress_public_network_access"):
        if key in settings and settings[key] not in ("enabled", "disabled"):
            raise ValueError(f"runtime.serving.{key} must be enabled or disabled")
    return settings


def _endpoint_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]{1,30}[a-zA-Z0-9]", value):
        raise ValueError("endpoint_name must be 3-32 letters, digits or hyphens, starting with a letter")
    return value


def _no_code_online(task: str, mode: str) -> bool:
    return task in {"classification", "regression"} or task.startswith("image_")


def _no_code_batch(task: str) -> bool:
    return task in {"classification", "regression"}


def _route(kind: str, task: str, mode: str, scoring: str) -> str:
    if scoring not in {"auto", "mlflow", "custom"}:
        raise ValueError("scoring must be auto, mlflow, or custom")
    if scoring != "auto":
        return scoring
    if kind == "online":
        return "mlflow" if _no_code_online(task, mode) else "custom"
    return "mlflow" if _no_code_batch(task) else "custom"


def _copy_code(source: Path, output: Path, scenario: dict, serving_config: dict, files: dict[str, str]) -> None:
    package = source / PACKAGE
    code = output / "code"
    code.mkdir(parents=True, exist_ok=True)
    for module in sorted(package.rglob("*.py")):
        if "__pycache__" in module.relative_to(package).parts:
            continue
        destination = code / "ml_model_factory" / module.relative_to(package)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module, destination)
    write_bundle_metadata(source, code / "pyproject.toml")
    (code / "scenario.json").write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    (code / "serving.json").write_text(json.dumps(serving_config, indent=2), encoding="utf-8")
    scripts = code / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy2(source / "accelerator" / "scripts" / "online_score.py", scripts / "online_score.py")
    files.update({"code": str(code), "scenario": str(code / "scenario.json"),
                  "serving_config": str(code / "serving.json"), "online_score": str(scripts / "online_score.py")})


def _copy_environment(source: Path, output: Path, filename: str, files: dict[str, str]) -> None:
    destination = output / "environments" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "accelerator" / "environments" / filename, destination)
    files.setdefault("environments", {})[filename] = str(destination)


def _serving_environment(runtime: dict, mode: str, task: str) -> object:
    if runtime.get("serving", {}).get("environment"):
        value = runtime["serving"]["environment"]
        if not isinstance(value, str) or not value.startswith("azureml:"):
            raise ValueError("runtime.serving.environment must be a versioned Azure ML environment URI")
        return value
    env = "vision" if task.startswith("image_") else ("automl" if mode == "automl" else "custom")
    return {
        "image": ("mcr.microsoft.com/azureml/openmpi4.1.0-cuda12.1-cudnn8-ubuntu22.04:latest"
                  if task.startswith("image_") else "mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest"),
        "conda_file": f"./environments/azureml-serving-{env}.yml",
    }


def _compute(runtime: dict, task: str) -> str:
    if task.startswith("image_"):
        return _asset(runtime.get("gpu_compute") or runtime.get("compute") or "")
    return _asset(runtime.get("compute") or "")


def _secure_input_uri(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("input URI is required")
    if "?" in value or "#" in value:
        raise ValueError("input URI must not contain credentials, query strings, or fragments")
    if not (value.startswith("azureml:") or value.startswith("azureml://") or re.match(r"^https://[^?]+", value)):
        raise ValueError("input must be an azureml://, versioned azureml: asset, or HTTPS Blob URI")


def _input_type(uri: str) -> str:
    return "uri_folder" if uri.endswith("/") else "uri_file"


def _load_manifest(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    path = Path(value)
    if path.is_dir():
        path = path / "manifest.json"
    return load_json(path)


def _payload_object(payload):
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        return json.loads(payload)
    if isinstance(payload, dict):
        return dict(payload)
    raise ValueError("Online request payload must be a JSON object")


def _rename_image_column(payload: dict) -> dict:
    def split(value):
        if isinstance(value, dict) and "columns" in value:
            columns = ["image" if column == "image_base64" else column for column in value["columns"]]
            return {**value, "columns": columns}
        return value
    payload = dict(payload)
    if "input_data" in payload:
        value = payload["input_data"]
        if isinstance(value, list):
            payload["input_data"] = [{("image" if key == "image_base64" else key): item for key, item in row.items()} for row in value]
        else:
            payload["input_data"] = split(value)
    if "dataframe_split" in payload:
        payload["dataframe_split"] = split(payload["dataframe_split"])
    if "dataframe_records" in payload:
        payload["dataframe_records"] = [
            {("image" if key == "image_base64" else key): item for key, item in row.items()}
            for row in payload["dataframe_records"]
        ]
    return payload


def adapt_online_request(manifest_or_none, payload, *, history_frame=None) -> dict:
    """Adapt factory online requests for selected Azure ML serving routes."""
    manifest = _load_manifest(manifest_or_none)
    result = _payload_object(payload)
    if manifest and manifest.get("kind") == "online" and manifest.get("mode") == "automl" and str(manifest.get("task", "")).startswith("image_") and manifest.get("scoring") == "mlflow":
        result = _rename_image_column(result)
    if history_frame is not None:
        from .online import attach_history
        result = attach_history(result, history_frame)
    return result


def _write_invocation_file(bundle: Path, name: str, document: dict) -> Path:
    folder = Path(bundle) / "invocations"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}-{uuid4().hex}.json"
    write_json(path, document)
    return path


def _write_resolved_job(bundle: Path, document: dict) -> Path:
    folder = Path(bundle)
    path = folder / f"batch-score-job-{uuid4().hex}.resolved.yml"
    _write_yaml(path, document)
    return path


def _batch_job(output: Path, scenario: dict, runtime: dict, model_uri: str, mode: str, route: str,
               tags: dict, files: dict[str, str]) -> None:
    task = scenario["task"]
    if mode == "automl" and task.startswith("image_") and not runtime.get("automl_vision_environment"):
        raise ValueError("AutoML image batch scoring requires runtime.automl_vision_environment pinned to a reviewed environment")
    env = runtime.get("automl_vision_environment") if mode == "automl" and task.startswith("image_") else _serving_environment(runtime, mode, task)
    command = (
        "python -m pip install --no-deps --no-build-isolation . && "
        "python -m ml_model_factory score --scenario scenario.json --model ${{inputs.model}} "
        "--input ${{inputs.requests}} --output ${{outputs.predictions}}"
    )
    if mode == "automl" and task == "forecasting":
        command += " --mode automl --history ${{inputs.history}}"
    else:
        command += f" --mode {mode}"
    job = {
        "$schema": SCHEMAS + "pipelineJob.schema.json", "type": "pipeline",
        "display_name": _name(scenario["name"], 70) + "-batch-score", "tags": tags,
        "settings": {"default_compute": _compute(runtime, task), "continue_on_step_failure": False},
        "inputs": {
            "model": {"type": "mlflow_model", "path": model_uri},
            "requests": {"type": "uri_folder", "path": "REPLACE_WITH_REQUESTS_URI"},
        },
        "outputs": {"predictions": {"type": "uri_folder"}},
        "jobs": {"score": {"type": "command", "code": "./code", "environment": env,
                            "command": command,
                            "inputs": {"model": "${{parent.inputs.model}}", "requests": "${{parent.inputs.requests}}"},
                            "outputs": {"predictions": "${{parent.outputs.predictions}}"}}},
    }
    identity = _job_identity(runtime)
    if identity is not None:
        job["jobs"]["score"]["identity"] = identity
    if mode == "automl" and task == "forecasting":
        job["inputs"]["history"] = {"type": "uri_folder", "path": "REPLACE_WITH_HISTORY_URI"}
        job["jobs"]["score"]["inputs"]["history"] = "${{parent.inputs.history}}"
    if runtime.get("datastore"):
        job["settings"]["default_datastore"] = _asset(runtime["datastore"])
    files["batch_job"] = _write_yaml(output / "batch-score-job.yml", job)


def render_serving(scenario: dict, runtime: dict, output: Path, *, kind: str, model_name: str,
                   mode: str, scoring: str = "auto", source: Path | None = None,
                   endpoint_name: str | None = None) -> dict[str, str]:
    """Render a serving bundle without contacting Azure."""
    scenario = validate_scenario(copy.deepcopy(scenario))
    if kind not in {"online", "batch"}:
        raise ValueError("kind must be online or batch")
    if mode not in {"custom", "automl"}:
        raise ValueError("mode must be custom or automl")
    runtime = resolve_storage_selection(runtime)
    task = scenario["task"]
    if not model_name or not isinstance(model_name, str):
        raise ValueError("model_name is required")
    settings = _validate_serving(runtime)
    source, output = source_root(source), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Render output must be empty to prevent stale serving artifacts")
    if output == source or output in source.parents or output.is_relative_to(source / PACKAGE):
        raise ValueError("output must not overwrite source or be inside ml_model_factory")
    route = _route(kind, task, mode, scoring)
    if scoring != "auto" and kind == "batch" and route == "mlflow" and not _no_code_batch(task):
        raise ValueError("No-code batch deployment is only supported for tabular classification/regression")
    tags = build_tags(scenario, runtime, mode=mode, engine="azureml")
    endpoint = (_endpoint_name(endpoint_name) if endpoint_name is not None
                else _name(scenario["name"], 24) + ("-online" if kind == "online" else "-batch"))
    model_uri = f"azureml:{model_name}:REPLACE_WITH_REGISTERED_VERSION"
    output.mkdir(parents=True)
    files: dict[str, str] = {}
    serving_config = {"mode": mode, "kind": kind, "scoring": route, "model_version": "REPLACE_WITH_REGISTERED_VERSION",
                      "max_rows": settings.get("max_rows", 1000)}
    if route == "custom":
        _copy_code(source, output, scenario, serving_config, files)
        env_name = "azureml-serving-vision.yml" if task.startswith("image_") else (
            "azureml-serving-automl.yml" if mode == "automl" else "azureml-serving-custom.yml")
        _copy_environment(source, output, env_name, files)
    endpoint_document = {
        "$schema": SCHEMAS + ("managedOnlineEndpoint.schema.json" if kind == "online" else "batchEndpoint.schema.json"),
        "name": endpoint, "auth_mode": "aad_token", "tags": tags,
    }
    if kind == "online" and "public_network_access" in settings:
        endpoint_document["public_network_access"] = settings["public_network_access"]
    files[f"{kind}_endpoint"] = _write_yaml(output / f"{kind}-endpoint.yml", endpoint_document)
    limitations = ["Preview-only render; no Azure resource is created until deploy with --execute."]
    if kind == "online":
        deployment = {
            "$schema": SCHEMAS + "managedOnlineDeployment.schema.json", "name": "blue",
            "endpoint_name": endpoint, "model": model_uri,
            "instance_type": settings.get("online_instance_type", "Standard_DS3_v2"),
            "instance_count": settings.get("instance_count", 1), "tags": tags,
        }
        if "egress_public_network_access" in settings:
            # Legacy per-deployment isolation for private workspaces without a workspace managed VNet.
            deployment["egress_public_network_access"] = settings["egress_public_network_access"]
        if route == "custom":
            deployment["code_configuration"] = {"code": "./code", "scoring_script": "scripts/online_score.py"}
            deployment["environment"] = _serving_environment(runtime, mode, task)
            limitations.append("Custom-code online deployments require azureml-inference-server-http in the environment.")
        elif mode == "automl" and task.startswith("image_"):
            limitations.append("AutoML image online no-code requests follow the Microsoft Learn image schema; use an image column.")
        files["online_deployment"] = _write_yaml(output / "online-deployment.yml", deployment)
    elif route == "mlflow":
        batch = {
            "$schema": SCHEMAS + "modelBatchDeployment.schema.json", "type": "model", "name": "blue",
            "endpoint_name": endpoint, "model": model_uri, "compute": _compute(runtime, task), "tags": tags,
            "resources": {"instance_count": settings.get("batch_instance_count", 1)},
            "settings": {"max_concurrency_per_instance": 1, "mini_batch_size": 10,
                         "output_action": "append_row", "output_file_name": "predictions.csv",
                         "error_threshold": 0, "retry_settings": {"max_retries": 2, "timeout": 300}},
        }
        files["batch_deployment"] = _write_yaml(output / "batch-deployment.yml", batch)
    else:
        _batch_job(output, scenario, runtime, model_uri, mode, route, tags, files)
        limitations.append("Batch scoring-job bundles are submitted as jobs; they are not persistent batch endpoint deployments.")
        if task.startswith("image_") and not runtime.get("gpu_compute"):
            limitations.append("Vision batch scoring is rendered on CPU because runtime.gpu_compute is not configured.")
    manifest = {
        "mode": mode, "task": task, "model_name": model_name, "scenario_name": scenario["name"],
        "model_tags": tags, "files": files, "limitations": limitations, "kind": kind, "scoring": route,
        "endpoint_name": None if kind == "batch" and route == "custom" else endpoint,
        "sample_request": "Use sample-requests to create online-request.json; labels must not be sent to serving endpoints.",
        "sources": [INFERENCE_SERVER_DOC, AUTOML_IMAGE_SCHEMA],
    }
    files["manifest"] = str(output / "manifest.json")
    write_json(output / "manifest.json", manifest)
    return files


def _registered(client, runtime: dict, bundle: Path, model_id: str):
    name, version = serving._model_name_version(model_id)
    registered = client.models.get(name=name, version=version)
    tags = registered.tags or {}
    manifest = load_json(Path(bundle) / "manifest.json")
    if (registered.type != "mlflow_model" or tags.get("quality_gate") != "passed" or not tags.get("pipeline_job")):
        raise ValueError("Deploy only MLflow models registered from a passing factory pipeline")
    if name != manifest["model_name"]:
        raise ValueError("Registered model name does not match this rendered bundle")
    if tags.get("factory_scenario") != manifest["scenario_name"]:
        raise ValueError("Registered model scenario does not match this rendered bundle")
    if tags.get("factory_mode") != manifest["mode"]:
        raise ValueError("Registered model training mode does not match this rendered bundle")
    if scope_tags(runtime) or tags.get("tag_schema"):
        assert_scope(tags, runtime)
    return registered, manifest


def _write_serving_model_version(bundle: Path, version: str) -> None:
    path = Path(bundle) / "code" / "serving.json"
    if not path.is_file():
        return
    serving_config = load_json(path)
    serving_config["model_version"] = str(version)
    write_json(path, serving_config)


def deploy_serving(runtime: dict, bundle: Path, model_id: str, *, execute: bool = False, client=None) -> dict:
    bundle = Path(bundle)
    manifest = load_json(bundle / "manifest.json")
    route = manifest["scoring"]
    result = {"preview_only": not execute, "kind": manifest["kind"], "scoring": route,
              "model": model_id, "cost_warning": "Managed online endpoints bill while deployed; delete when idle."}
    if manifest["kind"] == "batch" and route == "custom":
        message = "Batch scoring-job bundles have no persistent endpoint deployment; submit them per invocation with serving-invoke --kind batch --bundle --model-id --input."
        if execute:
            raise ValueError(message)
        return {**result, "endpoint": None, "message": message}
    if not execute:
        return {**result, "endpoint": yaml.safe_load((bundle / f"{manifest['kind']}-endpoint.yml").read_text())["name"]}
    if route == "mlflow" and client is None:
        return {**result, "endpoint": serving.deploy(runtime, bundle, model_id, kind=manifest["kind"])}
    client = client or _client(runtime)
    _, resolved_version = serving._model_name_version(model_id)
    registered, manifest = _registered(client, runtime, bundle, model_id)
    if manifest["kind"] == "online" and route == "custom":
        _write_serving_model_version(bundle, resolved_version)
    if manifest["kind"] == "online":
        from azure.ai.ml import load_online_deployment, load_online_endpoint
        endpoint = load_online_endpoint(source=str(bundle / "online-endpoint.yml"))
        deployment = load_online_deployment(source=str(bundle / "online-deployment.yml"))
        deployment.model = registered.id
        endpoint.tags, omitted = serving_resource_tags(registered.tags, lifecycle_stage="deployment",
                                                       serving_pattern="online")
        deployment.tags = dict(endpoint.tags)
        client.online_endpoints.begin_create_or_update(endpoint).result()
        client.online_deployments.begin_create_or_update(deployment).result()
        endpoint = client.online_endpoints.get(endpoint.name)
        endpoint.traffic = {deployment.name: 100}
        client.online_endpoints.begin_create_or_update(endpoint).result()
        return {**result, "endpoint": endpoint.name, "deployment": deployment.name, "resolved_version": resolved_version,
                "omitted_resource_tags": omitted}
    if route == "mlflow":
        from azure.ai.ml import load_batch_endpoint
        endpoint = load_batch_endpoint(source=str(bundle / "batch-endpoint.yml"))
        deployment = serving.load_model_batch_deployment(bundle / "batch-deployment.yml")
        deployment.model = registered.id
        endpoint.tags, omitted = serving_resource_tags(registered.tags, lifecycle_stage="deployment",
                                                       serving_pattern="batch")
        deployment.tags = dict(endpoint.tags)
        client.batch_endpoints.begin_create_or_update(endpoint).result()
        client.batch_deployments.begin_create_or_update(deployment).result()
        endpoint = client.batch_endpoints.get(endpoint.name)
        endpoint.defaults.deployment_name = deployment.name
        client.batch_endpoints.begin_create_or_update(endpoint).result()
        return {**result, "endpoint": endpoint.name, "deployment": deployment.name, "omitted_resource_tags": omitted}
    resolved = bundle / "batch-score-job.resolved.yml"
    text = (bundle / "batch-score-job.yml").read_text(encoding="utf-8").replace(
        f"azureml:{manifest['model_name']}:REPLACE_WITH_REGISTERED_VERSION", registered.id)
    resolved.write_text(text, encoding="utf-8")
    validate_job_storage(yaml.safe_load(text), runtime)
    from azure.ai.ml import load_job
    job = client.jobs.create_or_update(load_job(source=str(resolved)))
    return {**result, "job": job.name, "job_file": str(resolved)}


def invoke_online(runtime: dict, endpoint_name: str, request_path: Path, *, bundle: Path | None = None,
                  history_path: Path | None = None, deployment: str | None = None,
                  execute: bool = False, client=None) -> dict:
    if not endpoint_name:
        raise ValueError("--endpoint is required for online invocation")
    if not Path(request_path).is_file():
        raise FileNotFoundError(f"Request file not found: {request_path}")
    request_file = Path(request_path)
    if bundle is not None or history_path is not None:
        from .data import read_frame
        payload = json.loads(request_file.read_text(encoding="utf-8"))
        history = read_frame(history_path) if history_path is not None else None
        adapted = adapt_online_request(Path(bundle) if bundle is not None else None, payload, history_frame=history)
        request_file = _write_invocation_file(Path(bundle) if bundle is not None else request_file.parent, "online-request", adapted)
    result = {"preview_only": not execute, "kind": "online", "endpoint": endpoint_name,
              "request": str(request_file), "deployment": deployment}
    if not execute:
        return result
    client = client or _client(runtime)
    response = client.online_endpoints.invoke(endpoint_name=endpoint_name, request_file=str(request_file),
                                              deployment_name=deployment)
    return {**result, "response": response}


def _resolve_scoring_job(runtime: dict, bundle: Path, model_id: str, input_uri: str, history_uri: str | None,
                         client, inference_run_id: str | None = None) -> tuple[dict, Path, dict, dict]:
    bundle = Path(bundle)
    registered, manifest = _registered(client, runtime, bundle, model_id)
    if manifest.get("kind") != "batch" or manifest.get("scoring") != "custom":
        raise ValueError("--bundle batch invocation requires a batch scoring-job serving bundle")
    _secure_input_uri(input_uri)
    if history_uri is not None:
        _secure_input_uri(history_uri)
    job = yaml.safe_load((bundle / "batch-score-job.yml").read_text(encoding="utf-8"))
    job["inputs"]["model"]["path"] = registered.id
    job["inputs"]["requests"].update({"path": input_uri, "type": _input_type(input_uri)})
    if "history" in job.get("inputs", {}):
        if not history_uri:
            raise ValueError("AutoML forecasting scoring-job invocation requires --history")
        job["inputs"]["history"].update({"path": history_uri, "type": _input_type(history_uri)})
    elif history_uri:
        raise ValueError("--history is only valid for scoring-job bundles that declare a history input")
    binding = {}
    lake = resolve_storage_selection(runtime).get("lake")
    if inference_run_id is not None and not lake:
        raise ValueError("--inference-run-id requires runtime.lake")
    if lake:
        # Unbound outputs land in the default datastore's azureml/ area, outside governed lake ACLs.
        from .lake import LakeLayout, identifier

        # Each invocation owns its inference run: reusing the training run_id would make every scoring
        # of a model version share one out/ folder (later runs fail, concurrent runs overwrite).
        run_id = identifier(inference_run_id or
                            f"score-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}", "inference_run_id")
        if run_id == lake.get("run_id"):
            raise ValueError("--inference-run-id must differ from the training lake.run_id")
        version = serving._model_name_version(model_id)[1]
        scenario = load_json(bundle / "code" / "scenario.json")
        layout = LakeLayout.from_config({**copy.deepcopy(lake), "serving": "batch", "model_version": version,
                                         "run_id": run_id}, scenario)
        datastore = layout.datastore or runtime.get("datastore")
        if datastore:
            uri = layout.azureml_uri("output", datastore=datastore)
            job["outputs"]["predictions"].update(path=uri, mode="rw_mount")
            binding = {"inference_run_id": run_id, "predictions_uri": uri}
    text = yaml.safe_dump(job, sort_keys=False)
    if "REPLACE_WITH_" in text:
        raise ValueError("Scoring-job invocation still contains unresolved placeholders")
    validate_job_storage(job, runtime)
    resolved = _write_resolved_job(bundle, job)
    return job, resolved, manifest, binding


def invoke_batch(runtime: dict, endpoint_name: str | None = None, input_uri: str | None = None, *,
                 bundle: Path | None = None, model_id: str | None = None, history_uri: str | None = None,
                 deployment: str | None = None, execute: bool = False, client=None,
                 inference_run_id: str | None = None) -> dict:
    if not input_uri:
        raise ValueError("--input is required for batch invocation")
    if bundle is not None:
        if not model_id:
            raise ValueError("--model-id is required with --bundle for batch scoring-job invocation")
        client = client or _client(runtime)
        _, resolved, manifest, binding = _resolve_scoring_job(runtime, Path(bundle), model_id, input_uri, history_uri,
                                                              client, inference_run_id)
        result = {"preview_only": not execute, "kind": "batch", "endpoint": None, "bundle": str(bundle),
                  "model": model_id, "input": input_uri, "history": history_uri, "job_file": str(resolved),
                  **binding,
                  "note": "If --input or --history is a folder URI, it must contain data.parquet for ml_model_factory.read_frame."}
        if not execute:
            return result
        from azure.ai.ml import load_job
        job = client.jobs.create_or_update(load_job(source=str(resolved)))
        return {**result, "job": job.name}
    if not endpoint_name:
        raise ValueError("Batch endpoint invocation requires --endpoint, or use --bundle with --model-id for scoring jobs")
    _secure_input_uri(input_uri)
    result = {"preview_only": not execute, "kind": "batch", "endpoint": endpoint_name,
              "input": input_uri, "deployment": deployment}
    if not execute:
        return result
    from azure.ai.ml import Input
    client = client or _client(runtime)
    job = client.batch_endpoints.invoke(endpoint_name=endpoint_name, deployment_name=deployment,
                                        input=Input(path=input_uri, type=_input_type(input_uri)))
    return {**result, "job": job.name}


def delete_endpoint(runtime: dict, kind: str, endpoint_name: str, *, execute: bool = False, client=None) -> dict:
    if kind not in {"online", "batch"}:
        raise ValueError("kind must be online or batch")
    result = {"preview_only": not execute, "kind": kind, "endpoint": endpoint_name,
              "cost_control": "Deletion stops managed online endpoint billing."}
    if not execute:
        return result
    client = client or _client(runtime)
    operations = client.online_endpoints if kind == "online" else client.batch_endpoints
    operations.begin_delete(name=endpoint_name).result()
    return {**result, "deleted": True}


def _render_command(args):
    return render_serving(load_json(args.scenario), load_json(args.runtime), args.output, kind=args.kind,
                          model_name=args.model_name, mode=args.mode, scoring=args.scoring, source=args.source,
                          endpoint_name=args.endpoint_name)


def _deploy_command(args):
    return deploy_serving(load_json(args.runtime), args.bundle, args.model_id, execute=args.execute)


def _invoke_command(args):
    runtime = load_json(args.runtime)
    if args.kind == "online":
        if not args.request:
            raise ValueError("--request is required for online invocation")
        return invoke_online(runtime, args.endpoint, args.request, bundle=args.bundle, history_path=Path(args.history) if args.history else None,
                             deployment=args.deployment, execute=args.execute)
    if not args.input:
        raise ValueError("--input is required for batch invocation")
    if args.bundle and not args.model_id:
        raise ValueError("--model-id is required with --bundle for batch scoring-job invocation")
    if not args.bundle and not args.endpoint:
        raise ValueError("Batch invocation requires either --endpoint or --bundle with --model-id")
    return invoke_batch(runtime, args.endpoint, args.input, bundle=args.bundle, model_id=args.model_id,
                        history_uri=args.history, deployment=args.deployment, execute=args.execute,
                        inference_run_id=args.inference_run_id)


def _delete_command(args):
    return delete_endpoint(load_json(args.runtime), args.kind, args.endpoint, execute=args.execute)


def add_commands(commands) -> None:
    render = commands.add_parser("serving-render", help="Render Azure ML online/batch serving definitions")
    render.add_argument("--scenario", required=True, type=Path)
    render.add_argument("--runtime", required=True, type=Path)
    render.add_argument("--kind", required=True, choices=("online", "batch"))
    render.add_argument("--model-name", required=True)
    render.add_argument("--mode", required=True, choices=("custom", "automl"))
    render.add_argument("--output", required=True, type=Path)
    render.add_argument("--scoring", choices=("auto", "mlflow", "custom"), default="auto")
    render.add_argument("--source", type=Path)
    render.add_argument("--endpoint-name", help="Region-unique endpoint name (3-32 chars); defaults to <scenario>-online/-batch")
    render.set_defaults(handler=_render_command)

    deploy = commands.add_parser("serving-deploy", help="Preview or execute an Azure ML serving deployment")
    deploy.add_argument("--runtime", required=True, type=Path)
    deploy.add_argument("--bundle", required=True, type=Path)
    deploy.add_argument("--model-id", required=True)
    deploy.add_argument("--execute", action="store_true")
    deploy.set_defaults(handler=_deploy_command)

    invoke = commands.add_parser("serving-invoke", help="Preview or execute serving invocation")
    invoke.add_argument("--runtime", required=True, type=Path)
    invoke.add_argument("--kind", required=True, choices=("online", "batch"))
    invoke.add_argument("--endpoint")
    invoke.add_argument("--request", type=Path)
    invoke.add_argument("--input")
    invoke.add_argument("--bundle", type=Path)
    invoke.add_argument("--model-id")
    invoke.add_argument("--history")
    invoke.add_argument("--deployment")
    invoke.add_argument("--inference-run-id", help="Lake-bound batch scoring jobs: new inference run ID "
                        "(differs from the training lake.run_id); generated per invocation when omitted")
    invoke.add_argument("--execute", action="store_true")
    invoke.set_defaults(handler=_invoke_command)

    delete = commands.add_parser("serving-delete", help="Preview or delete a serving endpoint")
    delete.add_argument("--runtime", required=True, type=Path)
    delete.add_argument("--kind", required=True, choices=("online", "batch"))
    delete.add_argument("--endpoint", required=True)
    delete.add_argument("--execute", action="store_true")
    delete.set_defaults(handler=_delete_command)
