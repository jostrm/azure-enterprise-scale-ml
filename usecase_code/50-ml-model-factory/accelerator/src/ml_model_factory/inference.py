"""One scoring contract for batch files, online requests and streaming micro-batches.

Callers pass unlabeled rows with a unique request ID; a scorer returns exactly one
finite, nonmissing prediction per row. AutoML artifacts still need a compatible
runtime environment. The adapters only call documented MLflow/AutoML interfaces;
they never substitute another model or fabricate a missing prediction.
"""

from __future__ import annotations

import base64
import json
import math
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import load_json, validate_scenario, write_json
from .data import read_frame, sha256


IMAGE_COLUMN = "image_base64"
REQUEST_ID = "request_id"
EVENT_ID = "event_id"
EVENT_TIME = "event_time"
MODES = ("custom", "automl")
SPLITS = ("train", "validation", "test")


def model_columns(scenario: dict) -> list[str]:
    """Columns a scorer reads; never includes the label or request identity."""
    if scenario["task"].startswith("image_"):
        return [IMAGE_COLUMN]
    columns = list(scenario["features"])
    if scenario["task"] == "forecasting":
        forecast = scenario["forecast"]
        columns = list(dict.fromkeys(columns + forecast.get("series_columns", []) + [forecast["time_column"]]))
    return columns


def label_column(scenario: dict) -> str:
    return scenario.get("target", "label")


def validate_request_ids(frame, column: str = REQUEST_ID) -> None:
    if (column not in frame or frame[column].isna().any() or frame[column].duplicated().any()
            or frame[column].map(lambda value: isinstance(value, str) and not value.strip()).any()):
        raise ValueError("Requests require a nonempty unique request_id per row for output/feedback joins")


def normalize_features(model, frame, scenario: dict):
    """Select model features and apply the MLflow signature's numeric/datetime types."""
    import pandas as pd

    required = model_columns(scenario)
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Inference input is missing model features: {sorted(missing)}")
    if label_column(scenario) in frame.columns:
        raise ValueError("Inference input must not contain labels; store observed labels in feedback")
    result = frame.loc[:, required].copy()
    metadata = getattr(model, "metadata", None)
    schema = metadata.get_input_schema() if metadata is not None else None
    if schema:
        types = {column.name: str(column.type) for column in schema.inputs}
        for column in required:
            if types.get(column) in ("DataType.double", "double"):
                numeric = pd.to_numeric(result[column], errors="raise")
                if pd.api.types.is_integer_dtype(numeric) and ((numeric < -(2**53)) | (numeric > 2**53)).any():
                    raise ValueError(f"{column} exceeds lossless double conversion")
                result[column] = numeric.astype("float64")
            elif types.get(column) in ("DataType.datetime", "datetime"):
                result[column] = pd.to_datetime(result[column], errors="raise")
    return result


def model_definition(model_path: Path) -> dict:
    import yaml

    path = Path(model_path) / "MLmodel"
    if not path.is_file():
        raise FileNotFoundError(f"MLflow model definition not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Expected an MLflow MLmodel document")
    return document


def detect_mode(model_path: Path) -> str:
    """Read the recorded training mode; external artifacts need an explicit mode."""
    factory = Path(model_path) / "factory.json"
    if factory.is_file():
        mode = load_json(factory).get("mode")
        if mode in MODES:
            return mode
    tags = (model_definition(model_path).get("metadata") or {}).get("model_factory_tags") or {}
    if tags.get("training_mode") in MODES:
        return tags["training_mode"]
    raise ValueError("Cannot infer the model's training mode; pass mode='custom' or mode='automl' explicitly")


def check_predictions(predictions, rows: int):
    import numpy as np
    import pandas as pd

    from .evaluation import prediction_vector

    values = prediction_vector(predictions, rows)
    if pd.isna(values).any() or (np.issubdtype(values.dtype, np.number) and not np.isfinite(values).all()):
        raise ValueError("Model must produce a finite, nonmissing prediction for each request")
    return values


