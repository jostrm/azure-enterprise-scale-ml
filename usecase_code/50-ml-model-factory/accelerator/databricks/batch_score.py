# Databricks notebook source
"""Distributed Spark scoring for pinned MLflow pyfunc models."""

# COMMAND ----------
dbutils.widgets.text("scenario_path", "")
dbutils.widgets.text("model_uri", "")
dbutils.widgets.text("input_table", "")
dbutils.widgets.text("output_table", "")
dbutils.widgets.text("prediction_type", "double")
dbutils.widgets.text("lake_config", "")
dbutils.widgets.text("env_manager", "local")
dbutils.widgets.text("model_mode", "custom")

# COMMAND ----------
from pathlib import Path
from contextlib import nullcontext
import json
import re
import mlflow
from pyspark.sql import functions as F
from ml_model_factory.config import load_json, validate_scenario

scenario = validate_scenario(load_json(Path(dbutils.widgets.get("scenario_path"))), require_dataset=True)
model_mode = dbutils.widgets.get("model_mode") or "custom"
if scenario["task"] == "forecasting" and model_mode == "automl":
    raise ValueError("Databricks batch scoring refuses AutoML forecasting because it needs observed history; use the Azure ML scoring route")
model_uri = dbutils.widgets.get("model_uri")
if not (re.fullmatch(r"runs:/[a-fA-F0-9]{32}/[^?#]+", model_uri)
        or re.fullmatch(r"models:/[^/@?#]+/[1-9][0-9]*", model_uri)):
    raise ValueError("Use an immutable runs:/ URI or a numeric registered model version, not a mutable alias")
input_table, output_table = dbutils.widgets.get("input_table"), dbutils.widgets.get("output_table")
if not input_table or not output_table or input_table == output_table:
    raise ValueError("Provide different source/destination Unity Catalog table names")
env_manager = dbutils.widgets.get("env_manager") or "local"
if env_manager not in {"local", "virtualenv", "conda"}:
    raise ValueError("env_manager must be local, virtualenv or conda")
lake_value = dbutils.widgets.get("lake_config")
lake = None
if lake_value:
    from lake_utils import lineage, load_lake, validate_model

    lake = load_lake(lake_value, scenario, serving="batch")
    validate_model(lake, model_uri)
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){2}", name)
           for name in (input_table, output_table)):
        raise ValueError("Lake table bindings require explicit catalog.schema.table names, not object paths")
if scenario["task"].startswith("image_"):
    features, prediction_type = ["image_base64"], "string"
elif scenario["task"] == "forecasting":
    forecast = scenario["forecast"]
    features = list(dict.fromkeys(scenario["features"] + forecast.get("series_columns", []) + [forecast["time_column"]]))
else:
    features = list(scenario["features"])
prediction_type = dbutils.widgets.get("prediction_type") if not scenario["task"].startswith("image_") else "string"
if prediction_type not in {"double", "long", "string"}:
    raise ValueError("prediction_type must match the trained model: double, long, or string")
frame = spark.table(input_table)
if not set(features).issubset(frame.columns):
    raise ValueError("Scoring table is missing configured features")
predict = mlflow.pyfunc.spark_udf(spark, model_uri=model_uri, result_type=prediction_type, env_manager=env_manager)
scored = frame.withColumn("prediction", predict(F.struct(*[F.col(f"`{name}`") for name in features])))
with mlflow.start_run() if lake else nullcontext():
    if lake:
        mlflow.log_dict(lineage(lake, input_table=input_table, output_table=output_table,
                                model_uri=model_uri, env_manager=env_manager), "lake-lineage.json")
        scored = scored.withColumn("lake_run_id", F.lit(lake.run_id))
    final = scored.withColumn("scored_at", F.current_timestamp()).withColumn("model_uri", F.lit(model_uri))
    rows = int(final.count())
    final.write.format("delta").mode("errorifexists").saveAsTable(output_table)
receipt = {"output_table": output_table, "model_uri": model_uri, "rows": rows}
try:
    dbutils.jobs.taskValues.set(key="output_table", value=output_table)
    dbutils.jobs.taskValues.set(key="rows", value=str(rows))
except Exception:
    pass
dbutils.notebook.exit(json.dumps(receipt, allow_nan=False))
