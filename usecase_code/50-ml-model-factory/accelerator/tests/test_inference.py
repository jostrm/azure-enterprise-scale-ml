"""Shared scoring contract for batch files, online requests and streaming micro-batches."""

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from ml_model_factory import cli
from ml_model_factory.data import prepare
from ml_model_factory.inference import (
    IMAGE_COLUMN, AutoMLForecastScorer, ModelScorer, PyfuncScorer, detect_mode, load_scorer,
    model_columns, sample_requests, score_file, score_frame,
)


DATASET = {"provider": "kaggle", "kind": "dataset", "slug": "example/example", "version": 1, "file": "train.csv"}
CLASSIFICATION = {
    "name": "fixture-classification", "task": "classification", "target": "label",
    "features": ["amount", "segment"], "categorical_features": ["segment"],
    "dataset": DATASET, "split": {"seed": 7, "test_size": 0.2, "validation_size": 0.2},
    "custom": {"algorithm": "logistic_regression"}, "quality": {"min_accuracy": 0.0},
}
FORECAST = {
    "name": "fixture-forecast", "task": "forecasting", "target": "sales", "features": ["date"],
    "dataset": DATASET, "forecast": {"time_column": "date", "series_columns": [], "frequency": "D", "horizon": 3},
    "custom": {"algorithm": "seasonal_naive", "seasonal_period": 7}, "quality": {},
}
GENERATED = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def tabular_model(tmp_path):
    from ml_model_factory.training import train

    rng = np.random.default_rng(11)
    amount = rng.normal(size=200)
    frame = pd.DataFrame({"amount": amount, "segment": np.where(amount > 0, "a", "b"),
                          "label": (amount > 0).astype(int)})
    frame.to_csv(tmp_path / "train.csv", index=False)
    prepare(CLASSIFICATION, tmp_path / "train.csv", tmp_path / "prepared")
    train(CLASSIFICATION, tmp_path / "prepared", tmp_path / "model")
    return tmp_path / "prepared", tmp_path / "model"


@pytest.fixture
def forecast_model(tmp_path):
    from ml_model_factory.training import train

    dates = pd.date_range("2025-01-01", periods=60, freq="D")
    pd.DataFrame({"date": dates, "sales": np.arange(60) % 7 + 10.0}).to_csv(tmp_path / "series.csv", index=False)
    prepare(FORECAST, tmp_path / "series.csv", tmp_path / "prepared")
    train(FORECAST, tmp_path / "prepared", tmp_path / "model")
    return tmp_path / "prepared", tmp_path / "model"


def test_model_columns_follow_task_contracts():
    assert model_columns(CLASSIFICATION) == ["amount", "segment"]
    assert model_columns({**FORECAST, "forecast": {**FORECAST["forecast"], "series_columns": ["store"]}}) == [
        "date", "store"]
    image = {"name": "fixture-image", "task": "image_classification", "dataset": DATASET}
    assert model_columns(image) == [IMAGE_COLUMN]


def test_sample_requests_separate_requests_labels_events_and_online_payload(tabular_model, tmp_path):
    prepared, _ = tabular_model
    manifest = sample_requests(CLASSIFICATION, prepared, tmp_path / "requests", rows=5, generated_at=GENERATED)
    requests = pd.read_parquet(tmp_path / "requests" / "requests.parquet")
    labels = pd.read_parquet(tmp_path / "requests" / "labels.parquet")
    assert list(requests.columns) == ["request_id", "amount", "segment"]
    assert "label" not in requests
    assert list(labels.columns) == ["request_id", "label", "observed_at"]
    assert requests["request_id"].is_unique and list(requests["request_id"]) == list(labels["request_id"])
    events = [json.loads(line) for line in (tmp_path / "requests" / "events.jsonl").read_text().splitlines()]
    assert [event["event_id"] for event in events] == list(requests["request_id"])
    assert all("label" not in event and {"amount", "segment", "event_time"} <= set(event) for event in events)
    assert datetime.fromisoformat(events[0]["event_time"]) == GENERATED
    payload = json.loads((tmp_path / "requests" / "online-request.json").read_text())
    assert payload["input_data"]["columns"] == ["amount", "segment"]
    assert len(payload["input_data"]["data"]) == 5
    assert manifest["rows"] == 5 and set(manifest["files"]) >= {"requests.parquet", "labels.parquet"}
    with pytest.raises(ValueError, match="empty"):
        sample_requests(CLASSIFICATION, prepared, tmp_path / "requests", rows=5)


