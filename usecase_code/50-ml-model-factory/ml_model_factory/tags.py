"""Small, string-only model identity contract shared by SDK v2, CLI v2 and MLflow."""

import re
from pathlib import Path

import yaml

from .config import TASKS, load_json, write_json
from .lake import LakeLayout, identifier


TAG_SCHEMA = "ml-model-factory/v1"
SCOPE_KEYS = ("aifactory", "project", "environment")
TAG_KEYS = (
    "tag_schema", *SCOPE_KEYS, "training_environment", "use_case", "task_type",
    "training_engine", "training_mode", "dataset", "data_version", "snapshot_id", "run_id",
)


def _agree(name, values):
    present = [str(value) for value in values if value is not None and value != ""]
    if len(set(present)) > 1:
        raise ValueError(f"Conflicting {name} in model context and lake layout")
    return present[0] if present else None


def scope_tags(context: dict | None = None, require: bool = False) -> dict[str, str]:
    context = {} if context is None else context
    if not isinstance(context, dict):
        raise ValueError("Model context must be a JSON object")
    lake = context.get("lake", {})
    if not isinstance(lake, dict):
        raise ValueError("Model context lake must be a JSON object")
    environment = context.get("environment")
    if environment and str(environment).startswith("azureml:"):
        environment = None
    candidates = {
        "aifactory": [context.get("aifactory"), lake.get("aifactory")],
        "project": [context.get("project"), context.get("project_number"), lake.get("project")],
        "environment": [environment, context.get("environment_name"),
                        context.get("target_environment"), lake.get("environment")],
    }
    result = {key: selected for key, values in candidates.items() if (selected := _agree(key, values)) is not None}
    if result.get("aifactory"):
        identifier(result["aifactory"], "aifactory")
    if "project" in result and not re.fullmatch(r"\d{3}", result["project"]):
        raise ValueError("Model project tag must match the lake's three-digit project identifier")
    if "environment" in result and result["environment"] not in ("dev", "test", "prod"):
        raise ValueError("Model environment tag must be dev, test or prod, not an ML environment asset")
    if require and set(result) != set(SCOPE_KEYS):
        raise ValueError("Model registration requires explicit aifactory, project and environment_name (or matching lake scope)")
    return result


def build_tags(scenario: dict, context: dict | None = None, mode: str = "custom",
               engine: str = "local", require_scope: bool = False) -> dict[str, str]:
    context = {} if context is None else context
    scope = scope_tags(context, require=require_scope)
    if scenario.get("task") not in TASKS:
        raise ValueError("An explicit supported task is required for model tags")
    if mode not in ("custom", "automl") or engine not in ("local", "azureml", "databricks"):
        raise ValueError("Invalid model training engine or mode")
    scenario_name = identifier(scenario.get("name"), "use_case")
    lake = context.get("lake", {})
    # A standalone lake configuration is also accepted by local workflows.
    if not lake and "dataset" in context and "snapshot_id" in context:
        lake = context
    result = {
        "tag_schema": TAG_SCHEMA, **scope, "use_case": scenario_name, "task_type": scenario["task"],
        "training_engine": engine, "training_mode": mode,
    }
    if scope.get("environment"):
        result["training_environment"] = scope["environment"]
    if lake:
        layout = LakeLayout.from_config(lake, scenario)
        if layout.use_case != scenario_name:
            raise ValueError("Model use_case must match the scenario and lake use-case folder")
        for key in ("project", "environment"):
            if key in scope and scope[key] != getattr(layout, key):
                raise ValueError(f"Model {key} disagrees with lake path")
        result.update(project=layout.project, environment=layout.environment,
                      training_environment=layout.environment, dataset=layout.dataset,
                      data_version=layout.data_version, snapshot_id=layout.snapshot_id, run_id=layout.run_id)
    else:
        dataset = scenario.get("dataset", {})
        if dataset.get("slug"):
            result["dataset"] = f"{dataset.get('provider', 'kaggle')}:{dataset['slug']}"
        if dataset.get("version") is not None:
            result["data_version"] = str(dataset["version"])
    return validate_tags(result)


