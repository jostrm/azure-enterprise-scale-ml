import base64
import json
import shutil
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import sys

import pandas as pd
import pytest

from ml_model_factory.inference import IMAGE_COLUMN, load_scorer
from ml_model_factory.vision import prepare_vision
from ml_model_factory.vision_automl import AutoMLVisionScorer, evaluate_automl_vision, normalize_predictions, to_automl_frame


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace():
    path = ROOT / "ml-environment" / ".vision-automl-test-artifacts" / uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()


def image(path, index):
    Image = pytest.importorskip("PIL.Image")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), (index * 15 % 255, index * 7 % 255, index * 9 % 255)).save(path)


def scenario(task):
    return {
        "name": "fixture-automl-images", "task": task,
        "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/images", "file": ".", "version": 1},
        "vision": {"format": "jsonl", "image_root": "."},
        "split": {"test_size": .2, "validation_size": .2, "seed": 7},
        "quality": {},
    }


def raw_jsonl(root, task):
    rows = []
    for i in range(10):
        image(root / f"{i}.png", i)
        if task == "image_classification":
            label = ["cat", "dog"][i % 2]
        elif task == "image_classification_multilabel":
            label = ["cat", "dog"] if i % 2 else ["cat"]
        else:
            obj = {"label": "cat", "topX": .1, "topY": .1, "bottomX": .8, "bottomY": .8}
            if task == "image_instance_segmentation":
                obj = {"label": "cat", "polygon": [[.1, .1, .8, .1, .8, .8, .1, .8]]}
            label = [obj]
        rows.append({"image_url": f"{i}.png", "label": label})
    path = root / "annotations.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def model_dir(path):
    path.mkdir()
    (path / "MLmodel").write_text("flavors:\n  python_function: {}\nmetadata:\n  model_factory_tags: {}\n", encoding="utf-8")
    return path


class FakeModel:
    def __init__(self, outputs):
        self.outputs = outputs
        self.seen_columns = None

    def predict(self, frame):
        self.seen_columns = list(frame.columns)
        return self.outputs[:len(frame)]


def test_to_automl_frame_and_scorer_normalize_documented_outputs():
    encoded = base64.b64encode(b"image").decode("ascii")
    frame = to_automl_frame(pd.DataFrame({IMAGE_COLUMN: [encoded]}))
    assert list(frame.columns) == ["image"]
    assert frame.iloc[0, 0] == encoded
    assert normalize_predictions("image_classification", [{"labels": ["a", "b"], "probs": [0.2, 0.8]}]) == ["b"]
    assert normalize_predictions("image_classification_multilabel",
                                 pd.DataFrame({"labels": [["a", "b"]], "probs": [[0.6, 0.4]]}),
                                 threshold=.5) == ['["a"]']
    detected = normalize_predictions("image_object_detection", [{"boxes": [{
        "box": {"topX": .1, "topY": .2, "bottomX": .3, "bottomY": .4}, "label": "a", "score": .9}]}])
    assert json.loads(detected[0])["label_names"] == ["a"]


@pytest.mark.parametrize("raw,match", [
    ([{"labels": ["a"], "probs": [1.2]}], "probabilities"),
    ([{"labels": ["a"], "probs": [0.5, 0.5]}], "lengths"),
    ([{"boxes": [{"box": {"topX": .3, "topY": .2, "bottomX": .1, "bottomY": .4}, "label": "a", "score": .9}]}], "nonempty"),
    ([{"boxes": [{"box": {"topX": .1, "topY": .2, "bottomX": .3, "bottomY": .4}, "label": "a", "score": float("nan")}]}], "score"),
])
def test_malformed_outputs_fail_closed(raw, match):
    task = "image_classification" if "labels" in raw[0] else "image_object_detection"
    with pytest.raises(ValueError, match=match):
        normalize_predictions(task, raw)


def test_automl_vision_scorer_and_load_scorer(workspace):
    model = model_dir(workspace / "model")
    fake = FakeModel([{"labels": ["cat", "dog"], "probs": [.9, .1]}])
    scorer = AutoMLVisionScorer(scenario("image_classification"), model=model_dir(workspace / "unused"), threshold=.5)
    scorer.model = fake
    encoded = base64.b64encode(b"image").decode("ascii")
    assert list(scorer.predict(pd.DataFrame({IMAGE_COLUMN: [encoded]}))) == ["cat"]
    assert fake.seen_columns == ["image"]
    with patch("mlflow.pyfunc.load_model", return_value=fake):
        assert isinstance(load_scorer(scenario("image_classification"), model, mode="automl"), AutoMLVisionScorer)


