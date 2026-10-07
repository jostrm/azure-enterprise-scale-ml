"""AutoML image MLflow adapter and held-out evaluator.

Relies on Microsoft Learn's documented AutoML image online schema:
https://learn.microsoft.com/en-us/azure/machine-learning/reference-automl-images-schema
and deployment flow:
https://learn.microsoft.com/en-us/azure/machine-learning/how-to-auto-train-image-models

The docs specify input column ``image`` with base64 image strings and task-specific
outputs. Public docs do not precisely define local ``mlflow.pyfunc.predict`` return
types, so this adapter accepts DataFrame/list/dict/JSON variants of that schema and
fails closed on unknown or malformed values.
"""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path

from .config import quality_gate, validate_scenario, write_json
from .inference import IMAGE_COLUMN, ModelScorer, check_predictions


DOC_URLS = [
    "https://learn.microsoft.com/en-us/azure/machine-learning/reference-automl-images-schema",
    "https://learn.microsoft.com/en-us/azure/machine-learning/how-to-auto-train-image-models",
]


def to_automl_frame(features):
    """Return AutoML's documented input DataFrame with one ``image`` column."""
    import pandas as pd

    if IMAGE_COLUMN not in features:
        raise ValueError(f"AutoML vision input requires {IMAGE_COLUMN}")
    values = []
    for value in features[IMAGE_COLUMN]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("AutoML vision image values must be nonempty base64 strings")
        base64.b64decode(value, validate=True)
        values.append(value)
    return pd.DataFrame({"image": values})


def _task_kind(task: str) -> str:
    return {
        "image_classification": "multiclass",
        "image_classification_multilabel": "multilabel",
        "image_object_detection": "detection",
        "image_instance_segmentation": "segmentation",
    }.get(task, task)


def _records(raw):
    import pandas as pd

    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, pd.DataFrame):
        if len(raw.columns) == 1 and raw.columns[0] in {"prediction", "predictions", 0}:
            return [_parse_value(value) for value in raw.iloc[:, 0].tolist()]
        return [_parse_value(row) for row in raw.to_dict("records")]
    if isinstance(raw, pd.Series):
        return [_parse_value(value) for value in raw.tolist()]
    if isinstance(raw, dict):
        if "predictions" in raw and isinstance(raw["predictions"], list):
            return [_parse_value(value) for value in raw["predictions"]]
        return [_parse_value(raw)]
    if isinstance(raw, list):
        return [_parse_value(value) for value in raw]
    raise ValueError("Unsupported AutoML vision prediction container")


