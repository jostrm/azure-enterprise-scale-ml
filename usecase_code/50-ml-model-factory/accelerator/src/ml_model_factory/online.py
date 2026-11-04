"""Online request/response contract shared by Azure ML scoring scripts and local hosts."""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from . import inference
from .config import load_json, validate_scenario, write_json

MAX_PAYLOAD_BYTES = 5 * 1024 * 1024


class RequestError(ValueError):
    """Typed client error safe to expose to endpoint callers."""

    status_code = 400


class BadRequest(RequestError):
    pass


@dataclass(frozen=True)
class ParsedRequest:
    frame: object
    request_ids: list[str]
    history: object | None = None


def _json_payload(payload):
    if isinstance(payload, bytes):
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise ValueError("Request payload is too large")
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("Request payload is too large")
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("Request payload must be a JSON object")
    if len(json.dumps(payload, default=str).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("Request payload is too large")
    return payload


def _split_frame(value):
    import pandas as pd

    if not isinstance(value, dict):
        raise ValueError("dataframe_split/input_data split payload must be an object")
    columns = value.get("columns")
    data = value.get("data")
    if not isinstance(columns, list) or not isinstance(data, list):
        raise ValueError("Split payload requires columns and data arrays")
    return pd.DataFrame(data, columns=columns)


def _records_frame(value):
    import pandas as pd

    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Records payload must be a list of JSON objects")
    return pd.DataFrame(value)


def _frame_from_payload(payload: dict, *, root: bool):
    if root and "input_data" in payload:
        value = payload["input_data"]
        if isinstance(value, dict) and {"columns", "data"}.issubset(value):
            return _split_frame(value)
        return _records_frame(value)
    if "dataframe_split" in payload:
        return _split_frame(payload["dataframe_split"])
    if "dataframe_records" in payload:
        return _records_frame(payload["dataframe_records"])
    if not root and {"columns", "data"}.issubset(payload):
        return _split_frame(payload)
    if not root and "input_data" in payload:
        return _frame_from_payload(payload, root=True)
    raise ValueError("Request must contain input_data, dataframe_split, or dataframe_records")


def _parsed_request(payload, scenario: dict, *, max_rows: int = 1000) -> ParsedRequest:
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    scenario = validate_scenario(scenario)
    payload = _json_payload(payload)
    frame = _frame_from_payload(payload, root=True)
    rows = len(frame)
    if rows < 1:
        raise ValueError("Request must contain at least one row")
    if rows > max_rows:
        raise ValueError(f"Request row count {rows} exceeds max_rows={max_rows}")
    target = inference.label_column(scenario)
    if target in frame.columns:
        raise ValueError("Inference requests must not contain labels")
    columns = inference.model_columns(scenario)
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"Request is missing model columns: {sorted(missing)}")
    if inference.REQUEST_ID in frame.columns:
        request_ids = [str(value) for value in frame[inference.REQUEST_ID].tolist()]
    elif "request_ids" in payload:
        if not isinstance(payload["request_ids"], list) or len(payload["request_ids"]) != rows:
            raise ValueError("request_ids must be a list with one value per request row")
        request_ids = [str(value) for value in payload["request_ids"]]
    else:
        request_ids = [f"req-{uuid4().hex}" for _ in range(rows)]
    result = frame.loc[:, columns].copy()
    result.insert(0, inference.REQUEST_ID, request_ids)
    inference.validate_request_ids(result, inference.REQUEST_ID)
    history = None
    if "history" in payload:
        if scenario["task"] != "forecasting":
            raise ValueError("history is only valid for forecasting requests")
        history_value = payload["history"]
        if isinstance(history_value, list):
            history = _records_frame(history_value)
        else:
            history = _frame_from_payload(_json_payload(history_value), root=True)
        history_missing = set(columns + [target]) - set(history.columns)
        if history_missing:
            raise ValueError(f"history is missing required columns: {sorted(history_missing)}")
        history = history.loc[:, list(dict.fromkeys(columns + [target]))].copy()
    result.attrs["request_ids"] = request_ids
    result.attrs["history"] = history
    return ParsedRequest(result, request_ids, history)


def parse_request(payload, scenario: dict, *, max_rows: int = 1000):
    """Parse supported online JSON formats into request_id plus model columns."""
    return _parsed_request(payload, scenario, max_rows=max_rows).frame


class ScorerProvider(ABC):
    @abstractmethod
    def scorer_for(self, history=None) -> inference.ModelScorer:
        """Return a scorer for this request."""


class StaticScorerProvider(ScorerProvider):
    def __init__(self, scorer: inference.ModelScorer):
        self.scorer = scorer

    def scorer_for(self, history=None) -> inference.ModelScorer:
        if history is not None:
            raise ValueError("External history is only accepted by AutoML forecasting")
        return self.scorer


class AutoMLForecastScorerProvider(ScorerProvider):
    def __init__(self, scenario: dict, model_path: Path, *, model=None):
        from .serving import load_forecaster

        self.scenario = validate_scenario(scenario)
        self.model_path = Path(model_path)
        self.model = model if model is not None else load_forecaster(self.model_path)

    def scorer_for(self, history=None) -> inference.ModelScorer:
        if history is None:
            raise ValueError("AutoML forecasting online requests require history")
        return inference.AutoMLForecastScorer(self.scenario, self.model_path, history, model=self.model)


