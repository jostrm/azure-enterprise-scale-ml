"""Explicit notebook identity and separately invoked, evaluated MLflow registration."""

import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

import mlflow
from mlflow.tracking import MlflowClient
import yaml

from ml_model_factory.config import load_json
from ml_model_factory.tags import TAG_KEYS, assert_scope, build_tags, scope_tags


def _object(value, label):
    if value is None or value == "":
        return {}
    if isinstance(value, (str, Path)):
        text = str(value).strip()
        value = json.loads(text) if text.startswith(("{", "[")) else load_json(Path(text))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object or its file path")
    return dict(value)


def _merge(left, right):
    result = dict(left)
    for key, value in right.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        elif key in result and result[key] != value:
            raise ValueError(f"Conflicting lake {key} in model_context and lake_config")
        else:
            result[key] = value
    return result


def load_model_context(value="", lake_config=""):
    """Read JSON/path widgets without losing factory identity in raw lake_config."""
    context = _object(value, "model_context")
    if "lake" in context and not isinstance(context["lake"], dict):
        raise ValueError("Model context lake must be a JSON object")
    lake = _object(lake_config, "lake_config")
    if lake:
        context["lake"] = _merge(context.get("lake", {}), lake)
    scope_tags(context)
    return context


def register_evaluated(model_uri, model_name, scenario, context):
    """Register one evaluated runs:/<run-id>/model as a tagged candidate version.

    The caller selects the registry using MLflow's normal configuration and provides
    an explicit model name (including catalog/schema for Unity Catalog). No existing
    name is guessed, model aliases are not followed, and registered-model tags are
    never changed. A previously unused explicit name is created by MLflow.
    """
    match = re.fullmatch(r"runs:/([A-Za-z0-9][A-Za-z0-9_-]*)/model", model_uri) if isinstance(model_uri, str) else None
    if match is None:
        raise ValueError("Registration requires an immutable runs:/<run-id>/model URI")
    if (not isinstance(model_name, str) or not model_name.strip()
            or model_name != model_name.strip()
            or any(ord(char) < 32 for char in model_name)
            or any(char in model_name for char in "/\\?#@")):
        raise ValueError("Provide an explicit registered model name, not a URI or alias")
    context = load_model_context(context)
    expected = build_tags(scenario, context, engine="databricks", require_scope=True)
    run_id = match.group(1)
    client = MlflowClient()
    run = client.get_run(run_id)
    if run.info.run_id != run_id or run.info.status != "FINISHED":
        raise ValueError("Registration requires the selected MLflow run to be FINISHED")
    actual = {key: run.data.tags[key] for key in TAG_KEYS if key in run.data.tags}
    assert_scope(actual, context)
    if actual != expected:
        raise ValueError("Source run model tags differ from the selected scenario/context")

    # Keep review downloads isolated under the caller's working directory, not in
    # a shared system temporary directory or an existing local model artifact.
    review = Path.cwd() / f".model-registration-{uuid4().hex}"
    review.mkdir()
    try:
        def download(name):
            return Path(client.download_artifacts(run_id, name, dst_path=str(review)))

        gate = load_json(download("evaluation/quality-gate.json"))
        if not isinstance(gate, dict) or gate.get("passed") is not True:
            raise ValueError("Source run must have an explicitly passed evaluation quality gate")
        definition = yaml.safe_load(download("model/MLmodel").read_text(encoding="utf-8"))
        metadata = definition.get("metadata") if isinstance(definition, dict) else None
        factory = load_json(download("model/factory.json"))
        logged = load_json(download("model-tags.json"))
        if (not isinstance(metadata, dict) or metadata.get("model_factory_tags") != expected
                or not isinstance(factory, dict) or factory.get("model_tags") != expected
                or logged != expected):
            raise ValueError("Evaluated model metadata, factory and logged model tags must match the source run")
    finally:
        shutil.rmtree(review)

    return mlflow.register_model(model_uri, model_name, tags={
        **expected, "source_run_id": run_id, "lifecycle_status": "candidate", "quality_gate": "passed",
    })
