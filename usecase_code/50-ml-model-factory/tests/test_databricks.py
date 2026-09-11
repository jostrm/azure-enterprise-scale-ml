from pathlib import Path
import importlib.util
import json
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ml_model_factory.databricks_job import run_job


HOST = "https://adb-123456789.1.azuredatabricks.net"
RESOURCE = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/providers/Microsoft.Databricks/workspaces/test"
PARAMETERS = {"input_path": "wasbs://data@storage.blob.core.windows.net/input.csv"}


def test_existing_job_completion_and_explicit_model_handoff(tmp_path):
    client = MagicMock()
    client.jobs.run_now.return_value.result.return_value = SimpleNamespace(
        run_id=1, tasks=[SimpleNamespace(task_key="train-evaluate", run_id=2)],
    )
    client.jobs.get_run_output.return_value.notebook_output = SimpleNamespace(
        truncated=False, result="runs:/run/model",
    )
    with patch("databricks.sdk.WorkspaceClient", return_value=client) as constructor:
        result = run_job(HOST, RESOURCE, 1, PARAMETERS, tmp_path, idempotency_token="test-run")
    assert result["model_uri"] == "runs:/run/model"
    assert (tmp_path / "model_uri.txt").read_text().strip() == "runs:/run/model"
    assert constructor.call_args.kwargs["auth_type"] == "azure-msi"
    assert client.jobs.run_now.call_args.kwargs["idempotency_token"] == "test-run"
    assert client.jobs.run_now.call_args.kwargs["job_parameters"] == PARAMETERS


def test_azure_ml_mounted_path_is_not_passed_to_databricks(tmp_path):
    with pytest.raises(ValueError, match="Databricks-readable"):
        run_job(HOST, RESOURCE, 1, {"input_path": "/mnt/azureml/input.csv"}, tmp_path)


def test_failed_job_has_no_success_artifact(tmp_path):
    client = MagicMock()
    client.jobs.run_now.return_value.result.side_effect = TimeoutError("job timeout")
    with patch("databricks.sdk.WorkspaceClient", return_value=client), pytest.raises(TimeoutError):
        run_job(HOST, RESOURCE, 1, PARAMETERS, tmp_path)
    assert not (tmp_path / "result.json").exists()


def test_v2_component_loads_without_network():
    from azure.ai.ml import load_component
    root = Path(__file__).resolve().parents[1]
    component = load_component(root / "batch" / "classification" / "databricks-azureml-pipeline-step" / "component.yml")
    assert component.type == "command"


NOTEBOOKS = Path(__file__).resolve().parents[1] / "databricks"
SPEC = importlib.util.spec_from_file_location("lake_utils", NOTEBOOKS / "lake_utils.py")
lake_utils = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lake_utils)
SCENARIO = {
    "name": "test-case", "task": "classification", "target": "label", "features": ["feature"],
    "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "example/example",
                "version": 1, "file": "train.csv"},
}


def lake_config(**overrides):
    return {
        "project": "001", "environment": "dev", "dataset": "stable-data", "data_version": "1",
        "snapshot_id": "snapshot-1", "run_id": "run-1", "serving": "streaming",
        "model_version": "1", "pipeline_id": "prediction-events", "pipeline_version": "v1",
        "storage": {"account_url": "https://examplestorage.blob.core.windows.net",
                    "container": "ml-model-factory", "datastore": "project_blob"},
        **overrides,
    }


def test_lake_checkpoint_stable_across_runs_models_but_not_query_schema_versions():
    first = lake_utils.load_lake(json.dumps(lake_config()), SCENARIO, "streaming")
    next_run = lake_utils.load_lake(json.dumps(lake_config(run_id="run-2", model_version="2")), SCENARIO, "streaming")
    next_schema = lake_utils.load_lake(json.dumps(lake_config(pipeline_version="v2")), SCENARIO, "streaming")
    root = "/Volumes/catalog/schema/checkpoints"
    assert lake_utils.checkpoint_path(first, root) == lake_utils.checkpoint_path(next_run, root)
    assert lake_utils.checkpoint_path(first, root) != lake_utils.checkpoint_path(next_schema, root)
    assert first.key("output") != next_run.key("output")
    assert first.key("feedback") != first.key("training_gold")