def _parse_value(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("Each AutoML vision prediction must be an object")
    return value


def _probabilities(record):
    labels, probs = record.get("labels"), record.get("probs")
    if not isinstance(labels, list) or not labels or any(not isinstance(label, str) or not label for label in labels):
        raise ValueError("Classification prediction requires nonempty string labels")
    if not isinstance(probs, list) or len(probs) != len(labels):
        raise ValueError("Classification prediction probs and labels lengths differ")
    values = [float(value) for value in probs]
    if any(not math.isfinite(value) or value < 0 or value > 1 for value in values):
        raise ValueError("Classification probabilities must be finite values in [0, 1]")
    return labels, values


def _box_value(value, key):
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        raise ValueError(f"Box coordinate {key} must be a finite normalized value in [0, 1]")
    return number


def _normalize_boxes(record, *, segmentation: bool):
    boxes = record.get("boxes")
    if not isinstance(boxes, list):
        raise ValueError("Detection prediction requires a boxes list")
    converted = []
    for item in boxes:
        if not isinstance(item, dict):
            raise ValueError("Each detection must be an object")
        unknown = set(item) - {"box", "label", "score", "polygon"}
        if unknown:
            raise ValueError(f"Unknown detection keys: {sorted(unknown)}")
        box = item.get("box")
        if not isinstance(box, dict) or set(box) != {"topX", "topY", "bottomX", "bottomY"}:
            raise ValueError("Detection box must contain topX/topY/bottomX/bottomY")
        normalized = {key: _box_value(box[key], key) for key in ("topX", "topY", "bottomX", "bottomY")}
        if not (normalized["topX"] < normalized["bottomX"] and normalized["topY"] < normalized["bottomY"]):
            raise ValueError("Detection box must be nonempty")
        label = item.get("label")
        score = float(item.get("score"))
        if not isinstance(label, str) or not label:
            raise ValueError("Detection label must be a nonempty string")
        if not math.isfinite(score) or score < 0 or score > 1:
            raise ValueError("Detection score must be a finite value in [0, 1]")
        converted_item = {"box": normalized, "label": label, "score": score}
        if segmentation:
            polygon = item.get("polygon")
            if not isinstance(polygon, list) or not polygon:
                raise ValueError("Instance segmentation prediction requires polygons")
            for segment in polygon:
                if not isinstance(segment, list) or len(segment) < 6 or len(segment) % 2:
                    raise ValueError("Each polygon segment requires at least three x/y pairs")
                coords = [float(value) for value in segment]
                if any(not math.isfinite(value) or value < 0 or value > 1 for value in coords):
                    raise ValueError("Polygon coordinates must be finite normalized values in [0, 1]")
            converted_item["polygon"] = polygon
        elif "polygon" in item:
            raise ValueError("Object detection predictions must not include polygon")
        converted.append(converted_item)
    return converted


def normalize_predictions(task, raw, *, threshold=0.5):
    """Normalize AutoML image output to the factory custom pyfunc representation."""
    kind = _task_kind(task)
    if kind not in {"multiclass", "multilabel", "detection", "segmentation"}:
        raise ValueError(f"Unsupported AutoML vision task: {task}")
    threshold = float(threshold)
    if not math.isfinite(threshold) or threshold < 0 or threshold > 1:
        raise ValueError("AutoML multilabel threshold must be finite and in [0, 1]")
    predictions = []
    for record in _records(raw):
        allowed = {"probs", "labels"} if kind in {"multiclass", "multilabel"} else {"boxes"}
        unknown = set(record) - allowed
        if unknown:
            raise ValueError(f"Unknown AutoML vision prediction keys: {sorted(unknown)}")
        if kind == "multiclass":
            labels, probs = _probabilities(record)
            predictions.append(labels[max(range(len(probs)), key=probs.__getitem__)])
        elif kind == "multilabel":
            labels, probs = _probabilities(record)
            predictions.append(json.dumps([label for label, prob in zip(labels, probs) if prob >= threshold]))
        else:
            boxes = _normalize_boxes(record, segmentation=kind == "segmentation")
            payload = {
                "box_format": "normalized_xyxy",
                "boxes": [[box["box"]["topX"], box["box"]["topY"], box["box"]["bottomX"], box["box"]["bottomY"]]
                          for box in boxes],
                "scores": [box["score"] for box in boxes],
                "label_names": [box["label"] for box in boxes],
            }
            if kind == "segmentation":
                payload["polygons"] = [box["polygon"] for box in boxes]
            predictions.append(json.dumps(payload, allow_nan=False))
    return predictions


class AutoMLVisionScorer(ModelScorer):
    """Score image rows with an AutoML image MLflow pyfunc using documented schemas."""

    def __init__(self, scenario, model_path=None, *, model=None, threshold=None):
        super().__init__(scenario, "automl")
        if not self.scenario["task"].startswith("image_"):
            raise ValueError("AutoMLVisionScorer requires an image scenario")
        self.model_path = Path(model_path) if model_path is not None else None
        self.model = model
        self.threshold = threshold if threshold is not None else self.scenario.get("vision", {}).get("automl_threshold", 0.5)

    def _model(self):
        if self.model is None:
            if self.model_path is None:
                raise ValueError("Provide a model_path or injected AutoML image model")
            import mlflow.pyfunc

            self.model = mlflow.pyfunc.load_model(str(self.model_path))
        return self.model

    def predict(self, features):
        frame = to_automl_frame(features)
        raw = self._model().predict(frame)
        return check_predictions(normalize_predictions(self.scenario["task"], raw, threshold=self.threshold), len(features))


def _read_test_rows(prepared_dir: Path):
    folder = Path(prepared_dir) / "test"
    rows = [json.loads(line) for line in (folder / "annotations.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if not rows:
        raise ValueError("AutoML vision evaluation requires at least one held-out image")
    return folder, rows


def _image_features(folder, rows):
    import pandas as pd

    from .vision import _inside

    return pd.DataFrame({
        IMAGE_COLUMN: [base64.b64encode(_inside(folder, row["image"]).read_bytes()).decode("ascii") for row in rows]
    })


def _label_sets(rows, classes):
    return [[int(label in row["label"]) for label in classes] for row in rows]


def _mask(size, polygons, *, normalized: bool):
    import numpy as np
    from PIL import Image, ImageDraw

    mask = Image.new("L", size)
    drawer = ImageDraw.Draw(mask)
    width, height = size if normalized else (1, 1)
    for polygon in polygons:
        points = [(float(x) * width, float(y) * height) for x, y in zip(polygon[::2], polygon[1::2])]
        drawer.polygon(points, fill=1)
    return np.asarray(mask, dtype=bool)


def _detection_tensors(task, rows, predictions, folder):
    import numpy as np
    import torch
    from PIL import Image
    from torchmetrics.detection.mean_ap import MeanAveragePrecision

    from .vision import _inside

    names = sorted({obj["label"] for row in rows for obj in row["label"]} |
                   {label for pred in predictions for label in json.loads(pred).get("label_names", [])})
    if not names:
        raise ValueError("Detection evaluation has no labels")
    label_id = {name: index + 1 for index, name in enumerate(names)}
    metric = MeanAveragePrecision(iou_type="segm" if task == "image_instance_segmentation" else "bbox", class_metrics=True)
    errors = []
    for index, (row, pred_text) in enumerate(zip(rows, predictions)):
        with Image.open(_inside(folder, row["image"])) as opened:
            width, height = opened.size
        truth_boxes = torch.tensor([obj["box"] for obj in row["label"]], dtype=torch.float32).reshape(-1, 4)
        target = {
            "boxes": truth_boxes,
            "labels": torch.tensor([label_id[obj["label"]] for obj in row["label"]], dtype=torch.int64),
            "image_id": torch.tensor(index),
        }
        pred = json.loads(pred_text)
        boxes = [[box[0] * width, box[1] * height, box[2] * width, box[3] * height] for box in pred["boxes"]]
        prediction = {
            "boxes": torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4),
            "scores": torch.tensor(pred["scores"], dtype=torch.float32),
            "labels": torch.tensor([label_id[label] for label in pred["label_names"]], dtype=torch.int64),
        }
        if task == "image_instance_segmentation":
            prediction["masks"] = torch.tensor(np.asarray([_mask((width, height), poly, normalized=True)
                                                           for poly in pred.get("polygons", [])]),
                                               dtype=torch.bool).reshape(-1, height, width)
            target["masks"] = torch.tensor(np.asarray([_mask((width, height), obj["polygons"], normalized=False)
                                                       for obj in row["label"]]),
                                           dtype=torch.bool).reshape(-1, height, width)
        metric.update([prediction], [target])
        errors.append({"image": row["image"], "true_instances": len(row["label"]),
                       "predicted_instances_at_0_5": int((prediction["scores"] >= .5).sum())})
    computed = metric.compute()
    metrics = {key: float(computed[key]) for key in ("map", "map_50", "map_75", "mar_100")
               if torch.isfinite(computed[key]) and float(computed[key]) >= 0}
    if "map" not in metrics:
        raise ValueError("COCO mAP undefined for this held-out split; no quality claim can be made")
    return names, metrics, errors


def evaluate_automl_vision(scenario, prepared_dir, model_dir, output_dir, *, model=None, threshold=None):
    """Evaluate an AutoML image MLflow model on prepared/test images."""
    import numpy as np
    from sklearn.metrics import accuracy_score, f1_score, hamming_loss

    scenario = validate_scenario(scenario)
    if not scenario["task"].startswith("image_"):
        raise ValueError("evaluate_automl_vision requires an image scenario")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    folder, rows = _read_test_rows(Path(prepared_dir))
    scorer = AutoMLVisionScorer(scenario, model_dir, model=model, threshold=threshold)
    predictions = list(scorer.predict(_image_features(folder, rows)))
    task = scenario["task"]
    errors = []
    if task == "image_classification":
        truth = [row["label"] for row in rows]
        metrics = {"accuracy": float(accuracy_score(truth, predictions)),
                   "f1_weighted": float(f1_score(truth, predictions, average="weighted", zero_division=0))}
        classes = sorted(set(truth) | set(predictions))
        errors = [{"image": row["image"], "actual": actual, "prediction": pred, "error": actual != pred}
                  for row, actual, pred in zip(rows, truth, predictions)]
    elif task == "image_classification_multilabel":
        classes = sorted({label for row in rows for label in row["label"]} |
                         {label for pred in predictions for label in json.loads(pred)})
        truth = np.asarray(_label_sets(rows, classes))
        pred = np.asarray([[int(label in json.loads(value)) for label in classes] for value in predictions])
        metrics = {"accuracy": float(accuracy_score(truth, pred)),
                   "f1_weighted": float(f1_score(truth, pred, average="weighted", zero_division=0)),
                   "hamming_loss": float(hamming_loss(truth, pred))}
        errors = [{"image": row["image"], "actual": row["label"], "prediction": json.loads(prediction),
                   "error": sorted(row["label"]) != sorted(json.loads(prediction))}
                  for row, prediction in zip(rows, predictions)]
    else:
        classes, metrics, errors = _detection_tensors(task, rows, predictions, folder)
    report = {
        "task": task, "mode": "automl", "test_rows": len(rows), "classes": classes, "metrics": metrics,
        "responsible_ai": {
            "tooling": "Documented Azure AutoML image schema adapter, sklearn metrics or torchmetrics COCO mAP",
            "sources": DOC_URLS,
            "azure_dashboard": "Not generated; image tasks are not claimed to support Azure tabular RAI components.",
            "limitations": [
                "Adapter accepts documented online scoring schema variants; exact local pyfunc DataFrame shape is not publicly specified.",
                "No saliency, fairness, causal, privacy, or clinical validation claim is made.",
                "Class mapping uses returned label strings, never model-position guesses.",
            ],
        },
    }
    write_json(output / "metrics.json", metrics)
    write_json(output / "responsible-ai.json", report)
    write_json(output / "image-errors.json", errors)
    try:
        quality_gate(metrics, scenario.get("quality", {}))
    except ValueError as exc:
        write_json(output / "quality-gate.json", {"passed": False, "reason": str(exc)})
        raise
    gate = {"passed": True, "limits": scenario.get("quality", {})}
    write_json(output / "quality-gate.json", gate)
    from .selection import build_evidence
    write_json(output / "comparison.json", build_evidence(scenario, Path(prepared_dir), Path(model_dir), metrics, gate))
    return report


def add_commands(commands) -> None:
    """No CLI subcommands; scoring is exposed through inference.load_scorer."""
