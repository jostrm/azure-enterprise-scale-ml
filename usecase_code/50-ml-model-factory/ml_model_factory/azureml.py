"""Portable Azure ML SDK v2 / CLI v2 definitions; rendering never contacts Azure."""

from __future__ import annotations

import copy
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml
from .tags import build_tags, merge_registration_tags, scope_tags


SCHEMAS = "https://azuremlschemas.azureedge.net/latest/"
TASK_SCHEMAS = {
    "classification": "autoMLClassificationJob",
    "regression": "autoMLRegressionJob",
    "forecasting": "autoMLForecastingJob",
    "image_classification": "autoMLImageClassificationJob",
    "image_classification_multilabel": "autoMLImageClassificationMultilabelJob",
    "image_object_detection": "autoMLImageObjectDetectionJob",
    "image_instance_segmentation": "autoMLImageInstanceSegmentationJob",
}
METRICS = {
    "classification": "accuracy",
    "regression": "normalized_root_mean_squared_error",
    "forecasting": "normalized_root_mean_squared_error",
    "image_classification": "accuracy",
    "image_classification_multilabel": "iou",
    "image_object_detection": "mean_average_precision",
    "image_instance_segmentation": "mean_average_precision",
}
TABLE_LIMITS = {
    "enable_early_termination", "exit_score", "max_concurrent_trials",
    "max_cores_per_trial", "max_nodes", "max_trials", "timeout_minutes",
    "trial_timeout_minutes",
}
IMAGE_LIMITS = {"max_concurrent_trials", "max_trials", "timeout_minutes"}
LAKE_LINEAGE_FIELDS = ("project", "environment", "use_case", "dataset", "data_version", "snapshot_id", "run_id")


def _lake_context(scenario: dict, runtime: dict) -> dict | None:
    """Resolve optional lake bindings without importing an Azure SDK or opening storage."""
    if "lake" not in runtime:
        return None
    from .lake import LakeLayout, lake_manifest

    config = runtime["lake"]
    layout = LakeLayout.from_config(config, scenario)
    for field, selectors in (
        ("project", ("project", "project_number")),
        ("environment", ("environment_name", "target_environment")),
    ):
        for selector in selectors:
            if selector in runtime and runtime[selector] != config[field]:
                raise ValueError(f"runtime.{selector} does not match runtime.lake.{field}")
    safe = {key: getattr(layout, key) for key in (
        *LAKE_LINEAGE_FIELDS, "serving", "model_version", "pipeline_id", "pipeline_version", "prefix",
    )}
    factory = scope_tags(runtime).get("aifactory")
    if factory:
        safe["aifactory"] = factory
    storage = {key: getattr(layout, key) for key in ("account_url", "container", "datastore")
               if getattr(layout, key) is not None}
    if storage:
        safe["storage"] = storage
    # A datastore is an explicit Azure ML resource, never inferred from an account URL.
    datastore = safe.get("storage", {}).get("datastore")
    if runtime.get("datastore") and datastore and runtime["datastore"] != datastore:
        raise ValueError("runtime.datastore does not match runtime.lake.storage.datastore")
    datastore = datastore or runtime.get("datastore")
    bindings = {name: layout.azureml_uri(key, datastore=datastore) for name, key in (
        ("model", "training_model"), ("report", "training_evaluation"),
    )}
    bindings["prepared"] = layout.azureml_uri("training_run", datastore=datastore) + "prepared/"
    if datastore:
        safe.setdefault("storage", {})["datastore"] = datastore
    return {**lake_manifest(layout, scenario), "config": safe, "bindings": bindings}