@pytest.mark.parametrize("root", [
    "wasbs://container@examplestorage.blob.core.windows.net/checkpoint",
    "abfss://container@examplestorage.blob.core.windows.net/checkpoint",
    "abfss://container@examplestorage.dfs.core.windows.net/checkpoint?sig=NEVER_PRINT",
    "/Volumes/catalog/schema/volume/runs/run-1", "/Volumes/catalog/schema/volume/../other",
    "abfss://container@examplestorage.dfs.core.windows.net/%2e%2e",
])
def test_lake_checkpoints_require_supported_credential_free_stable_backend(root):
    lake = lake_utils.load_lake(json.dumps(lake_config()), SCENARIO, "streaming")
    with pytest.raises(ValueError) as caught:
        lake_utils.checkpoint_path(lake, root)
    assert "NEVER_PRINT" not in str(caught.value)


def test_lake_checkpoint_checks_installed_hadoop_connector():
    lake = lake_utils.load_lake(json.dumps(lake_config()), SCENARIO, "streaming")
    spark = MagicMock()
    root = "abfss://container@checkpointstore.dfs.core.windows.net"
    assert lake_utils.checkpoint_path(lake, root, spark).endswith(lake.key("checkpoint"))
    spark._jvm.org.apache.hadoop.fs.FileSystem.getFileSystemClass.assert_called_once()
    spark._jvm.org.apache.hadoop.fs.FileSystem.getFileSystemClass.side_effect = RuntimeError("NEVER_PRINT")
    with pytest.raises(ValueError) as caught:
        lake_utils.checkpoint_path(lake, root, spark)
    assert "NEVER_PRINT" not in str(caught.value)


def test_lake_data_reads_blob_landing_and_lineage_is_not_fake_publication():
    lake = lake_utils.load_lake(json.dumps(lake_config(serving="batch")), SCENARIO)
    uri = lake_utils.landing_file(lake, SCENARIO)
    assert uri == f"wasbs://ml-model-factory@examplestorage.blob.core.windows.net/{lake.key('landing')}/train.csv"
    metadata = lake_utils.lineage(lake, output_table="catalog.schema.predictions")
    assert metadata["bindings"]["output_table"] == "catalog.schema.predictions"
    assert "not automatically materialized" in metadata["publication"]
    assert "predictions are not labels" in metadata["feedback"]
    assert "storage" not in metadata


def test_lake_lineage_keeps_late_writes_outside_immutable_roots():
    lake = lake_utils.load_lake(json.dumps(lake_config()), SCENARIO, "streaming")
    metadata = lake_utils.lineage(lake)
    paths = metadata["paths"]
    assert paths["dataset_quarantine"] == lake.key("dataset_quarantine")
    assert not paths["dataset_quarantine"].startswith(lake.key("dataset_root") + "/")
    for area in ("quarantine", "feedback"):
        assert paths[area] == lake.key(area)
        assert not paths[area].startswith(lake.key("inference_root") + "/")
        assert not paths[area].startswith(lake.key("training_snapshot") + "/")


@pytest.mark.parametrize("uri", ["models:/model@champion", "models:/model/latest", "models:/model/2",
                               "models:/model/1?sig=NEVER_PRINT"])
def test_lake_inference_requires_matching_immutable_model_version(uri):
    lake = lake_utils.load_lake(json.dumps(lake_config()), SCENARIO, "streaming")
    with pytest.raises(ValueError) as caught:
        lake_utils.validate_model(lake, uri)
    assert "NEVER_PRINT" not in str(caught.value)
    lake_utils.validate_model(lake, "models:/model/1")


