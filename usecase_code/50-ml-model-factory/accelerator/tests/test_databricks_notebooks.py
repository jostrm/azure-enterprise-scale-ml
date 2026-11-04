import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

NOTEBOOKS = Path(__file__).resolve().parents[1] / "databricks"
SCENARIO = {"name": "test-case", "task": "image_classification", "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "a/b", "version": 1, "file": "images"},
            "split": {"test_size": .2, "validation_size": .2}, "vision": {"format": "image_folder"}}
FORECAST = {"name": "forecast-case", "task": "forecasting", "target": "y", "features": ["promo"],
            "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "a/b", "version": 1, "file": "train.csv"},
            "split": {"test_size": .2, "validation_size": .2}, "forecast": {"time_column": "ds", "frequency": "D", "horizon": 2}}


def scenario_file(tmp_path, scenario):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    return path


def test_train_vision_branch_sets_task_value(monkeypatch, tmp_path):
    source = tmp_path / "Volumes" / "c" / "s" / "v" / "images"
    source.mkdir(parents=True)
    values = {"scenario_path": str(scenario_file(tmp_path, SCENARIO)), "input_path": "/Volumes/c/s/v/images",
              "artifact_root": "/local_disk0/root", "experiment_path": "/Shared/e", "max_rows": "10", "lake_config": "", "model_context": ""}
    dbutils, mlflow = MagicMock(), MagicMock()
    dbutils.widgets.get.side_effect = lambda name: values[name]
    mlflow.start_run.return_value.__enter__.return_value.info.run_id = "a" * 32
    original_is_dir = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda self: str(self).replace("\\", "/").startswith("/Volumes") or original_is_dir(self))
    monkeypatch.setitem(sys.modules, "mlflow", mlflow)
    monkeypatch.setitem(sys.modules, "model_tags", SimpleNamespace(load_model_context=lambda value, lake: {}))
    monkeypatch.setitem(sys.modules, "ml_model_factory.vision", SimpleNamespace(
        prepare_vision=MagicMock(), train_vision=MagicMock(), evaluate_vision=MagicMock(return_value={"metrics": {"accuracy": 1.0}})))
    monkeypatch.setitem(sys.modules, "ml_model_factory.tags", SimpleNamespace(build_tags=lambda *a, **k: {"training_engine": "databricks"}, stamp_model=MagicMock()))
    runpy.run_path(str(NOTEBOOKS / "train.py"), init_globals={"dbutils": dbutils, "spark": MagicMock()})
    dbutils.jobs.taskValues.set.assert_called_with(key="model_uri", value="runs:/" + "a" * 32 + "/model")
    assert json.loads(dbutils.notebook.exit.call_args.args[0])["model_uri"] == "runs:/" + "a" * 32 + "/model"


def test_batch_refuses_automl_forecasting(monkeypatch, tmp_path):
    dbutils = MagicMock()
    values = {"scenario_path": str(scenario_file(tmp_path, FORECAST)), "model_uri": "models:/m/1", "model_mode": "automl"}
    dbutils.widgets.get.side_effect = lambda name: values.get(name, "")
    monkeypatch.setitem(sys.modules, "mlflow", MagicMock())
    monkeypatch.setitem(sys.modules, "pyspark", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pyspark.sql", SimpleNamespace(functions=MagicMock()))
    with pytest.raises(ValueError, match="AutoML forecasting"):
        runpy.run_path(str(NOTEBOOKS / "batch_score.py"), init_globals={"dbutils": dbutils, "spark": MagicMock()})


def test_serve_create_and_update_paths(monkeypatch, tmp_path):
    for exists, expected in [(False, "created"), (True, "updated")]:
        dbutils, client = MagicMock(), MagicMock()
        values = {"scenario_path": str(scenario_file(tmp_path, {**SCENARIO, "name": "image-case"})), "model_uri": "runs:/" + "a" * 32 + "/model",
                  "registered_model_name": "cat.sch.model", "endpoint_name": "endpoint", "workload_size": "Small",
                  "scale_to_zero": "true", "model_context": '{"aifactory":"af","project":"001","environment_name":"dev"}',
                  "lake_config": "", "sample_request": ""}
        dbutils.widgets.get.side_effect = lambda name, values=values: values[name]
        from databricks.sdk.errors import NotFound
        client.serving_endpoints.get.side_effect = None if exists else NotFound("missing")
        monkeypatch.setitem(sys.modules, "mlflow", MagicMock(set_registry_uri=MagicMock()))
        import databricks.sdk
        monkeypatch.setattr(databricks.sdk, "WorkspaceClient", lambda: client)
        monkeypatch.setitem(sys.modules, "model_tags", SimpleNamespace(load_model_context=lambda v, l: json.loads(v), register_evaluated=lambda *a, **k: SimpleNamespace(version="3")))
        runpy.run_path(str(NOTEBOOKS / "serve.py"), init_globals={"dbutils": dbutils})
        receipt = json.loads(dbutils.notebook.exit.call_args.args[0])
        assert receipt["state"] == expected