def _write_yaml(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return str(path)


def _name(value: str, limit: int = 32) -> str:
    name = re.sub("[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not name:
        raise ValueError("scenario.name must contain letters or digits")
    if not name[0].isalpha():
        name = "model-" + name
    return name[:limit].rstrip("-")


def _asset(name: str) -> str:
    return name if name.startswith("azureml:") else "azureml:" + name


def _raw_input(value: str, datastore: str | None = None) -> dict:
    if not value:
        raise ValueError("runtime.input_data must identify the raw file or folder")
    if re.match(r"^(azureml:|https?://|wasbs?://|abfss?://)", value):
        kind = "uri_folder" if value.endswith("/") else "uri_file"
        path = value
    else:
        local = Path(value).expanduser().resolve()
        if not local.exists():
            raise FileNotFoundError(f"Raw input does not exist: {local}")
        kind = "uri_folder" if local.is_dir() else "uri_file"
        path = str(local)
    result = {"type": kind, "path": path, "mode": "download"}
    if datastore:
        result["datastore"] = datastore
    return result


def _environment(runtime: dict, mode: str) -> Any:
    if runtime.get("environment"):
        value = runtime["environment"]
        if not isinstance(value, str) or not value.startswith("azureml:"):
            raise ValueError("runtime.environment must be a versioned Azure ML environment URI")
        return value
    return {
        "image": ("mcr.microsoft.com/azureml/openmpi4.1.0-cuda12.1-cudnn8-ubuntu22.04:latest"
                  if mode == "vision" else
                  "mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest"),
        "conda_file": f"./environments/azureml-{mode}.yml",
    }


def _automl(scenario: dict, runtime: dict, *, standalone: bool) -> dict:
    task = scenario["task"]
    image = task.startswith("image_")
    settings = scenario.get("automl", {})
    limits = copy.deepcopy(settings.get("limits", {}))
    unknown = set(limits) - (IMAGE_LIMITS if image else TABLE_LIMITS)
    if unknown:
        raise ValueError(f"Unsupported AutoML {task} limits: {sorted(unknown)}")
    limits.setdefault("max_trials", 4)
    limits.setdefault("max_concurrent_trials", 1)
    limits.setdefault("timeout_minutes", 60)
    compute = runtime.get("gpu_compute") if image else runtime.get("compute")
    if not compute:
        raise ValueError("runtime.gpu_compute is required for image AutoML" if image
                         else "runtime.compute is required")
    result = {
        "type": "automl",
        "task": task,
        "compute": _asset(compute),
        "target_column_name": scenario["target"],
        "primary_metric": settings.get("primary_metric", METRICS[task]),
        "limits": limits,
        "outputs": {"best_model": {"type": "mlflow_model"}},
    }
    if standalone:
        result = {"$schema": SCHEMAS + TASK_SCHEMAS[task] + ".schema.json", **result}
        result["experiment_name"] = _name(scenario["name"], 100)
        result["training_data"] = {
            "type": "mltable",
            "path": "azureml://jobs/REPLACE_WITH_PREPARE_JOB/outputs/train/paths/",
        }
        result["validation_data"] = {
            "type": "mltable",
            "path": "azureml://jobs/REPLACE_WITH_PREPARE_JOB/outputs/validation/paths/",
        }
    else:
        result["training_data"] = "${{parent.jobs.prepare.outputs.train}}"
        result["validation_data"] = "${{parent.jobs.prepare.outputs.validation}}"
    if not image:
        result["featurization"] = {"mode": "auto"}
    if task == "forecasting":
        forecast = scenario.get("forecast", {})
        if not forecast.get("time_column") or not forecast.get("horizon"):
            raise ValueError("forecast.time_column and forecast.horizon are required")
        result["forecasting"] = {
            "time_column_name": forecast["time_column"],
            "forecast_horizon": forecast["horizon"],
        }
        if forecast.get("series_columns"):
            result["forecasting"]["time_series_id_column_names"] = forecast["series_columns"]
        if forecast.get("frequency"):
            result["forecasting"]["frequency"] = forecast["frequency"]
    if image:
        vision = scenario.get("vision", {})
        for key in ("training_parameters", "search_space", "sweep"):
            if key in vision:
                result[key] = copy.deepcopy(vision[key])
    return result


def render(
    scenario: dict,
    runtime: dict,
    output: Path,
    source: Path,
    mode: str = "automl",
) -> dict[str, str]:
    """Render a self-contained submission bundle without provisioning resources.

    Standalone training consumes the outputs of prepare-job.yml; replace its
    REPLACE_WITH_PREPARE_JOB token, or override the prepared input paths.
    Pipeline registration is deliberately an explicit, post-quality-gate action.
    """
    if mode not in {"automl", "custom"}:
        raise ValueError("mode must be 'automl' or 'custom'")
    task = scenario.get("task")
    if task not in TASK_SCHEMAS:
        raise ValueError(f"Unsupported task: {task}")
    image = task.startswith("image_")
    if image and not runtime.get("gpu_compute"):
        raise ValueError("runtime.gpu_compute is required for image training")
    if not runtime.get("compute"):
        raise ValueError("runtime.compute must identify an existing Azure ML compute")
    if not image and not scenario.get("target"):
        raise ValueError("scenario.target is required")
    scenario = copy.deepcopy(scenario)
    if image:
        scenario.setdefault("target", "label")
    source, output = Path(source).resolve(), Path(output).resolve()
    package = source / "ml_model_factory"
    if not package.is_dir():
        raise FileNotFoundError(f"Missing package source: {package}")
    if output == source or output in source.parents or output.is_relative_to(package):
        raise ValueError("output must not overwrite source or be inside ml_model_factory")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Render output must be empty to prevent stale submission artifacts")
    # Validate before creating files. No credentials or full repository are uploaded.
    lake = _lake_context(scenario, runtime)
    model_tags = build_tags(scenario, runtime, mode=mode, engine="azureml")
    raw = _raw_input(str(runtime.get("input_data", "")), runtime.get("datastore"))
    if image:
        raw["type"] = "uri_folder"
    serving = runtime.get("serving", {})
    for key in ("instance_count", "batch_instance_count"):
        value = serving.get(key, 1)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"runtime.serving.{key} must be a positive integer")
    automl = _automl(scenario, runtime, standalone=False) if mode == "automl" else None
    output.mkdir(parents=True, exist_ok=True)
    code = output / "code"
    code.mkdir(exist_ok=True)
    shutil.copytree(package, code / "ml_model_factory", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".venv"))
    shutil.copy2(source / "pyproject.toml", code / "pyproject.toml")
    (code / "scenario.json").write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    (code / "model-tags.json").write_text(json.dumps(model_tags, indent=2), encoding="utf-8")
    (code / "scripts").mkdir(exist_ok=True)
    files: dict[str, str] = {}
    for filename in ("azureml_prepare.py", "azureml_evaluate.py", "azureml_sdk.py", "azureml_cli.py"):
        origin = source / "scripts" / filename
        shutil.copy2(origin, code / "scripts" / filename)
        files[filename.removesuffix(".py")] = str(code / "scripts" / filename)
    for filename in ("azureml-custom.yml", "azureml-automl.yml", "azureml-vision.yml"):
        destination = output / "environments" / filename
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(source / "environments" / filename, destination)
    # Account and resource names are configuration, not authentication material.
    safe_runtime = {k: runtime[k] for k in (
        "subscription_id", "tenant_id", "resource_group", "workspace_name",
        "compute", "gpu_compute", "datastore", "environment", "serving",
        "credential", "managed_identity_client_id", "project", "project_number",
        "environment_name", "target_environment",
        "aifactory",
    ) if k in runtime}
    if lake is not None:
        safe_runtime["lake"] = lake["config"]
        (code / "lake.json").write_text(json.dumps(lake["config"], indent=2), encoding="utf-8")
        lake["split_outputs"] = {} if image else {
            split: f"azureml://jobs/REPLACE_WITH_PREPARE_JOB/outputs/{split}/paths/"
            for split in ("train", "validation", "test")
        }
        lake["write_policy"] = (
            "Use a new run_id for each preparation/training attempt. Preparation writes run-scoped "
            "prepared data, not the shared training_snapshot/training_gold paths. Those snapshot "
            "paths are references only; this bundle does not publish an immutable snapshot. "
            "Explicit paths are not storage-enforced immutable: reruns can target the same URI. "
            "Preparation refuses locally visible nonempty outputs; rendering does not check remote "
            "existence, acquire a lease, or prevent concurrent submissions. Standalone jobs and the "
            "pipeline are alternatives, not separate writers to the same run."
        )
        files["lake_config"] = str(code / "lake.json")
        files["lake_manifest"] = str(output / "lake-manifest.json")
        for path in (code / "lake-manifest.json", output / "lake-manifest.json"):
            path.write_text(json.dumps(lake, indent=2), encoding="utf-8")
    (output / "runtime.json").write_text(json.dumps(safe_runtime, indent=2), encoding="utf-8")
    files["runtime"] = str(output / "runtime.json")
    files["scenario"] = str(code / "scenario.json")
    environment = _environment(runtime, "vision" if image else "custom")
    common = {"type": "command", "code": "./code", "environment": environment}
    install = "python -m pip install --no-deps --no-build-isolation . && "
    prepare = {
        **copy.deepcopy(common),
        "command": install + (
            "python scripts/azureml_prepare.py --scenario scenario.json "
            '--input "${{inputs.raw}}" --prepared "${{outputs.prepared}}" '
            '--train "${{outputs.train}}" --validation "${{outputs.validation}}" '
            '--test "${{outputs.test}}"'
        ),
        "inputs": {"raw": "${{parent.inputs.raw}}"},
        "outputs": {
            "prepared": {"type": "uri_folder"},
            "train": {"type": "mltable"},
            "validation": {"type": "mltable"},
            "test": {"type": "mltable"},
        },
    }
    if image:
        prepare["command"] = install + (
            "python scripts/azureml_prepare.py --scenario scenario.json "
            '--input "${{inputs.raw}}" --prepared "${{outputs.prepared}}"'
        )
        prepare["outputs"] = {"prepared": {"type": "uri_folder"}}
    if lake is not None:
        prepare["command"] += " --lake-config lake.json"
        prepare["outputs"]["prepared"].update(path=lake["bindings"]["prepared"], mode="rw_mount")
    standalone_prepare = copy.deepcopy(prepare)
    standalone_prepare.update({
        "$schema": SCHEMAS + "commandJob.schema.json",
        "compute": _asset(runtime["compute"]),
        "experiment_name": _name(scenario["name"], 100),
        "inputs": {"raw": raw},
    })
    standalone_prepare["tags"] = {**model_tags, "lifecycle_stage": "prepare"}
    files["prepare_job"] = _write_yaml(output / "prepare-job.yml", standalone_prepare)
    train = {
        **copy.deepcopy(common),
        "command": install + (
            "python -m ml_model_factory train --scenario scenario.json "
            '--prepared "${{inputs.prepared}}" --model-output "${{outputs.model}}" '
            "--model-tags model-tags.json"
        ),
        "inputs": {"prepared": "${{parent.jobs.prepare.outputs.prepared}}"},
        "outputs": {"model": "${{parent.outputs.model}}"},
    }
    if image:
        train["compute"] = _asset(runtime["gpu_compute"])
    if mode == "automl":
        train = automl
        train["outputs"]["best_model"] = "${{parent.outputs.model}}"
        standalone = _automl(scenario, runtime, standalone=True)
        model_ref = "${{parent.jobs.train.outputs.best_model}}"
    else:
        standalone = copy.deepcopy(train)
        standalone.update({
            "$schema": SCHEMAS + "commandJob.schema.json",
            "compute": _asset(runtime["gpu_compute"] if image else runtime["compute"]),
            "experiment_name": _name(scenario["name"], 100),
            "inputs": {"prepared": {
                "type": "uri_folder",
                "path": "azureml://jobs/REPLACE_WITH_PREPARE_JOB/outputs/prepared/paths/",
            }},
            "outputs": {"model": {"type": "mlflow_model"}},
        })
        model_ref = "${{parent.jobs.train.outputs.model}}"
    if lake is not None:
        standalone["outputs"]["best_model" if mode == "automl" else "model"]["path"] = lake["bindings"]["model"]
    standalone["tags"] = {**model_tags, "lifecycle_stage": "train"}
    files["training_job"] = _write_yaml(output / "job.yml", standalone)
    files["job"] = files["training_job"]
    pipeline = {
        "$schema": SCHEMAS + "pipelineJob.schema.json",
        "type": "pipeline",
        "display_name": _name(scenario["name"], 80) + "-" + mode,
        "experiment_name": _name(scenario["name"], 100),
        "tags": {**model_tags, "factory_quality_gate": "evaluate", "factory_mode": mode,
                 "factory_task": task, "factory_scenario": scenario["name"]},
        "settings": {"default_compute": _asset(runtime["compute"]),
                     "continue_on_step_failure": False},
        "inputs": {"raw": raw},
        "outputs": {"model": {"type": "mlflow_model"}, "report": {"type": "uri_folder"}},
        "jobs": {
            "prepare": prepare,
            "train": train,
            "evaluate": {
                **copy.deepcopy(common),
                "environment": _environment(runtime, "automl") if mode == "automl" else environment,
                **({"compute": _asset(runtime["gpu_compute"])} if image else {}),
                "command": install + (
                    f"python scripts/azureml_evaluate.py --mode {mode} --scenario scenario.json "
                    '--prepared "${{inputs.prepared}}" --model "${{inputs.model}}" '
                    '--output "${{outputs.report}}"'
                    ' --model-tags model-tags.json'
                ),
                "inputs": {"prepared": "${{parent.jobs.prepare.outputs.prepared}}",
                           "model": model_ref},
                "outputs": {"report": "${{parent.outputs.report}}"},
            },
        },
    }
    if runtime.get("datastore"):
        pipeline["settings"]["default_datastore"] = _asset(runtime["datastore"])
    if lake is not None:
        for name in ("model", "report"):
            pipeline["outputs"][name]["path"] = lake["bindings"][name]
        pipeline["outputs"]["report"]["mode"] = "rw_mount"
        pipeline["jobs"]["evaluate"]["command"] += " --lake-config lake.json"
        pipeline["tags"].update({f"factory_lake_{key}": lake["config"][key] for key in LAKE_LINEAGE_FIELDS})
    # Vision training is supported, but a tabular evaluator cannot certify boxes
    # or masks. Do not publish an executable-looking, false end-to-end example.
    if not image or mode == "custom":
        files["pipeline_job"] = _write_yaml(output / "pipeline.yml", pipeline)
        files["pipeline"] = files["pipeline_job"]
    if mode == "custom" and task in {"classification", "regression"}:
        files["rai_pipeline"] = _write_yaml(output / "rai-pipeline.yml", _rai_pipeline(scenario, runtime))
    endpoint = _name(scenario["name"], 24)
    model_name = scenario.get("model_name", endpoint)
    model_uri = f"azureml:{model_name}:REPLACE_WITH_REGISTERED_VERSION"
    files["online_endpoint"] = _write_yaml(output / "online-endpoint.yml", {
        "$schema": SCHEMAS + "managedOnlineEndpoint.schema.json",
        "name": endpoint + "-online", "auth_mode": "aad_token", "tags": model_tags,
    })
    files["online_deployment"] = _write_yaml(output / "online-deployment.yml", {
        "$schema": SCHEMAS + "managedOnlineDeployment.schema.json",
        "name": "blue", "endpoint_name": endpoint + "-online", "model": model_uri,
        "instance_type": serving.get("online_instance_type", "Standard_DS3_v2"),
        "instance_count": serving.get("instance_count", 1),
        "tags": model_tags,
    })
    files["batch_endpoint"] = _write_yaml(output / "batch-endpoint.yml", {
        "$schema": SCHEMAS + "batchEndpoint.schema.json",
        "name": endpoint + "-batch", "auth_mode": "aad_token", "tags": model_tags,
    })
    batch = {
        "$schema": SCHEMAS + "modelBatchDeployment.schema.json",
        "type": "model", "name": "blue", "endpoint_name": endpoint + "-batch",
        "model": model_uri, "compute": _asset(runtime["compute"]),
        "tags": model_tags,
        "resources": {"instance_count": serving.get("batch_instance_count", 1)},
        "settings": {"max_concurrency_per_instance": 1, "mini_batch_size": 10,
                     "output_action": "append_row", "output_file_name": "predictions.csv",
                     "error_threshold": 0, "retry_settings": {"max_retries": 2, "timeout": 300}},
    }
    if not image and not (task == "forecasting" and mode == "automl"):
        files["batch_deployment"] = _write_yaml(output / "batch-deployment.yml", batch)
    if mode == "automl" and image:
        for key in ("online_deployment",):
            Path(files.pop(key)).unlink()
    manifest = {
        "mode": mode, "task": task, "model_name": model_name, "scenario_name": scenario["name"],
        "model_tags": model_tags,
        "standalone_preparation": "Submit prepare-job.yml; replace REPLACE_WITH_PREPARE_JOB "
        "in job.yml with the completed preparation job name.",
        "registration": "Only a successful generated pipeline containing evaluate and a downloaded "
        "passing quality-gate.json may register its named model output. Standalone training is not a quality gate.",
        "online": "MLflow no-code deployment uses the registered model's own environment. "
        "Set REPLACE_WITH_REGISTERED_VERSION before deployment; endpoint names must be unique.",
        "batch": "No-code MLflow deployment: CSV inputs must contain only model features with headers. "
        "Do not submit labeled test files. Errors fail the batch job; no custom scoring script is injected.",
        "limitations": (
            ["AutoML vision is training-only: replace training/validation MLTable paths with "
             "Azure-compatible image JSONL assets. No AutoML vision preparation, gated pipeline, "
             "registration, or deployment is supported by this factory."] if image and mode == "automl" else
            ["Custom vision online requests must match the exported MLflow model signature. "
             "Image batch endpoints are not generated."] if image else
            ["AutoML forecast evaluation supports sklearn-flavor models exposing forecast(), "
             "using validation observations as history; TCN/PyTorch requires a separate adapter. "
             "No no-code AutoML forecast deployment is generated."] if task == "forecasting" and mode == "automl" else []
        ) + ["RAI dashboard components are a separate optional pipeline only for compatible custom "
             "tabular sklearn models, not forecasting or images. Match sklearn dependency versions, "
             "resolve registered model/train/test inputs, and review cohort sizes before submission."],
        "sources": [
            SCHEMAS + "pipelineJob.schema.json",
            SCHEMAS + TASK_SCHEMAS[task] + ".schema.json",
            "https://github.com/Azure/azureml-examples/blob/main/cli/jobs/pipelines/automl/"
            "cli-automl-classification-task-bankmarketing-pipeline/pipeline.yml",
        ],
        "files": files,
    }
    if lake is not None:
        manifest["lake"] = lake
    if image and mode == "automl":
        Path(files.pop("prepare_job")).unlink()
    if task == "forecasting" and mode == "automl":
        Path(files.pop("online_deployment")).unlink()
    files["manifest"] = str(output / "manifest.json")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return files