def test_lake_config_supports_file_and_rejects_mismatched_scenario_or_serving(tmp_path):
    path = tmp_path / "lake.json"
    path.write_text(json.dumps(lake_config()), encoding="utf-8")
    assert lake_utils.load_lake(str(path), SCENARIO).project == "001"
    for config in (lake_config(use_case="wrong-case"), lake_config(serving="batch"),
                   lake_config(model_version=None)):
        with pytest.raises(ValueError):
            lake_utils.load_lake(json.dumps(config), SCENARIO, serving="streaming")


def execute_scoring_notebook(name, widgets, monkeypatch, tmp_path):
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(SCENARIO), encoding="utf-8")
    values = {"scenario_path": str(scenario), "model_uri": "models:/model/1", "prediction_type": "double",
              "input_table": "catalog.schema.inputs", "output_table": "catalog.schema.predictions",
              "lake_config": "", **widgets}
    dbutils, spark, mlflow, functions = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    dbutils.widgets.get.side_effect = lambda name: values.get(name, "")
    spark.table.return_value.columns = ["feature"]
    monkeypatch.setitem(sys.modules, "lake_utils", lake_utils)
    monkeypatch.setitem(sys.modules, "mlflow", mlflow)
    monkeypatch.setitem(sys.modules, "pyspark", SimpleNamespace())
    sql = SimpleNamespace(functions=functions, types=MagicMock())
    monkeypatch.setitem(sys.modules, "pyspark.sql", sql)
    if name == "stream_score.py":
        values.update(eventhubs_namespace="example-events", eventhub_name="predictions",
                      secret_scope="scope", connection_string_secret="connection", payload_schema_json="{}")
        dbutils.secrets.get.return_value = "Endpoint=sb://example;SharedAccessKey=NEVER_PRINT"
        schema = sql.types.StructType.fromJson.return_value
        schema.fieldNames.return_value = ["feature", "event_id", "event_time"]
        sql.types.TimestampType = type("TimestampType", (), {})
        schema.__getitem__.return_value.dataType = sql.types.TimestampType()
    runpy.run_path(str(NOTEBOOKS / name), init_globals={"dbutils": dbutils, "spark": spark})
    return spark, mlflow


def test_legacy_batch_notebook_keeps_tables_and_does_not_log_lake(monkeypatch, tmp_path):
    spark, mlflow = execute_scoring_notebook("batch_score.py", {}, monkeypatch, tmp_path)
    spark.table.assert_called_once_with("catalog.schema.inputs")
    mlflow.start_run.assert_not_called()
    mlflow.log_dict.assert_not_called()


def test_lake_batch_notebook_logs_real_table_binding(monkeypatch, tmp_path):
    _, mlflow = execute_scoring_notebook(
        "batch_score.py", {"lake_config": json.dumps(lake_config(serving="batch"))}, monkeypatch, tmp_path,
    )
    metadata = mlflow.log_dict.call_args.args[0]
    assert metadata["bindings"]["output_table"] == "catalog.schema.predictions"
    expected = lake_utils.load_lake(json.dumps(lake_config(serving="batch")), SCENARIO)
    assert metadata["paths"]["feedback"] == expected.key("feedback")


def test_lake_stream_notebook_uses_stable_checkpoint_and_never_logs_secrets(monkeypatch, tmp_path, capsys):
    _, mlflow = execute_scoring_notebook(
        "stream_score.py", {"lake_config": json.dumps(lake_config()),
                            "checkpoint_root": "/Volumes/catalog/schema/checkpoints"}, monkeypatch, tmp_path,
    )
    metadata = mlflow.log_dict.call_args.args[0]
    assert metadata["bindings"]["checkpoint"].endswith(
        "/operations/streaming/prediction-events/versions/v1/checkpoints",
    )
    assert metadata["bindings"]["output_table"] == "catalog.schema.predictions"
    assert "NEVER_PRINT" not in json.dumps(metadata)
    assert "NEVER_PRINT" not in str(mlflow.mock_calls)
    output = capsys.readouterr()
    assert "NEVER_PRINT" not in output.out + output.err