class ModelScorer(ABC):
    """Strategy interface shared by batch, online and streaming callers."""

    def __init__(self, scenario: dict, mode: str):
        if mode not in MODES:
            raise ValueError("mode must be custom or automl")
        self.scenario = validate_scenario(scenario)
        self.mode = mode

    @property
    def columns(self) -> list[str]:
        return model_columns(self.scenario)

    def features(self, frame):
        missing = set(self.columns) - set(frame.columns)
        if missing:
            raise ValueError(f"Requests are missing model columns: {sorted(missing)}")
        return frame.loc[:, self.columns].copy()

    @abstractmethod
    def predict(self, features):
        """Return one finite, nonmissing prediction per feature row."""

    def describe(self) -> dict:
        return {"scorer": type(self).__name__, "mode": self.mode, "task": self.scenario["task"],
                "columns": self.columns}


class PyfuncScorer(ModelScorer):
    """Factory custom pyfunc models and AutoML tabular classification/regression models."""

    def __init__(self, scenario: dict, model_path: Path | None = None, *, mode: str = "custom", model=None):
        super().__init__(scenario, mode)
        task = self.scenario["task"]
        if task == "forecasting" and mode == "automl":
            raise ValueError("AutoML forecasting needs observed history; use AutoMLForecastScorer")
        if task.startswith("image_") and mode == "automl":
            raise ValueError("AutoML image models need the documented image adapter; use AutoMLVisionScorer")
        if model is None:
            if model_path is None:
                raise ValueError("Provide a model_path or an injected model")
            import mlflow.pyfunc

            model = mlflow.pyfunc.load_model(str(model_path))
        self.model_path = Path(model_path) if model_path is not None else None
        self.model = model

    def predict(self, features):
        if self.scenario["task"].startswith("image_"):
            inputs = features.loc[:, [IMAGE_COLUMN]]
        else:
            inputs = normalize_features(self.model, features, self.scenario)
        return check_predictions(self.model.predict(inputs), len(features))


class AutoMLForecastScorer(ModelScorer):
    """AutoML forecast() with observed history that strictly precedes each requested series row."""

    def __init__(self, scenario: dict, model_path: Path, history, *, model=None):
        super().__init__(scenario, "automl")
        if self.scenario["task"] != "forecasting":
            raise ValueError("AutoMLForecastScorer requires a forecasting scenario")
        if history is None:
            raise ValueError("AutoML forecasting requires observed history with target values")
        target = label_column(self.scenario)
        required = self.columns + [target]
        missing = set(required) - set(history.columns)
        if missing or history.empty or history[target].isna().any():
            raise ValueError(f"AutoML forecasting history needs labeled rows with {sorted(required)}")
        self.history = history.loc[:, list(dict.fromkeys(required))].copy()
        self.model_path = Path(model_path)
        if model is None:
            from .serving import load_forecaster

            model = load_forecaster(self.model_path)
        self.model = model

    def _check_history(self, future) -> None:
        import pandas as pd

        forecast = self.scenario["forecast"]
        time, series = forecast["time_column"], forecast.get("series_columns", [])
        history = self.history.assign(**{time: pd.to_datetime(self.history[time])})
        requested = future.assign(**{time: pd.to_datetime(future[time])})
        if not series:
            if history[time].max() >= requested[time].min():
                raise ValueError("Observed history must precede every requested forecast timestamp")
            return
        last = history.groupby(series)[time].max()
        first = requested.groupby(series)[time].min()
        unseen = set(first.index) - set(last.index)
        if unseen:
            raise ValueError(f"Forecast requests include series without observed history: {sorted(map(str, unseen))}")
        if (last.loc[first.index] >= first).any():
            raise ValueError("Observed history must precede every requested forecast timestamp")

    def predict(self, features):
        from .serving import forecast_predictions

        self._check_history(features)
        values = forecast_predictions(self.model_path, features, self.history, self.scenario, model=self.model)
        return check_predictions(values, len(features))


def load_scorer(scenario: dict, model_path: Path, *, mode: str | None = None, history=None) -> ModelScorer:
    """Factory method selecting the documented adapter for the model's training mode and task."""
    scenario = validate_scenario(scenario)
    mode = mode or detect_mode(model_path)
    if mode not in MODES:
        raise ValueError("mode must be custom or automl")
    task = scenario["task"]
    if task == "forecasting" and mode == "automl":
        return AutoMLForecastScorer(scenario, model_path, history)
    if history is not None:
        raise ValueError("External history is only used by the AutoML forecast adapter; custom models use fitted history")
    if task.startswith("image_") and mode == "automl":
        from .vision_automl import AutoMLVisionScorer

        return AutoMLVisionScorer(scenario, model_path)
    return PyfuncScorer(scenario, model_path, mode=mode)


