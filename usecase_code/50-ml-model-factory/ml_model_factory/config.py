"""Configuration validation without Azure credentials or SDK imports."""

import json
import math
import re
from pathlib import Path
from uuid import UUID


TASKS = {
    "classification", "regression", "forecasting", "image_classification",
    "image_classification_multilabel", "image_object_detection",
    "image_instance_segmentation",
}


def load_json(path: Path) -> dict:
    with Path(path).open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def boolean(value) -> bool:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError(f"Expected a boolean or 'true'/'false', got {value!r}")


def safe_relative(value: str) -> Path:
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    if not normalized or normalized.startswith("/") or path.is_absolute() or ":" in normalized or ".." in path.parts:
        raise ValueError(f"Expected a safe dataset-relative path, got {value!r}")
    return path


def validate_scenario(value: dict, *, require_dataset: bool = False) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,62}", value.get("name", "")):
        raise ValueError("Scenario name must be a lowercase identifier of 2-63 characters")
    task = value.get("task")
    if task not in TASKS:
        raise ValueError(f"Unsupported task: {task!r}")
    dataset = value.get("dataset", {})
    if dataset.get("provider") != "kaggle":
        raise ValueError("Training dataset provider must be 'kaggle'")
    if dataset.get("kind") not in ("dataset", "competition"):
        raise ValueError("dataset.kind must be 'dataset' or 'competition'")
    if dataset.get("file"):
        safe_relative(dataset["file"])
    if require_dataset:
        if dataset.get("status") in ("required-selection", "license-review", "requires-license-review"):
            raise ValueError(f"Dataset {dataset.get('status')}: {dataset.get('notes', 'Resolve dataset selection and license before ingestion')}")
        slug = dataset.get("slug", "")
        pattern = r"[\w-]+/[\w-]+" if dataset["kind"] == "dataset" else r"[\w-]+"
        if not re.fullmatch(pattern, slug):
            raise ValueError("Select a verified Kaggle dataset/competition slug before ingestion")
        if not dataset.get("file"):
            raise ValueError("Set dataset.file to the training file or image directory")
        if dataset["kind"] == "dataset" and not isinstance(dataset.get("version"), int):
            raise ValueError("Pin dataset.version to a Kaggle dataset version number")
        if dataset.get("version") is not None and dataset["version"] < 1:
            raise ValueError("dataset.version must be positive")
    if not task.startswith("image_"):
        if not value.get("target"):
            raise ValueError("A target column is required")
        features = value.get("features", [])
        if not features or len(features) != len(set(features)):
            raise ValueError("Provide a nonempty list of unique feature columns")
        if value["target"] in features:
            raise ValueError("The target column must not be an input feature")
        if not set(value.get("categorical_features", [])).issubset(features):
            raise ValueError("categorical_features must be a subset of features")
    split = value.get("split", {})
    test = split.get("test_size", 0.2)
    validation = split.get("validation_size", 0.2)
    if not 0 < test < 1 or not 0 < validation < 1 or test + validation >= 1:
        raise ValueError("test_size and validation_size must be positive and total less than one")
    group = split.get("group_column")
    if group is not None:
        if not isinstance(group, str) or not group or group == value.get("target"):
            raise ValueError("split.group_column must identify an entity column, not the target")
        if task == "forecasting" or task.startswith("image_"):
            raise ValueError("group_column is for tabular classification/regression; use temporal or image split rules")
    if task == "forecasting":
        forecast = value.get("forecast", {})
        if not forecast.get("time_column") or not forecast.get("frequency"):
            raise ValueError("Forecasting requires a time_column and frequency")
        if not isinstance(forecast.get("horizon"), int) or forecast["horizon"] < 1:
            raise ValueError("forecast.horizon must be a positive integer")
    for metric, limit in value.get("quality", {}).items():
        if not metric.startswith(("min_", "max_")) or not isinstance(limit, (int, float)) or not math.isfinite(limit):
            raise ValueError(f"Invalid quality gate {metric!r}")
    return value


def validate_runtime(value: dict) -> dict:
    for field in ("subscription_id", "tenant_id"):
        try:
            UUID(value.get(field, ""))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"runtime.{field} must be a resolved UUID") from exc
    for field in ("resource_group", "workspace_name", "compute"):
        setting = value.get(field)
        if not isinstance(setting, str) or not setting.strip() or "<" in setting or "${" in setting:
            raise ValueError(f"runtime.{field} must name an existing resource")
    from .tags import scope_tags
    scope_tags(value)
    return value


def quality_gate(metrics: dict, limits: dict) -> None:
    failures = []
    for gate, limit in limits.items():
        direction, metric = gate.split("_", 1)
        actual = metrics.get(metric)
        if actual is None or not math.isfinite(actual):
            failures.append(f"{metric} was not produced")
        elif direction == "min" and actual < limit or direction == "max" and actual > limit:
            failures.append(f"{metric}={actual:.6g} violates {gate}={limit}")
    if failures:
        raise ValueError("Model quality gate failed: " + "; ".join(failures))