def validate_tags(tags: dict, require_scope: bool = False) -> dict[str, str]:
    if not isinstance(tags, dict) or tags.get("tag_schema") != TAG_SCHEMA:
        raise ValueError("Missing or unsupported model tag_schema")
    for key, value in tags.items():
        if (not isinstance(key, str) or not isinstance(value, str) or not value
                or len(key) > 128 or len(value) > 256 or any(ord(char) < 32 for char in value)):
            raise ValueError("Model tags must be nonempty bounded strings without control characters")
    scope_tags(tags, require=require_scope)
    return dict(tags)


def assert_scope(tags: dict, context: dict):
    wanted = scope_tags(context, require=True)
    actual = scope_tags(tags, require=True)
    if wanted != actual:
        raise ValueError("Registered model factory/project/environment differs from the selected target")


def stamp_model(model_path: Path, tags: dict) -> None:
    """Write metadata only before publishing an immutable local model artifact."""
    tags = validate_tags(tags)
    model_path = Path(model_path)
    if (model_path.parent / "_SUCCESS.json").exists():
        raise ValueError("Do not change tags inside an already committed lake run")
    mlmodel = model_path / "MLmodel"
    document = yaml.safe_load(mlmodel.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Expected an MLflow model definition")
    metadata = document.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("MLflow metadata must be an object")
    metadata["model_factory_tags"] = tags
    mlmodel.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    factory_path = model_path / "factory.json"
    factory = load_json(factory_path) if factory_path.exists() else {}
    factory["model_tags"] = tags
    write_json(factory_path, factory)


def merge_registration_tags(job_tags: dict, lineage: dict, runtime: dict, job_name: str) -> dict[str, str]:
    """Keep origin tags; never relabel a model into a different target environment."""
    scope = scope_tags(runtime, require=True)
    tagged = {key: job_tags[key] for key in TAG_KEYS if key in job_tags}
    if tagged.get("tag_schema"):
        validate_tags(tagged, require_scope=True)
        assert_scope(tagged, runtime)
        if lineage.get("model_tags") != tagged:
            raise ValueError("Evaluation model tags do not match the training job")
    else:
        # Legacy factory jobs can be registered with explicit scope, but their task
        # and mode must still come from the checked training/evaluation lineage.
        task = lineage.get("task") or job_tags.get("factory_task")
        mode = lineage.get("mode") or job_tags.get("factory_mode")
        if task not in TASKS or mode not in ("custom", "automl"):
            raise ValueError("Legacy model registration requires task and mode in training lineage")
        tagged = {
            "tag_schema": TAG_SCHEMA, **scope, "training_environment": scope["environment"],
            "use_case": lineage["scenario"], "task_type": task,
            "training_engine": "azureml", "training_mode": mode,
        }
    if (tagged["use_case"] != lineage["scenario"]
            or tagged["training_mode"] != job_tags.get("factory_mode")
            or tagged["task_type"] != (lineage.get("task") or job_tags.get("factory_task"))):
        raise ValueError("Model task/use-case/mode tags disagree with evaluation lineage")
    lake = lineage.get("lake", {}).get("config", {})
    if lake:
        if lake.get("aifactory") is not None and lake["aifactory"] != tagged["aifactory"]:
            raise ValueError("Model aifactory tag disagrees with evaluated lake lineage")
        for key in ("project", "environment", "use_case", "dataset", "data_version", "snapshot_id", "run_id"):
            if key in tagged and str(lake.get(key)) != tagged[key]:
                raise ValueError(f"Model {key} tag disagrees with evaluated lake lineage")
    return validate_tags({
        **tagged, "source_run_id": job_name,
        "source_resource_id": f"/subscriptions/{runtime['subscription_id']}/resourceGroups/{runtime['resource_group']}"
                              f"/providers/Microsoft.MachineLearningServices/workspaces/{runtime['workspace_name']}",
        "lifecycle_status": "candidate", "quality_gate": "passed",
    }, require_scope=True)
