# Databricks notebook source
"""Event Hubs Kafka -> Spark Structured Streaming -> Delta, using secrets.

Image events carry an image_base64 payload; Event Hubs per-event limits make URI
reference designs preferable for large images. Checkpoints belong to a stable
query, not a model/run; incompatible query/schema changes need a new pipeline version.
"""

# COMMAND ----------
for name in ("scenario_path", "model_uri", "eventhubs_namespace", "eventhub_name",
             "secret_scope", "connection_string_secret", "checkpoint", "output_table", "payload_schema_json"):
    dbutils.widgets.text(name, "")
dbutils.widgets.text("prediction_type", "double")
dbutils.widgets.text("trigger_interval", "30 seconds")
dbutils.widgets.text("lake_config", "")
dbutils.widgets.text("checkpoint_root", "")
dbutils.widgets.text("env_manager", "local")
dbutils.widgets.text("model_mode", "custom")

# COMMAND ----------
import json
import re
from pathlib import Path
from contextlib import nullcontext
import mlflow
from pyspark.sql import functions as F, types as T
from ml_model_factory.config import load_json, validate_scenario

scenario = validate_scenario(load_json(Path(dbutils.widgets.get("scenario_path"))), require_dataset=True)
if scenario["task"] not in {"classification", "regression", "forecasting", "image_classification", "image_classification_multilabel", "image_object_detection", "image_instance_segmentation"}:
    raise ValueError("Unsupported streaming task")
if scenario["task"] == "forecasting" and (dbutils.widgets.get("model_mode") or "custom") == "automl":
    raise ValueError("Databricks streaming refuses AutoML forecasting because it needs observed history; use the Azure ML scoring route")
namespace, topic = dbutils.widgets.get("eventhubs_namespace"), dbutils.widgets.get("eventhub_name")
if not re.fullmatch(r"[a-zA-Z0-9-]+", namespace) or not re.fullmatch(r"[A-Za-z0-9._-]{1,256}", topic):
    raise ValueError("Set an Event Hubs namespace name and event hub topic")
checkpoint, destination = dbutils.widgets.get("checkpoint"), dbutils.widgets.get("output_table")
model_uri = dbutils.widgets.get("model_uri")
if not (re.fullmatch(r"runs:/[a-fA-F0-9]{32}/[^?#]+", model_uri)
        or re.fullmatch(r"models:/[^/@?#]+/[1-9][0-9]*", model_uri)):
    raise ValueError("Pin a model version/run for reproducible replay")
env_manager = dbutils.widgets.get("env_manager") or "local"
if env_manager not in {"local", "virtualenv", "conda"}:
    raise ValueError("env_manager must be local, virtualenv or conda")
lake_value = dbutils.widgets.get("lake_config")
lake = None
if lake_value:
    from lake_utils import checkpoint_path, lineage, load_lake, validate_model

    lake = load_lake(lake_value, scenario, serving="streaming")
    validate_model(lake, model_uri)
    expected_checkpoint = checkpoint_path(lake, dbutils.widgets.get("checkpoint_root"), spark=spark)
    if checkpoint and checkpoint != expected_checkpoint:
        raise ValueError("With lake_config, checkpoint must be empty or equal the stable contract checkpoint")
    checkpoint = expected_checkpoint
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){2}", destination):
        raise ValueError("output_table must be catalog.schema.table, not a lake object path")
if ("?" in checkpoint or "#" in checkpoint
        or not checkpoint.startswith(("wasbs://", "abfss://", "/Volumes/")) or not destination):
    raise ValueError("A durable credential-free checkpoint and destination Delta table are required")
schema = T.StructType.fromJson(json.loads(dbutils.widgets.get("payload_schema_json")))
if scenario["task"].startswith("image_"):
    features, result_type = ["image_base64"], "string"
elif scenario["task"] == "forecasting":
    forecast = scenario["forecast"]
    features = list(dict.fromkeys(scenario["features"] + forecast.get("series_columns", []) + [forecast["time_column"]]))
    result_type = dbutils.widgets.get("prediction_type")
else:
    features = list(scenario["features"])
    result_type = dbutils.widgets.get("prediction_type")
required = set(features) | {"event_id", "event_time"}
if not required.issubset(schema.fieldNames()) or not isinstance(schema["event_time"].dataType, T.TimestampType):
    raise ValueError("Payload schema must include features, event_id and timestamp event_time")
if result_type not in {"double", "long", "string"}:
    raise ValueError("prediction_type must be double, long or string")
connection = dbutils.secrets.get(dbutils.widgets.get("secret_scope"), dbutils.widgets.get("connection_string_secret"))
connection = connection.replace("\\", "\\\\").replace('"', '\\"')
jaas = f'org.apache.kafka.common.security.plain.PlainLoginModule required username="$ConnectionString" password="{connection}";'
events = (
    spark.readStream.format("kafka")
    .option("kafka.bootstrap.servers", f"{namespace}.servicebus.windows.net:9093")
    .option("subscribe", topic)
    .option("kafka.security.protocol", "SASL_SSL")
    .option("kafka.sasl.mechanism", "PLAIN")
    .option("kafka.sasl.jaas.config", jaas)
    .option("startingOffsets", "latest")
    .option("failOnDataLoss", "true")
    .load()
)
decoded = events.select(
    F.from_json(F.col("value").cast("string"), schema, {"mode": "FAILFAST"}).alias("event"),
    F.col("timestamp").alias("broker_timestamp"),
).select("event.*", "broker_timestamp")
valid = decoded.filter(F.col("event_id").isNotNull() & F.col("event_time").isNotNull())
deduplicated = valid.withWatermark("event_time", "10 minutes").dropDuplicatesWithinWatermark(["event_id"])
predict = mlflow.pyfunc.spark_udf(spark, model_uri=model_uri, result_type=result_type, env_manager=env_manager)
scored = deduplicated.withColumn("prediction", predict(F.struct(*[F.col(f"`{name}`") for name in features])))
with mlflow.start_run() if lake else nullcontext():
    if lake:
        mlflow.log_dict(lineage(
            lake, source=f"eventhubs://{namespace}/{topic}", output_table=destination,
            checkpoint=checkpoint, model_uri=model_uri, env_manager=env_manager,
            validation="Malformed JSON fails; null event IDs/times are filtered, not quarantined",
        ), "lake-lineage.json")
        scored = scored.withColumn("lake_run_id", F.lit(lake.run_id))
    query = (
        scored.withColumn("model_uri", F.lit(model_uri)).withColumn("scored_at", F.current_timestamp())
        .writeStream.format("delta").outputMode("append")
        .option("checkpointLocation", checkpoint)
        .trigger(processingTime=dbutils.widgets.get("trigger_interval"))
        .toTable(destination)
    )
    query.awaitTermination()