def provider_for(scenario: dict, model_path: Path, *, mode: str | None = None) -> ScorerProvider:
    scenario = validate_scenario(scenario)
    mode = mode or inference.detect_mode(Path(model_path))
    if scenario["task"] == "forecasting" and mode == "automl":
        return AutoMLForecastScorerProvider(scenario, Path(model_path))
    return StaticScorerProvider(inference.load_scorer(scenario, Path(model_path), mode=mode))


class OnlineService:
    def __init__(self, scenario: dict, provider: ScorerProvider, *, model_version=None, max_rows: int = 1000):
        self.scenario = validate_scenario(scenario)
        self.provider = provider
        self.model_version = model_version
        self.max_rows = max_rows

    def handle(self, payload) -> dict:
        try:
            parsed = _parsed_request(payload, self.scenario, max_rows=self.max_rows)
            scorer = self.provider.scorer_for(parsed.history)
            scored = inference.score_frame(scorer, parsed.frame, model_version=self.model_version)
        except RequestError:
            raise
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc
        return {
            "predictions": [
                {key: inference.json_value(value) for key, value in row.items()}
                for row in scored.to_dict("records")
            ],
            "request_ids": parsed.request_ids,
            "model_version": None if self.model_version is None else str(self.model_version),
            "rows": len(scored),
        }


_SERVICE: OnlineService | None = None


def _find_model_dir(root: Path) -> Path:
    root = Path(root)
    if (root / "MLmodel").is_file():
        return root
    matches = [path.parent for path in root.glob("*/*/MLmodel")] + [path.parent for path in root.glob("*/MLmodel")]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(f"Could not locate a single MLflow MLmodel under AZUREML_MODEL_DIR={root}")


def _config_dir() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent, Path.cwd()):
        if (candidate / "scenario.json").is_file():
            return candidate
    raise FileNotFoundError("scenario.json was not found in the scoring code bundle")


def _resolved_model_version(serving: dict, model_dir: Path, azureml_model_dir: Path):
    version = serving.get("model_version")
    if version is None or not str(version).startswith("REPLACE_WITH_"):
        return version
    try:
        relative = model_dir.resolve().relative_to(azureml_model_dir.resolve())
    except ValueError:
        relative = Path()
    if len(relative.parts) >= 2:
        return relative.parts[-1]
    raise ValueError("serving.json contains an unresolved model_version placeholder and AZUREML_MODEL_DIR is not .../<model-name>/<version>")


def init() -> None:
    global _SERVICE
    code = _config_dir()
    scenario = load_json(code / "scenario.json")
    serving = load_json(code / "serving.json") if (code / "serving.json").is_file() else {}
    azureml_model_dir = Path(os.environ["AZUREML_MODEL_DIR"])
    model_dir = _find_model_dir(azureml_model_dir)
    model_version = _resolved_model_version(serving, model_dir, azureml_model_dir)
    provider = provider_for(scenario, model_dir, mode=serving.get("mode"))
    _SERVICE = OnlineService(
        scenario, provider, model_version=model_version, max_rows=int(serving.get("max_rows", 1000))
    )


def _aml_response(body: dict, status_code: int):
    """Return AMLResponse when available; otherwise include status in the JSON fallback."""
    text = json.dumps(body, allow_nan=False)
    for name in (
        "azureml_inference_server_http.api.aml_response",
        "azureml.contrib.services.aml_response",
    ):
        try:
            module, attr = name, "AMLResponse"
            imported = __import__(module, fromlist=[attr])
            return getattr(imported, attr)(text, status_code)
        except Exception:
            continue
    return {**body, "status": status_code}


def run(raw_data):
    if _SERVICE is None:
        raise RuntimeError("Online scoring service is not initialized")
    try:
        return _SERVICE.handle(raw_data)
    except RequestError as exc:
        return _aml_response({"error": "bad_request", "message": str(exc)}, exc.status_code)
    except Exception:
        logging.getLogger(__name__).exception("Online scoring failed")
        return _aml_response({"error": "server_error", "message": "Online scoring failed"}, 500)


def history_payload(history_frame) -> dict:
    """Convert a labeled history DataFrame into the online request history block."""
    return {"dataframe_records": [
        {key: inference.json_value(value) for key, value in row.items()}
        for row in history_frame.to_dict("records")
    ]}


def attach_history(payload: dict, history_frame) -> dict:
    result = dict(payload)
    result["history"] = history_payload(history_frame)
    return result


def local_online_test(scenario: dict, model_path: Path, request_path: Path, *, mode: str | None = None,
                      history_path: Path | None = None, model_version=None) -> dict:
    scenario = validate_scenario(scenario)
    payload = json.loads(Path(request_path).read_text(encoding="utf-8"))
    if history_path is not None:
        from .data import read_frame
        payload = attach_history(payload, read_frame(history_path))
    service = OnlineService(scenario, provider_for(scenario, model_path, mode=mode), model_version=model_version)
    response = service.handle(payload)
    if response["rows"] != len(response["predictions"]):
        raise ValueError("Online contract returned a different number of predictions than request rows")
    return response


def _online_test_command(args):
    result = local_online_test(
        load_json(args.scenario), args.model, args.request, mode=args.mode,
        history_path=args.history, model_version=args.model_version,
    )
    if args.output:
        write_json(args.output, result)
    return result


def add_commands(commands) -> None:
    parser = commands.add_parser("online-test", help="Run the online scoring contract in-process")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--mode", choices=inference.MODES)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--model-version")
    parser.add_argument("--output", type=Path)
    parser.set_defaults(handler=_online_test_command)
