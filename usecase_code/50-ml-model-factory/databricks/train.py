# Databricks notebook source
"""Train/evaluate a Kaggle-backed tabular scenario using the installed factory wheel."""

# COMMAND ----------
dbutils.widgets.text("scenario_path", "")
dbutils.widgets.text("input_path", "")
dbutils.widgets.text("artifact_root", "")
dbutils.widgets.text("experiment_path", "")
dbutils.widgets.text("max_rows", "100000")
dbutils.widgets.text("lake_config", "")
dbutils.widgets.text("model_context", "")

# COMMAND ----------
from pathlib import Path
import mlflow
from ml_model_factory.config import load_json, validate_scenario
from ml_model_factory.data import prepare
from ml_model_factory.training import train
from ml_model_factory.evaluation import evaluate
from ml_model_factory.tags import build_tags, stamp_model
from model_tags import load_model_context

scenario = validate_scenario(load_json(Path(dbutils.widgets.get("scenario_path"))), require_dataset=True)
if scenario["task"] not in {"classification", "regression", "forecasting"}:
    raise ValueError("This Databricks training notebook supports tabular/forecasting tasks only")
source_value = dbutils.widgets.get("input_path")
root_value = dbutils.widgets.get("artifact_root")
experiment = dbutils.widgets.get("experiment_path")
max_rows = int(dbutils.widgets.get("max_rows"))
lake_value = dbutils.widgets.get("lake_config")
context = load_model_context(dbutils.widgets.get("model_context"), lake_value)
model_tags = build_tags(scenario, context, engine="databricks")
lake = None
if lake_value:
    from lake_utils import landing_file, lineage, load_lake

    lake = load_lake(lake_value, scenario)
    expected_source = landing_file(lake, scenario)
    if source_value and source_value != expected_source:
        raise ValueError("With lake_config, input_path must be empty or the exact configured landing file")
    source_value = expected_source
if (not root_value.startswith(("/Volumes/", "/local_disk0/")) or "?" in root_value or "#" in root_value
        or not experiment or max_rows < 1):
    raise ValueError("Set a writable /Volumes or /local_disk0 artifact root, an existing experiment, and positive max_rows")
remote = source_value.startswith(("wasbs://", "abfss://"))
if "?" in source_value or "#" in source_value:
    raise ValueError("Use configured storage credentials, not a token-bearing input URI")
source = Path(source_value)
if not remote and not source.is_file():
    raise ValueError("input_path must be the labeled CSV/Parquet exported by reviewed Kaggle ingestion")
mlflow.set_experiment(experiment)
with mlflow.start_run() as run:
    mlflow.set_tags(model_tags)
    mlflow.log_dict(model_tags, "model-tags.json")
    root = Path(root_value).joinpath(*lake.key("training_run").split("/")) if lake else Path(root_value) / run.info.run_id
    if lake:
        root.mkdir(parents=True, exist_ok=False)
        mlflow.log_dict(lineage(
            lake, input_file=source_value, artifacts=str(root),
            model=f"runs:/{run.info.run_id}/model",
            evaluation=f"runs:/{run.info.run_id}/evaluation",
            preparation="Per-run driver preparation; no immutable snapshot or silver publication",
        ), "lake-lineage.json")
    prepared, model, evaluation = root / "prepared", root / "model", root / "evaluation"
    if remote:
        extension = source_value.rsplit(".", 1)[-1].lower()
        if extension not in {"csv", "parquet"}:
            raise ValueError("Remote input must identify a CSV or Parquet file")
        reader = spark.read
        if extension == "csv":
            reader = reader.option("header", True).option("inferSchema", True)
        rows = reader.format(extension).load(source_value).limit(max_rows + 1).toPandas()
        if len(rows) > max_rows:
            raise ValueError("Input exceeds the configured driver-training row budget")
        root.mkdir(parents=True, exist_ok=True)
        source = root / "input.parquet"
        rows.to_parquet(source, index=False)
    prepare(scenario, source, prepared)
    train(scenario, prepared, model)
    stamp_model(model, model_tags)
    report = evaluate(scenario, prepared, model, evaluation)
    mlflow.log_params({"scenario": scenario["name"], "task": scenario["task"], "source": scenario["dataset"]["slug"]})
    mlflow.log_metrics(report["metrics"])
    mlflow.log_artifact(str(prepared / "manifest.json"), "provenance")
    mlflow.log_artifacts(str(evaluation), "evaluation")
    mlflow.log_artifacts(str(model), "model")
    model_uri = f"runs:/{run.info.run_id}/model"
    print(model_uri)

# COMMAND ----------
# Registration/promotion is a separate reviewed step after the held-out quality gate.
dbutils.notebook.exit(model_uri)
