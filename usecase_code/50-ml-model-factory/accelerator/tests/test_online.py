import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys
import types

import numpy as np
import pandas as pd
import pytest

from ml_model_factory import cli
from ml_model_factory.inference import ModelScorer, REQUEST_ID
from ml_model_factory.online import (
    AutoMLForecastScorerProvider, OnlineService, StaticScorerProvider, local_online_test, parse_request,
)

DATASET = {"provider": "kaggle", "kind": "dataset", "slug": "example/example", "version": 1, "file": "train.csv"}
SCENARIO = {"name": "online-fixture", "task": "classification", "target": "label",
            "features": ["x", "segment"], "categorical_features": ["segment"], "dataset": DATASET}
FORECAST = {"name": "forecast-fixture", "task": "forecasting", "target": "sales", "features": ["date", "price"],
            "dataset": DATASET, "forecast": {"time_column": "date", "series_columns": ["store"], "frequency": "D", "horizon": 1}}


class EchoScorer(ModelScorer):
    def __init__(self, scenario=SCENARIO, mode="custom"):
        super().__init__(scenario, mode)
    def predict(self, features):
        return np.arange(len(features))


def test_parse_request_accepts_supported_formats_ids_limits_and_rejects_labels():
    split = {"input_data": {"columns": ["x", "segment"], "index": [0], "data": [[1, "a"]]}, "request_ids": ["r1"]}
    frame = parse_request(json.dumps(split), SCENARIO)
    assert frame.to_dict("records") == [{REQUEST_ID: "r1", "x": 1, "segment": "a"}]
    assert parse_request({"input_data": [{"request_id": "r2", "x": 2, "segment": "b"}]}, SCENARIO)[REQUEST_ID].tolist() == ["r2"]
    assert len(parse_request({"dataframe_records": [{"x": 3, "segment": "c"}]}, SCENARIO)[REQUEST_ID][0]) > 10
    assert parse_request({"dataframe_split": {"columns": ["x", "segment"], "data": [[4, "d"]]}}, SCENARIO).shape == (1, 3)
    with pytest.raises(ValueError, match="labels"):
        parse_request({"dataframe_records": [{"x": 1, "segment": "a", "label": 1}]}, SCENARIO)
    with pytest.raises(ValueError, match="max_rows"):
        parse_request({"dataframe_records": [{"x": 1, "segment": "a"}, {"x": 2, "segment": "b"}]}, SCENARIO, max_rows=1)
    with pytest.raises(ValueError, match="JSON object"):
        parse_request([1, 2], SCENARIO)


def test_history_is_forecast_only_and_attached_to_frame():
    payload = {"dataframe_records": [{"date": "2025-01-02", "store": "a", "price": 2.0}],
               "history": {"dataframe_records": [{"date": "2025-01-01", "store": "a", "price": 1.0, "sales": 10.0}]}}
    frame = parse_request(payload, FORECAST)
    assert frame.attrs["history"]["sales"].tolist() == [10.0]
    with pytest.raises(ValueError, match="history"):
        parse_request({"dataframe_records": [{"x": 1, "segment": "a"}], "history": []}, SCENARIO)


def test_online_service_json_safe_response_and_static_history_refusal():
    service = OnlineService(SCENARIO, StaticScorerProvider(EchoScorer()), model_version="7")
    response = service.handle({"dataframe_records": [{"request_id": "a", "x": 1, "segment": "a"}, {"request_id": "b", "x": 2, "segment": "b"}]})
    assert response["request_ids"] == ["a", "b"]
    assert [row["prediction"] for row in response["predictions"]] == [0, 1]
    assert {row["model_version"] for row in response["predictions"]} == {"7"}


def test_automl_forecast_provider_loads_once_and_requires_history(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "MLmodel").write_text("flavors:\n  sklearn: {}\n")
    estimator = MagicMock()
    with patch("ml_model_factory.serving.load_forecaster", return_value=estimator) as loader:
        provider = AutoMLForecastScorerProvider(FORECAST, model)
        with pytest.raises(ValueError, match="history"):
            provider.scorer_for()
        history = pd.DataFrame({"date": ["2025-01-01"], "store": ["a"], "price": [1.0], "sales": [10.0]})
        assert provider.scorer_for(history).model is estimator
        assert provider.scorer_for(history).model is estimator
    assert loader.call_count == 1