def _rai_pipeline(scenario: dict, runtime: dict) -> dict:
    """Actual public RAI components; run only after quality-gated registration."""
    prefix = "azureml://registries/azureml/components/rai_tabular_"
    def component(name):
        return prefix + name + "/versions/0.22.0"

    model = scenario.get("model_name", _name(scenario["name"], 24))
    constructor = "${{parent.jobs.construct.outputs.rai_insights_dashboard}}"
    return {
        "$schema": SCHEMAS + "pipelineJob.schema.json", "type": "pipeline",
        "tags": {**build_tags(scenario, runtime, mode="custom", engine="azureml"),
                 "lifecycle_stage": "responsible-ai"},
        "experiment_name": _name(scenario["name"], 80) + "-rai",
        "settings": {"default_compute": _asset(runtime["compute"]), "continue_on_step_failure": False},
        "inputs": {
            "model": {"type": "mlflow_model", "path": f"azureml:{model}:REPLACE_WITH_REGISTERED_VERSION"},
            "model_info": f"{model}:REPLACE_WITH_REGISTERED_VERSION",
            "train": {"type": "mltable", "path": "azureml://jobs/REPLACE_WITH_PREPARE_JOB/outputs/train/paths/"},
            "test": {"type": "mltable", "path": "azureml://jobs/REPLACE_WITH_PREPARE_JOB/outputs/test/paths/"},
        },
        "outputs": {"dashboard": {"type": "uri_folder"}, "ux_json": {"type": "uri_folder"}},
        "jobs": {
            "construct": {
                "type": "command", "component": component("insight_constructor"),
                "inputs": {
                    "title": scenario["name"] + " held-out model analysis",
                    "task_type": scenario["task"], "target_column_name": scenario["target"],
                    "model_input": "${{parent.inputs.model}}", "model_info": "${{parent.inputs.model_info}}",
                    "train_dataset": "${{parent.inputs.train}}", "test_dataset": "${{parent.inputs.test}}",
                    "categorical_column_names": json.dumps(scenario.get("categorical_features", [])),
                    "maximum_rows_for_test_dataset": 5000, "classes": "[]",
                },
            },
            "explain": {
                "type": "command", "component": component("explanation"),
                "inputs": {"rai_insights_dashboard": constructor, "comment": "Held-out feature explanations"},
            },
            "errors": {
                "type": "command", "component": component("erroranalysis"),
                "inputs": {"rai_insights_dashboard": constructor, "max_depth": 3},
            },
            "gather": {
                "type": "command", "component": component("insight_gather"),
                "inputs": {"constructor": constructor,
                           "insight_1": "${{parent.jobs.explain.outputs.explanation}}",
                           "insight_2": "${{parent.jobs.errors.outputs.error_analysis}}"},
                "outputs": {"dashboard": "${{parent.outputs.dashboard}}", "ux_json": "${{parent.outputs.ux_json}}"},
            },
        },
    }