def test_score_file_writes_predictions_and_lineage_without_labels(tabular_model, tmp_path):
    prepared, model = tabular_model
    sample_requests(CLASSIFICATION, prepared, tmp_path / "requests", rows=6, generated_at=GENERATED)
    info = score_file(CLASSIFICATION, model, tmp_path / "requests" / "requests.parquet", tmp_path / "scored",
                      model_version="3")
    predictions = pd.read_parquet(tmp_path / "scored" / "predictions.parquet")
    assert list(predictions.columns) == ["request_id", "prediction", "model_version"]
    assert len(predictions) == 6 and set(predictions["model_version"]) == {"3"}
    assert info["mode"] == "custom" and info["rows"] == 6
    assert info["model_tags"]["use_case"] == "fixture-classification"
    assert len(info["input_sha256"]) == 64 and len(info["predictions_sha256"]) == 64
    with pytest.raises(ValueError, match="empty"):
        score_file(CLASSIFICATION, model, tmp_path / "requests" / "requests.parquet", tmp_path / "scored")


@pytest.mark.parametrize("change, message", [
    (lambda frame: frame.assign(label=1), "labels"),
    (lambda frame: frame.assign(request_id="same"), "request_id"),
    (lambda frame: frame.drop(columns=["segment"]), "segment"),
    (lambda frame: frame.iloc[0:0], "empty"),
])
def test_scoring_rejects_labels_duplicate_ids_missing_features_and_empty_batches(tabular_model, change, message):
    _, model = tabular_model
    frame = pd.DataFrame({"request_id": ["a", "b"], "amount": [0.5, -0.5], "segment": ["a", "b"]})
    with pytest.raises(ValueError, match=message):
        score_frame(load_scorer(CLASSIFICATION, model), change(frame))


def test_custom_forecast_scores_requested_timestamps_and_refuses_external_history(forecast_model, tmp_path):
    prepared, model = forecast_model
    sample_requests(FORECAST, prepared, tmp_path / "requests", rows=3, generated_at=GENERATED)
    assert (tmp_path / "requests" / "history.parquet").is_file()
    info = score_file(FORECAST, model, tmp_path / "requests" / "requests.parquet", tmp_path / "scored")
    assert info["rows"] == 3
    truth = pd.read_parquet(tmp_path / "requests" / "labels.parquet")["sales"].to_numpy()
    predicted = pd.read_parquet(tmp_path / "scored" / "predictions.parquet")["prediction"].to_numpy()
    np.testing.assert_allclose(predicted, truth)
    with pytest.raises(ValueError, match="history"):
        load_scorer(FORECAST, model, history=pd.read_parquet(tmp_path / "requests" / "history.parquet"))


def test_automl_forecast_scorer_requires_prior_history_and_aligns_keys(tmp_path):
    model = tmp_path / "automl-model"
    model.mkdir()
    (model / "MLmodel").write_text("flavors:\n  sklearn: {}\n")
    scenario = {**FORECAST, "features": ["date", "price"],
                "forecast": {**FORECAST["forecast"], "series_columns": ["store"]}}
    history = pd.DataFrame({"date": pd.to_datetime(["2025-01-01", "2025-01-01"]), "store": ["b", "a"],
                            "price": [1.0, 2.0], "sales": [10.0, 20.0]})
    future = pd.DataFrame({"request_id": ["r1", "r2"], "date": pd.to_datetime(["2025-01-02", "2025-01-02"]),
                           "store": ["b", "a"], "price": [3.0, 4.0]})
    estimator = MagicMock()

    def forecast(X_pred=None, y_pred=None, forecast_destination=None, ignore_data_errors=False):
        ordered = X_pred.iloc[[1, 3, 0, 2]].set_index(["store", "date"])
        return np.array([20.0, 22.0, 10.0, 11.0]), ordered

    estimator.forecast.side_effect = forecast
    with pytest.raises(ValueError, match="history"):
        load_scorer(scenario, model, mode="automl")
    with patch("mlflow.sklearn.load_model", return_value=estimator) as loader:
        scorer = load_scorer(scenario, model, mode="automl", history=history)
        assert isinstance(scorer, AutoMLForecastScorer)
        first = score_frame(scorer, future)
        second = score_frame(scorer, future)
    assert loader.call_count == 1
    assert list(first["prediction"]) == [11.0, 22.0] and first.equals(second)
    late = history.assign(date=pd.to_datetime(["2025-01-03", "2025-01-03"]))
    with patch("mlflow.sklearn.load_model", return_value=estimator):
        with pytest.raises(ValueError, match="precede"):
            score_frame(load_scorer(scenario, model, mode="automl", history=late), future)