def test_scoring_entrypoint_run_uses_initialized_service_without_stack_leaks(tmp_path, monkeypatch):
    from ml_model_factory import online
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scenario.json").write_text(json.dumps(SCENARIO))
    (tmp_path / "serving.json").write_text(json.dumps({"mode": "custom", "model_version": "9"}))
    model_root = tmp_path / "azureml-models" / "m" / "9"
    model_root.mkdir(parents=True)
    (model_root / "MLmodel").write_text("flavors:\n  python_function: {}\n")
    monkeypatch.setenv("AZUREML_MODEL_DIR", str(tmp_path / "azureml-models"))
    with patch("ml_model_factory.online.provider_for", return_value=StaticScorerProvider(EchoScorer())):
        online.init()
    response = online.run(json.dumps({"dataframe_records": [{"request_id": "a", "x": 1, "segment": "a"}]}))
    assert response["model_version"] == "9" and response["rows"] == 1
    bad = online.run(json.dumps({"dataframe_records": [{"request_id": "a", "x": 1, "segment": "a", "label": 1}]}))
    assert bad["status"] == 400 and "Traceback" not in json.dumps(bad)


def test_online_init_refuses_unresolved_version_unless_model_dir_has_name_version(tmp_path, monkeypatch):
    from ml_model_factory import online
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scenario.json").write_text(json.dumps(SCENARIO))
    (tmp_path / "serving.json").write_text(json.dumps({"mode": "custom", "model_version": "REPLACE_WITH_REGISTERED_VERSION"}))
    direct = tmp_path / "direct"
    direct.mkdir()
    (direct / "MLmodel").write_text("flavors:\n  python_function: {}\n")
    monkeypatch.setenv("AZUREML_MODEL_DIR", str(direct))
    with pytest.raises(ValueError, match="unresolved model_version"):
        online.init()
    nested = tmp_path / "models" / "online-fixture" / "42"
    nested.mkdir(parents=True)
    (nested / "MLmodel").write_text("flavors:\n  python_function: {}\n")
    monkeypatch.setenv("AZUREML_MODEL_DIR", str(tmp_path / "models"))
    with patch("ml_model_factory.online.provider_for", return_value=StaticScorerProvider(EchoScorer())):
        online.init()
    response = online.run(json.dumps({"dataframe_records": [{"request_id": "a", "x": 1, "segment": "a"}]}))
    assert response["model_version"] == "42"


def test_aml_response_prefers_v2_import_path_and_falls_back(monkeypatch):
    from ml_model_factory.online import _aml_response
    module = types.ModuleType("azureml_inference_server_http.api.aml_response")
    class AMLResponse:
        def __init__(self, body, status_code):
            self.body = body
            self.status_code = status_code
    module.AMLResponse = AMLResponse
    monkeypatch.setitem(sys.modules, "azureml_inference_server_http", types.ModuleType("azureml_inference_server_http"))
    monkeypatch.setitem(sys.modules, "azureml_inference_server_http.api", types.ModuleType("azureml_inference_server_http.api"))
    monkeypatch.setitem(sys.modules, "azureml_inference_server_http.api.aml_response", module)
    response = _aml_response({"error": "bad"}, 400)
    assert isinstance(response, AMLResponse) and response.status_code == 400
    monkeypatch.delitem(sys.modules, "azureml_inference_server_http.api.aml_response")
    fallback = _aml_response({"error": "bad"}, 400)
    assert fallback["status"] == 400


def test_online_run_logs_unexpected_server_errors(caplog):
    from ml_model_factory import online
    class Broken:
        def handle(self, payload):
            raise RuntimeError("internal detail")
    online._SERVICE = Broken()
    response = online.run("{}")
    assert response["status"] == 500
    assert any("Online scoring failed" in record.message for record in caplog.records)


def test_online_score_script_bootstraps_code_root():
    script = Path(__file__).resolve().parents[1] / "scripts" / "online_score.py"
    text = script.read_text()
    assert "parents[1]" in text and "sys.path.insert" in text


def test_local_online_test_and_cli_with_patched_provider(tmp_path, capsys):
    scenario = tmp_path / "scenario.json"
    request = tmp_path / "request.json"
    model = tmp_path / "model"
    model.mkdir()
    scenario.write_text(json.dumps(SCENARIO))
    request.write_text(json.dumps({"dataframe_records": [{"request_id": "a", "x": 1, "segment": "a"}]}))
    with patch("ml_model_factory.online.provider_for", return_value=StaticScorerProvider(EchoScorer())):
        assert local_online_test(SCENARIO, model, request)["rows"] == 1
        assert cli.main(["online-test", "--scenario", str(scenario), "--model", str(model), "--request", str(request)]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 1
