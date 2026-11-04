# Databricks notebook source
"""Register an evaluated MLflow run in UC and create/update a Model Serving endpoint."""

# COMMAND ----------
for name, default in (("scenario_path", ""), ("model_uri", ""), ("registered_model_name", ""),
                      ("endpoint_name", ""), ("workload_size", "Small"), ("scale_to_zero", "true"),
                      ("model_context", ""), ("lake_config", ""), ("sample_request", "")):
    dbutils.widgets.text(name, default)

# COMMAND ----------
import json
from pathlib import Path
import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, ResourceDoesNotExist
from databricks.sdk.service.serving import DataframeSplitInput, EndpointCoreConfigInput, Route, ServedEntityInput, TrafficConfig
from ml_model_factory.config import boolean, load_json, validate_scenario
from model_tags import load_model_context, register_evaluated

scenario = validate_scenario(load_json(Path(dbutils.widgets.get("scenario_path"))), require_dataset=True)
model_uri = dbutils.widgets.get("model_uri")
model_name = dbutils.widgets.get("registered_model_name")
endpoint = dbutils.widgets.get("endpoint_name")
workload_size = dbutils.widgets.get("workload_size") or "Small"
scale_to_zero = boolean(dbutils.widgets.get("scale_to_zero") or "true")
context = load_model_context(dbutils.widgets.get("model_context"), dbutils.widgets.get("lake_config"))
if model_name.count(".") != 2:
    raise ValueError("registered_model_name must be a Unity Catalog three-level name catalog.schema.model")
if not endpoint or any(char in endpoint for char in " ?#/@\\"):
    raise ValueError("endpoint_name must be explicit and credential-free")
mlflow.set_registry_uri("databricks-uc")
version = register_evaluated(model_uri, model_name, scenario, context)
version_number = str(version.version)
served_name = (model_name.rsplit(".", 1)[-1] + "-" + version_number).replace("_", "-")
entity = ServedEntityInput(
    name=served_name, entity_name=model_name, entity_version=version_number,
    workload_size=workload_size, scale_to_zero_enabled=scale_to_zero,
)
traffic = TrafficConfig(routes=[Route(served_entity_name=served_name, traffic_percentage=100)])
client = WorkspaceClient()
try:
    current = client.serving_endpoints.get(endpoint)
    state = "updated"
except (NotFound, ResourceDoesNotExist):
    current = None
if current is None:
    detail = client.serving_endpoints.create_and_wait(
        name=endpoint,
        config=EndpointCoreConfigInput(name=endpoint, served_entities=[entity], traffic_config=traffic),
    )
    state = "created"
else:
    detail = client.serving_endpoints.update_config_and_wait(
        name=endpoint, served_entities=[entity], traffic_config=traffic,
    )
query_result = None
sample = dbutils.widgets.get("sample_request")
if sample:
    payload = json.loads(sample)
    if "dataframe_split" not in payload:
        raise ValueError("sample_request must contain dataframe_split JSON for a smoke query")
    query_result = client.serving_endpoints.query(endpoint, dataframe_split=DataframeSplitInput.from_dict(payload["dataframe_split"]))
receipt = {"endpoint": endpoint, "model": model_name, "version": version_number, "state": state}
if query_result is not None:
    receipt["smoke_query"] = "completed"
try:
    dbutils.jobs.taskValues.set(key="endpoint", value=endpoint)
    dbutils.jobs.taskValues.set(key="model_version", value=version_number)
    dbutils.jobs.taskValues.set(key="state", value=state)
except Exception:
    pass
dbutils.notebook.exit(json.dumps(receipt, allow_nan=False))