def test_mode_detection_is_explicit_for_external_artifacts(tabular_model, tmp_path):
    _, model = tabular_model
    assert detect_mode(model) == "custom"
    external = tmp_path / "external"
    external.mkdir()
    (external / "MLmodel").write_text("flavors:\n  python_function: {}\n")
    with pytest.raises(ValueError, match="mode"):
        detect_mode(external)


def test_scorer_strategy_accepts_injected_models_for_isolated_callers():
    class Constant:
        metadata = None

        def predict(self, frame):
            return np.full(len(frame), "cat", dtype=object)

    image = {"name": "fixture-image", "task": "image_classification", "dataset": DATASET}
    scorer = PyfuncScorer(image, model=Constant())
    assert isinstance(scorer, ModelScorer)
    payload = base64.b64encode(b"not-decoded-by-the-strategy").decode()
    result = score_frame(scorer, pd.DataFrame({"request_id": ["r1"], IMAGE_COLUMN: [payload]}))
    assert result.to_dict("records") == [{"request_id": "r1", "prediction": "cat"}]
    with pytest.raises(ValueError, match="AutoMLVisionScorer"):
        PyfuncScorer(image, mode="automl", model=Constant())


def test_nonfinite_predictions_fail_closed():
    class Broken:
        metadata = None

        def predict(self, frame):
            return np.array([np.nan] * len(frame))

    scorer = PyfuncScorer(CLASSIFICATION, model=Broken())
    with pytest.raises(ValueError, match="finite"):
        score_frame(scorer, pd.DataFrame({"request_id": ["r1"], "amount": [1.0], "segment": ["a"]}))


def test_cli_sample_requests_and_score_commands(tabular_model, tmp_path, capsys):
    prepared, model = tabular_model
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(CLASSIFICATION), encoding="utf-8")
    assert cli.main(["sample-requests", "--scenario", str(scenario), "--prepared", str(prepared),
                     "--output", str(tmp_path / "requests"), "--rows", "4"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 4
    assert cli.main(["score", "--scenario", str(scenario), "--model", str(model),
                     "--input", str(tmp_path / "requests" / "requests.parquet"),
                     "--output", str(tmp_path / "scored")]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 4


def test_vision_requests_carry_base64_images_and_reviewed_labels(tmp_path):
    from PIL import Image

    prepared = tmp_path / "prepared" / "test"
    (prepared / "images").mkdir(parents=True)
    rows = []
    for index, label in enumerate(("cat", "dog")):
        Image.new("RGB", (8, 8), (index * 100, 0, 0)).save(prepared / "images" / f"{index}.png")
        rows.append({"image": f"images/{index}.png", "label": label, "width": 8, "height": 8})
    (prepared / "annotations.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    image = {"name": "fixture-image", "task": "image_classification", "dataset": DATASET}
    sample_requests(image, tmp_path / "prepared", tmp_path / "requests", rows=2, generated_at=GENERATED)
    requests = pd.read_parquet(tmp_path / "requests" / "requests.parquet")
    labels = pd.read_parquet(tmp_path / "requests" / "labels.parquet")
    assert list(requests.columns) == ["request_id", IMAGE_COLUMN]
    assert base64.b64decode(requests[IMAGE_COLUMN][0]) == (prepared / "images" / "0.png").read_bytes()
    assert list(labels["label"]) == ["cat", "dog"]
    event = json.loads((tmp_path / "requests" / "events.jsonl").read_text().splitlines()[1])
    assert event[IMAGE_COLUMN] == requests[IMAGE_COLUMN][1]
    assert datetime.fromisoformat(event["event_time"]) == GENERATED + timedelta(milliseconds=1)
