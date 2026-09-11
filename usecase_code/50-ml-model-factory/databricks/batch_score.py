# Databricks notebook source
"""Distributed Spark scoring for a pinned scalar-prediction MLflow pyfunc."""

# COMMAND ----------
dbutils.widgets.text("scenario_path", "")
dbutils.widgets.text("model_uri", "")
dbutils.widgets.text("input_table", "")
dbutils.widgets.text("output_table", "")
dbutils.widgets.text("prediction_type", "double")
dbutils.widgets.text("lake_config", "")

# COMMAND ----------
from pathlib import Path
from contextlib import nullcontext
import re
import mlflow
from pyspark.sql import functions as F
from ml_model_factory.config import load_json, validate_scenario

scenario = validate_scenario(load_json(Path(dbutils.widgets.get("scenario_path"))), require_dataset=True)
if scenario["task"].startswith("image_"):
    raise ValueError("This Spark scalar UDF adapter does not support image outputs")
model_uri = dbutils.widgets.get("model_uri")
if not (re.fullmatch(r"runs:/[a-fA-F0-9]{32}/[^?#]+", model_uri)
        or re.fullmatch(r"models:/[^/@?#]+/[1-9][0-9]*", model_uri)):
    raise ValueError("Use an immutable runs:/ URI or a numeric registered model version, not a mutable alias")
input_table, output_table = dbutils.widgets.get("input_table"), dbutils.widgets.get("output_table")
if not input_table or not output_table or input_table == output_table:
    raise ValueError("Provide different source/destination Unity Catalog table names")
lake_value = dbutils.widgets.get("lake_config")
lake = None
if lake_value:
    from lake_utils import lineage, load_lake, validate_model

    lake = load_lake(lake_value, scenario, serving="batch")
    validate_model(lake, model_uri)
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){2}", name)
           for name in (input_table, output_table)):
        raise ValueError("Lake table bindings require explicit catalog.schema.table names, not object paths")
features = list(scenario["features"])
if scenario["task"] == "forecasting":
    features = list(dict.fromkeys(features + scenario["forecast"].get("series_columns", []) + [scenario["forecast"]["time_column"]]))
prediction_type = dbutils.widgets.get("prediction_type")
if prediction_type not in {"double", "long", "string"}:
    raise ValueError("prediction_type must match the trained model: double, long, or string")
frame = spark.table(input_table)
if not set(features).issubset(frame.columns):
    raise ValueError("Scoring table is missing configured features")
predict = mlflow.pyfunc.spark_udf(spark, model_uri=model_uri, result_type=prediction_type, env_manager="local")
scored = frame.withColumn("prediction", predict(F.struct(*[F.col(f"`{name}`") for name in features])))
with mlflow.start_run() if lake else nullcontext():
    if lake:
        mlflow.log_dict(lineage(lake, input_table=input_table, output_table=output_table,
                                model_uri=model_uri), "lake-lineage.json")
        scored = scored.withColumn("lake_run_id", F.lit(lake.run_id))
    scored.withColumn("scored_at", F.current_timestamp()).withColumn("model_uri", F.lit(model_uri)).write.format("delta").mode("errorifexists").saveAsTable(output_table)