def _client(runtime: dict):
    from azure.ai.ml import MLClient
    from azure.identity import AzureCliCredential, ManagedIdentityCredential

    from .config import validate_runtime

    validate_runtime(runtime)
    required = ("subscription_id", "resource_group", "workspace_name")
    missing = [key for key in required if not runtime.get(key)]
    if missing:
        raise ValueError(f"Missing Azure ML runtime settings: {', '.join(missing)}")
    mode = runtime.get("credential", "azure_cli")
    if mode == "azure_cli":
        credential = AzureCliCredential(tenant_id=runtime["tenant_id"])
    elif mode == "managed_identity":
        credential = ManagedIdentityCredential(client_id=runtime.get("managed_identity_client_id"))
    else:
        raise ValueError("runtime.credential must be azure_cli or managed_identity; no credential fallback is used")
    return MLClient(credential, *(runtime[key] for key in required))


def submit(job_path: Path, runtime: dict) -> str:
    """Submit the same YAML as CLI v2, using SDK v2 load_job (no SDK v1)."""
    from azure.ai.ml import load_job

    job_path = Path(job_path).resolve()
    if "REPLACE_WITH_" in job_path.read_text(encoding="utf-8"):
        raise ValueError("Resolve the REPLACE_WITH_ input/model placeholders before submission")
    job = load_job(source=str(job_path))
    from .tags import assert_scope
    assert_scope(job.tags or {}, runtime)
    submitted = _client(runtime).jobs.create_or_update(job)
    return submitted.name