def test_legacy_stream_keeps_explicit_checkpoint_without_lake_lineage(monkeypatch, tmp_path):
    _, mlflow = execute_scoring_notebook(
        "stream_score.py", {"checkpoint": "/Volumes/catalog/schema/checkpoints/legacy-query"},
        monkeypatch, tmp_path,
    )
    mlflow.log_dict.assert_not_called()
    mlflow.start_run.assert_not_called()


def execute_training_notebook(tmp_path, config=None):
    scenario = tmp_path / "training-scenario.json"
    scenario.write_text(json.dumps(SCENARIO), encoding="utf-8")
    source = tmp_path / "legacy.csv"
    source.write_text("feature,label\n1,1\n", encoding="utf-8")
    values = {
        "scenario_path": str(scenario), "input_path": "" if config else str(source),
        "artifact_root": "/local_disk0/ml-model-factory", "experiment_path": "/Shared/approved",
        "max_rows": "1000", "lake_config": json.dumps(config) if config else "",
    }
    dbutils, spark, mlflow = MagicMock(), MagicMock(), MagicMock()
    dbutils.widgets.get.side_effect = lambda name: values[name]
    mlflow.start_run.return_value.__enter__.return_value.info.run_id = "a" * 32
    preparation, training, evaluation = MagicMock(), MagicMock(), MagicMock(return_value={"metrics": {"accuracy": 1.0}})
    artifact_root = tmp_path / "artifacts"

    def local_path(value):
        return artifact_root if value == values["artifact_root"] else Path(value)

    with patch.dict(sys.modules, {
        "pathlib": SimpleNamespace(Path=local_path), "mlflow": mlflow, "lake_utils": lake_utils,
        "ml_model_factory.data": SimpleNamespace(prepare=preparation),
        "ml_model_factory.training": SimpleNamespace(train=training),
        "ml_model_factory.evaluation": SimpleNamespace(evaluate=evaluation),
    }):
        runpy.run_path(str(NOTEBOOKS / "train.py"), init_globals={"dbutils": dbutils, "spark": spark})
    return spark, mlflow, preparation, artifact_root


def test_legacy_training_notebook_preserves_mlflow_run_artifact_location(tmp_path):
    _, mlflow, preparation, root = execute_training_notebook(tmp_path)
    assert preparation.call_args.args[1] == tmp_path / "legacy.csv"
    assert preparation.call_args.args[2] == root / ("a" * 32) / "prepared"
    mlflow.log_dict.assert_not_called()


def test_lake_training_notebook_reads_landing_logs_lineage_and_never_overwrites_snapshot(tmp_path):
    config = lake_config(serving="batch")
    layout = lake_utils.load_lake(json.dumps(config), SCENARIO)
    spark, mlflow, preparation, root = execute_training_notebook(tmp_path, config)
    source = lake_utils.landing_file(layout, SCENARIO)
    spark.read.option.return_value.option.return_value.format.return_value.load.assert_called_once_with(source)
    expected_root = root.joinpath(*layout.key("training_run").split("/"))
    assert preparation.call_args.args[2] == expected_root / "prepared"
    assert not root.joinpath(*layout.key("training_gold").split("/")).exists()
    metadata = mlflow.log_dict.call_args.args[0]
    assert metadata["bindings"]["input_file"] == source
    assert metadata["paths"] == layout.as_dict()
    with pytest.raises(FileExistsError):
        execute_training_notebook(tmp_path, config)


def test_notebook_sources_and_job_optional_widget_compile():
    for path in NOTEBOOKS.glob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    job = json.loads((NOTEBOOKS / "job-template.json").read_text())
    assert next(p for p in job["parameters"] if p["name"] == "lake_config")["default"] == ""
    assert job["tasks"][0]["notebook_task"]["base_parameters"]["lake_config"] == "{{job.parameters.lake_config}}"