def _outputs_from_rows(task, rows):
    outputs = []
    for row in rows:
        if task == "image_classification":
            outputs.append({"labels": ["cat", "dog"], "probs": [1.0, 0.0] if row["label"] == "cat" else [0.0, 1.0]})
        elif task == "image_classification_multilabel":
            labels = ["cat", "dog"]
            outputs.append({"labels": labels, "probs": [1.0 if label in row["label"] else 0.0 for label in labels]})
        else:
            boxes = []
            for obj in row["label"]:
                if task == "image_instance_segmentation":
                    xs = [value for poly in obj["polygons"] for value in poly[::2]]
                    ys = [value for poly in obj["polygons"] for value in poly[1::2]]
                    box = {"topX": min(xs) / row["width"], "topY": min(ys) / row["height"],
                           "bottomX": max(xs) / row["width"], "bottomY": max(ys) / row["height"]}
                    polygon = [[value / (row["width"] if i % 2 == 0 else row["height"]) for i, value in enumerate(poly)]
                               for poly in obj["polygons"]]
                    boxes.append({"box": box, "label": obj["label"], "score": .99, "polygon": polygon})
                else:
                    x1, y1, x2, y2 = obj["box"]
                    boxes.append({"box": {"topX": x1 / row["width"], "topY": y1 / row["height"],
                                          "bottomX": x2 / row["width"], "bottomY": y2 / row["height"]},
                                  "label": obj["label"], "score": .99})
            outputs.append({"boxes": boxes})
    return outputs


@pytest.mark.parametrize("task", ["image_classification", "image_classification_multilabel",
                                 "image_object_detection", "image_instance_segmentation"])
def test_evaluate_automl_vision_writes_quality_gate_and_evidence(task, workspace):
    if task.endswith(("detection", "segmentation")):
        pytest.importorskip("torchmetrics")
        pytest.importorskip("pycocotools")
    config = scenario(task)
    prepare_vision(config, raw_jsonl(workspace / "raw", task), workspace / "prepared")
    rows = [json.loads(line) for line in (workspace / "prepared" / "test" / "annotations.jsonl").read_text().splitlines()]
    report = evaluate_automl_vision(
        config, workspace / "prepared", model_dir(workspace / "model"), workspace / "report",
        model=FakeModel(_outputs_from_rows(task, rows)),
    )
    assert report["metrics"]
    assert json.loads((workspace / "report" / "quality-gate.json").read_text())["passed"] is True
    assert (workspace / "report" / "comparison.json").is_file()
    assert "Documented Azure AutoML image schema adapter" in (workspace / "report" / "responsible-ai.json").read_text()


def test_azureml_evaluate_dispatches_automl_images(workspace):
    from scripts import azureml_evaluate

    config = scenario("image_classification")
    prepare_vision(config, raw_jsonl(workspace / "raw", "image_classification"), workspace / "prepared")
    scenario_path = workspace / "scenario.json"
    scenario_path.write_text(json.dumps(config), encoding="utf-8")
    model = model_dir(workspace / "model")
    report = workspace / "report"
    args = ["azureml_evaluate.py", "--mode", "automl", "--scenario", str(scenario_path),
            "--prepared", str(workspace / "prepared"), "--model", str(model), "--output", str(report)]

    def fake_evaluator(scenario, prepared, model_dir, output):
        output.mkdir()
        (output / "metrics.json").write_text(json.dumps({"accuracy": 1.0}), encoding="utf-8")
        (output / "quality-gate.json").write_text(json.dumps({"passed": True}), encoding="utf-8")

    with patch.object(sys, "argv", args), patch.object(azureml_evaluate, "subprocess") as subprocess_mock, \
            patch("ml_model_factory.vision_automl.evaluate_automl_vision", side_effect=fake_evaluator) as evaluator:
        azureml_evaluate.main()
    evaluator.assert_called_once()
    subprocess_mock.run.assert_not_called()
    assert json.loads((report / "lineage.json").read_text())["mode"] == "automl"
    assert (report / "comparison.json").is_file()