def registration_definition(pipeline_job_name: str, runtime: dict, model_name: str) -> dict:
    """Create a v2 model definition only after evaluating the real job's gates."""
    from azure.ai.ml.constants import AssetTypes

    scope_tags(runtime, require=True)
    client = _client(runtime)
    job = client.jobs.get(pipeline_job_name)
    _check_registration_job(job.type, job.status, job.tags, getattr(job, "jobs", None), job.outputs)
    with tempfile.TemporaryDirectory(prefix="model-factory-registration-") as temporary:
        download = Path(temporary)
        client.jobs.download(name=pipeline_job_name, download_path=str(download), output_name="report")
        reports = list(download.rglob("quality-gate.json"))
        if len(reports) != 1:
            raise ValueError("Named pipeline report output must contain exactly one quality-gate.json")
        gate = json.loads(reports[0].read_text(encoding="utf-8"))
        if gate.get("passed") is not True:
            raise ValueError("Registration refused: the downloaded evaluation quality gate did not pass")
        lineage_path = reports[0].parent / "lineage.json"
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        if (lineage.get("model_output") != "model" or
                lineage.get("scenario") != (job.tags or {}).get("factory_scenario")):
            raise ValueError("Evaluation lineage does not match this factory pipeline")
        lake_tags = {key: value for key, value in (job.tags or {}).items() if key.startswith("factory_lake_")}
        if lake_tags:
            lake = lineage.get("lake", {}).get("config", {})
            if (any(lake.get(key) is None or lake.get(key) != lake_tags.get(f"factory_lake_{key}")
                    for key in LAKE_LINEAGE_FIELDS)
                    or lineage.get("task") != (job.tags or {}).get("factory_task")):
                raise ValueError("Evaluation lake lineage does not match this factory pipeline")
        model_tags = merge_registration_tags(job.tags or {}, lineage, runtime, pipeline_job_name)
    return {
        "$schema": SCHEMAS + "model.schema.json", "name": model_name,
        "path": f"azureml://jobs/{pipeline_job_name}/outputs/model/paths/",
        "type": AssetTypes.MLFLOW_MODEL,
        "tags": {**model_tags, "pipeline_job": pipeline_job_name, "quality_gate": "passed",
                 "factory_scenario": lineage["scenario"], "factory_mode": (job.tags or {}).get("factory_mode", ""),
                 **lake_tags, "factory_task": model_tags["task_type"]},
    }


def register(pipeline_job_name: str, runtime: dict, model_name: str) -> str:
    """SDK v2 registration using the same gated definition as CLI v2."""
    from azure.ai.ml.entities import Model

    definition = registration_definition(pipeline_job_name, runtime, model_name)
    definition.pop("$schema")
    model = _client(runtime).models.create_or_update(Model(**definition))
    return model.id


def _check_registration_job(
    kind: str, status: str, tags: dict | None, jobs: dict | None, outputs: dict | None
) -> None:
    if (kind != "pipeline" or status not in {"Completed", "Succeeded"}
            or (tags or {}).get("factory_quality_gate") != "evaluate"
            or "evaluate" not in (jobs or {})
            or not {"model", "report"}.issubset(outputs or {})):
        raise ValueError("Registration requires a successful (Completed/Succeeded) factory pipeline with an "
                         "evaluate quality gate and model/report outputs")