def score_frame(scorer: ModelScorer, frame, *, request_id_column: str = REQUEST_ID, model_version=None):
    import pandas as pd

    if not isinstance(request_id_column, str) or not request_id_column.strip() or request_id_column == "prediction":
        raise ValueError("request_id_column must be a nonempty name distinct from prediction")
    validate_request_ids(frame, request_id_column)
    if label_column(scorer.scenario) in frame.columns:
        raise ValueError("Requests must not contain labels; store observed labels separately")
    if frame.empty:
        raise ValueError("Requests must not be empty")
    predictions = scorer.predict(scorer.features(frame))
    result = pd.DataFrame({request_id_column: frame[request_id_column].to_numpy(), "prediction": predictions})
    if model_version is not None:
        result["model_version"] = str(model_version)
    return result


def _empty_output(output: Path, label: str) -> Path:
    output = Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"{label} output must be a new or empty directory")
    return output


def _data_file(path: Path) -> Path:
    path = Path(path)
    return path / "data.parquet" if path.is_dir() else path


def score_file(scenario: dict, model_path: Path, input_path: Path, output: Path, *, mode: str | None = None,
               history_path: Path | None = None, request_id_column: str = REQUEST_ID,
               model_version=None) -> dict:
    """Score an unlabeled CSV/Parquet request file into predictions.parquet plus run lineage."""
    scenario = validate_scenario(scenario)
    output = _empty_output(output, "Scoring")
    frame = read_frame(input_path)
    history = read_frame(history_path) if history_path is not None else None
    scorer = load_scorer(scenario, model_path, mode=mode, history=history)
    result = score_frame(scorer, frame, request_id_column=request_id_column, model_version=model_version)
    output.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output / "predictions.parquet", index=False)
    definition = model_definition(model_path)
    info = {
        "schema": "ml-model-factory-scoring/v1", "scenario": scenario["name"], **scorer.describe(),
        "rows": len(result), "request_id_column": request_id_column,
        "model_version": None if model_version is None else str(model_version),
        "input_sha256": sha256(_data_file(input_path)),
        "history_sha256": sha256(_data_file(history_path)) if history_path is not None else None,
        "model_mlmodel_sha256": sha256(Path(model_path) / "MLmodel"),
        "model_tags": (definition.get("metadata") or {}).get("model_factory_tags", {}),
        "predictions_sha256": sha256(output / "predictions.parquet"),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "limitations": ["Predictions are not labels; join observed outcomes later by request ID for monitoring."],
    }
    write_json(output / "runinfo.json", info)
    return info


def json_value(value):
    """Convert pandas/numpy scalars into strict JSON values (NaN becomes null)."""
    import numpy as np
    import pandas as pd

    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    return value


def _image_rows(scenario: dict, prepared: Path, split: str, rows: int):
    import pandas as pd

    from .vision import _inside

    folder = Path(prepared) / split
    annotations = folder / "annotations.jsonl"
    if not annotations.is_file():
        raise FileNotFoundError(f"Prepared image split has no annotations.jsonl: {folder}")
    records = [json.loads(line) for line in annotations.read_text(encoding="utf-8").splitlines() if line.strip()][:rows]
    task = scenario["task"]
    frame = pd.DataFrame({
        IMAGE_COLUMN: [base64.b64encode(_inside(folder, row["image"]).read_bytes()).decode("ascii") for row in records],
        label_column(scenario): [row["label"] if task == "image_classification" else json.dumps(row["label"])
                                 for row in records],
    })
    return frame


