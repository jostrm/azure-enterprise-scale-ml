"""MLflow inference contracts and explicit, quality-gated endpoint deployment."""

import json
from pathlib import Path

import yaml


def forecast_predictions(model_path: Path, future, history, scenario: dict):
    """Use the documented sklearn AutoML forecast API, never generic predict()."""
    import mlflow.sklearn
    import numpy as np
    import pandas as pd

    from .evaluation import prediction_vector

    definition = yaml.safe_load((Path(model_path) / "MLmodel").read_text(encoding="utf-8"))
    if "sklearn" not in definition.get("flavors", {}):
        raise ValueError("AutoML forecasting evaluation requires sklearn flavor; TCN needs a task-specific adapter")
    model = mlflow.sklearn.load_model(str(model_path))
    if not callable(getattr(model, "forecast", None)):
        raise ValueError("AutoML forecasting model must expose forecast(); generic predict() is not supported")
    forecast = scenario["forecast"]
    columns = list(dict.fromkeys(
        scenario["features"] + forecast.get("series_columns", []) + [forecast["time_column"]]
    ))
    query = pd.concat([history.loc[:, columns], future.loc[:, columns]], ignore_index=True)
    query[forecast["time_column"]] = pd.to_datetime(query[forecast["time_column"]], errors="raise")
    observed = np.concatenate([history[scenario["target"]].to_numpy(dtype=float), np.full(len(future), np.nan)])
    result = model.forecast(query, y_query=observed, ignore_data_errors=False)
    if not isinstance(result, tuple) or len(result) != 2:
        raise ValueError("Expected AutoML forecast() to return (predictions, aligned_data)")
    predictions = prediction_vector(result[0], len(query))
    # Forecast models can sort rows by series and time. Validate the returned keys
    # and join rather than treating the last N predictions as held-out rows.
    aligned = result[1]
    keys = forecast.get("series_columns", []) + [forecast["time_column"]]
    if not isinstance(aligned, pd.DataFrame):
        raise ValueError("AutoML forecast() did not return an alignment dataframe")
    if not set(keys).issubset(aligned.columns):
        aligned = aligned.reset_index()
    if not set(keys).issubset(aligned.columns):
        raise ValueError("Forecast output is missing series/time keys; cannot safely align held-out predictions")
    aligned = aligned.loc[:, keys].copy()
    aligned[forecast["time_column"]] = pd.to_datetime(aligned[forecast["time_column"]])
    aligned["_factory_prediction"] = predictions
    if aligned.duplicated(keys).any():
        raise ValueError("Forecast output has duplicate series/time keys")
    requested = future.loc[:, keys].copy()
    requested[forecast["time_column"]] = pd.to_datetime(requested[forecast["time_column"]])
    merged = requested.merge(aligned, on=keys, how="left", validate="one_to_one", sort=False)
    values = merged["_factory_prediction"].to_numpy()
    if not np.isfinite(values).all():
        raise ValueError("Forecast output does not contain a finite prediction for every held-out row")
    return values


def deploy(runtime: dict, bundle: Path, model_id: str, kind: str = "online") -> str:
    """Create/update a no-code MLflow deployment; online traffic changes last."""
    from azure.ai.ml import (
        load_batch_endpoint,
        load_online_deployment, load_online_endpoint,
    )

    from .azureml import _client

    if kind not in {"online", "batch"}:
        raise ValueError("kind must be 'online' or 'batch'")
    client = _client(runtime)
    name, version = _model_name_version(model_id)
    registered = client.models.get(name=name, version=version)
    if (registered.type != "mlflow_model" or
            (registered.tags or {}).get("quality_gate") != "passed" or
            not (registered.tags or {}).get("pipeline_job")):
        raise ValueError("Deploy only MLflow models registered from a passing factory pipeline")
    bundle = Path(bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if name != manifest["model_name"]:
        raise ValueError("Registered model name does not match this rendered bundle")
    if registered.tags.get("factory_scenario") != manifest["scenario_name"]:
        raise ValueError("Registered model scenario does not match this rendered bundle")
    if registered.tags.get("factory_mode") != manifest["mode"]:
        raise ValueError("Registered model training mode does not match this rendered bundle")
    deployment_path = bundle / f"{kind}-deployment.yml"
    if not deployment_path.is_file():
        raise ValueError(f"{kind} serving is not supported for this task/mode; inspect manifest limitations")
    if kind == "online":
        endpoint = load_online_endpoint(source=str(bundle / "online-endpoint.yml"))
        deployment = load_online_deployment(source=str(deployment_path))
        deployment.model = registered.id
        client.online_endpoints.begin_create_or_update(endpoint).result()
        client.online_deployments.begin_create_or_update(deployment).result()
        endpoint = client.online_endpoints.get(endpoint.name)
        endpoint.traffic = {deployment.name: 100}
        client.online_endpoints.begin_create_or_update(endpoint).result()
    else:
        endpoint = load_batch_endpoint(source=str(bundle / "batch-endpoint.yml"))
        deployment = load_model_batch_deployment(deployment_path)
        deployment.model = registered.id
        client.batch_endpoints.begin_create_or_update(endpoint).result()
        client.batch_deployments.begin_create_or_update(deployment).result()
        endpoint = client.batch_endpoints.get(endpoint.name)
        endpoint.defaults.deployment_name = deployment.name
        client.batch_endpoints.begin_create_or_update(endpoint).result()
    return endpoint.name


def load_model_batch_deployment(source: Path):
    """SDK's legacy load_batch_deployment does not accept model settings YAML."""
    from azure.ai.ml.entities import (
        BatchRetrySettings, ModelBatchDeployment, ModelBatchDeploymentSettings, ResourceConfiguration,
    )

    document = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
    document.pop("$schema", None)
    if document.pop("type", None) != "model":
        raise ValueError("Expected a modelBatchDeployment definition")
    settings = document.pop("settings")
    if "retry_settings" in settings:
        settings["retry_settings"] = BatchRetrySettings(**settings["retry_settings"])
    resources = ResourceConfiguration(**document.pop("resources"))
    return ModelBatchDeployment(
        **document, settings=ModelBatchDeploymentSettings(**settings), resources=resources,
    )


def _model_name_version(value: str) -> tuple[str, str]:
    import re

    reference = re.fullmatch(r"azureml:([^:/]+):([^:/@]+)", value)
    arm = re.search(r"/models/([^/]+)/versions/([^/]+)$", value)
    if not (reference or arm):
        raise ValueError("Use an immutable azureml:name:version or model ARM ID, never @latest")
    return (reference or arm).groups()