def sample_requests(scenario: dict, prepared: Path, output: Path, *, rows: int = 10, split: str = "test",
                    generated_at: datetime | None = None) -> dict:
    """Create reviewed demo requests from a held-out split, keeping labels in a separate file."""
    import pandas as pd

    scenario = validate_scenario(scenario)
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
        raise ValueError("rows must be a positive integer")
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    generated = generated_at or datetime.now(timezone.utc)
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    output = _empty_output(output, "Sample request")
    target = label_column(scenario)
    if scenario["task"].startswith("image_"):
        frame = _image_rows(scenario, prepared, split, rows)
    else:
        frame = read_frame(Path(prepared) / split).head(rows).reset_index(drop=True)
    if frame.empty:
        raise ValueError(f"Prepared {split} split has no rows to sample")
    columns = model_columns(scenario)
    missing = set(columns + [target]) - set(frame.columns)
    if missing:
        raise ValueError(f"Prepared split is missing columns: {sorted(missing)}")
    identifiers = [f"{scenario['name']}-{split}-{index:06d}" for index in range(len(frame))]
    requests = frame.loc[:, columns].copy()
    requests.insert(0, REQUEST_ID, identifiers)
    labels = pd.DataFrame({REQUEST_ID: identifiers, target: frame[target].to_numpy(),
                           "observed_at": pd.Timestamp(generated)})
    output.mkdir(parents=True, exist_ok=True)
    requests.to_parquet(output / "requests.parquet", index=False)
    labels.to_parquet(output / "labels.parquet", index=False)
    records = [{column: json_value(value) for column, value in row.items()}
               for row in requests.loc[:, columns].to_dict("records")]
    events = [{EVENT_ID: identifier, EVENT_TIME: (generated + timedelta(milliseconds=index)).isoformat(), **record}
              for index, (identifier, record) in enumerate(zip(identifiers, records))]
    (output / "events.jsonl").write_text("".join(json.dumps(event, allow_nan=False) + "\n" for event in events),
                                         encoding="utf-8")
    write_json(output / "online-request.json", {"input_data": {
        "columns": columns, "index": list(range(len(records))),
        "data": [[record[column] for column in columns] for record in records],
    }})
    if scenario["task"] == "forecasting":
        history_split = {"test": "validation", "validation": "train"}.get(split)
        if history_split is not None:
            history = read_frame(Path(prepared) / history_split)
            history.loc[:, list(dict.fromkeys(columns + [target]))].to_parquet(output / "history.parquet", index=False)
    files = {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file()}
    manifest = {
        "schema": "ml-model-factory-sample-requests/v1", "scenario": scenario["name"], "task": scenario["task"],
        "split": split, "rows": len(requests), "request_id_column": REQUEST_ID, "columns": columns,
        "generated_at": generated.isoformat(), "files": files,
        "notes": [
            "Requests come from a held-out prepared split for demonstrations and contract tests.",
            "labels.parquet holds the held-out truth for monitoring demos; observed_at is the generation time.",
            "Never send labels to a model or treat predictions as observed outcomes.",
        ],
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def _score_command(args):
    return score_file(
        load_json(args.scenario), args.model, args.input, args.output, mode=args.mode,
        history_path=args.history, request_id_column=args.request_id_column, model_version=args.model_version,
    )


def _sample_command(args):
    return sample_requests(load_json(args.scenario), args.prepared, args.output, rows=args.rows, split=args.split)


def add_commands(commands) -> None:
    score = commands.add_parser("score", help="Score unlabeled CSV/Parquet requests with a local MLflow model")
    score.add_argument("--scenario", required=True, type=Path)
    score.add_argument("--model", required=True, type=Path)
    score.add_argument("--input", required=True, type=Path)
    score.add_argument("--output", required=True, type=Path)
    score.add_argument("--mode", choices=MODES, help="Required for external/AutoML artifacts without factory metadata")
    score.add_argument("--history", type=Path, help="Observed labeled history for AutoML forecasting only")
    score.add_argument("--request-id-column", default=REQUEST_ID)
    score.add_argument("--model-version", help="Immutable registered model version recorded with predictions")
    score.set_defaults(handler=_score_command)
    sample = commands.add_parser("sample-requests", help="Create demo requests/labels/events from a held-out split")
    sample.add_argument("--scenario", required=True, type=Path)
    sample.add_argument("--prepared", required=True, type=Path)
    sample.add_argument("--output", required=True, type=Path)
    sample.add_argument("--rows", type=int, default=10)
    sample.add_argument("--split", choices=SPLITS, default="test")
    sample.set_defaults(handler=_sample_command)
