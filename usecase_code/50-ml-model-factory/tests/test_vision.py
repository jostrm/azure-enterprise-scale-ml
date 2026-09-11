"""Generated local images test adapters, not dataset quality or Kaggle accuracy."""

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from ml_model_factory.config import load_json, write_json
from ml_model_factory.vision import _source_records, evaluate_vision, prepare_vision, train_vision


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace():
    path = ROOT / ".test-artifacts" / uuid4().hex
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
    Image.new("RGB", (24, 24), (index * 11 % 255, index * 17 % 255, index * 23 % 255)).save(path)


def scenario(task, format_name):
    return {
        "name": "fixture-images", "task": task,
        "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/not-downloaded",
                    "file": ".", "version": 1, "license": "generated-test-fixture"},
        "vision": {"format": format_name, "image_root": ".", "device": "cpu", "pretrained": False,
                   "image_size": 32, "max_image_size": 64, "epochs": 1, "batch_size": 2,
                   "max_steps_per_epoch": 1, "num_threads": 1},
        "split": {"test_size": .2, "validation_size": .2, "seed": 42},
        "quality": {},
    }


def make_jsonl(root, task):
    rows = []
    for i in range(10):
        image(root / f"{i}.png", i)
        if task == "image_classification":
            labels = ["red", "blue"][i % 2]
        elif task.endswith("multilabel"):
            labels = ["red", "blue"] if i % 2 else ["red"]
        else:
            obj = {"label": "fruit", "topX": .1, "topY": .1, "bottomX": .8, "bottomY": .8}
            if task == "image_instance_segmentation":
                obj = {"label": "fruit", "polygon": [[.1, .1, .8, .1, .8, .8, .1, .8]]}
            labels = [obj]
        rows.append({"image_url": f"{i}.png", "label": labels})
    path = root / "annotations.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


@pytest.mark.parametrize("task", ["image_classification", "image_classification_multilabel",
                                 "image_object_detection", "image_instance_segmentation"])
def test_jsonl_preparation_and_relocation(task, workspace):
    source = make_jsonl(workspace / "raw", task)
    config = scenario(task, "jsonl")
    output = workspace / "prepared"
    manifest = prepare_vision(config, source, output)
    assert sum(manifest["split_rows"].values()) == 10
    assert manifest["automl_ready"] is False
    moved = workspace / "relocated"
    shutil.move(output, moved)
    seen = set()
    for name in ("train", "validation", "test"):
        rows = [json.loads(line) for line in (moved / name / "annotations.jsonl").read_text().splitlines()]
        for row in rows:
            assert row["sha256"] not in seen
            seen.add(row["sha256"])
            assert not Path(row["image"]).is_absolute()
            assert (moved / name / row["image"]).exists()
        automl = json.loads((moved / name / "data.jsonl").read_text().splitlines()[0])
        assert not Path(automl["image_url"]).is_absolute()
        if task == "image_instance_segmentation":
            assert set(automl["label"][0]) == {"label", "isCrowd", "polygon"}


def test_image_folder_and_remote_root(workspace):
    for i in range(10):
        image(workspace / "raw" / ("blue" if i % 2 else "red") / f"{i}.png", i)
    config = scenario("image_classification", "image_folder")
    config["vision"]["image_base_uri"] = "azureml://datastores/workspaceblobstore/paths/prepared/v1"
    manifest = prepare_vision(config, workspace / "raw", workspace / "prepared")
    assert manifest["automl_ready"]
    for split in ("train", "validation", "test"):
        row = json.loads((workspace / "prepared" / split / "data.jsonl").read_text().splitlines()[0])
        assert row["image_url"].startswith(config["vision"]["image_base_uri"] + "/" + split + "/images/")


def test_pascal_voc_boxes_and_multilabel(workspace):
    for i in range(10):
        image(workspace / f"{i}.png", i)
        xml = f"""<annotation><filename>{i}.png</filename>
        <object><name>apple</name><bndbox><xmin>1</xmin><ymin>1</ymin><xmax>12</xmax><ymax>12</ymax></bndbox></object>
        <object><name>banana</name><bndbox><xmin>13</xmin><ymin>13</ymin><xmax>24</xmax><ymax>24</ymax></bndbox></object></annotation>"""
        (workspace / f"{i}.xml").write_text(xml)
    config = scenario("image_object_detection", "pascal_voc")
    records = _source_records(config, workspace)
    assert records[0]["label"][0]["box"] == [0., 0., 12., 12.]
    config["task"] = "image_classification_multilabel"
    assert _source_records(config, workspace)[0]["label"] == ["apple", "banana"]
    config["task"] = "image_instance_segmentation"
    with pytest.raises(ValueError, match="cannot be used"):
        _source_records(config, workspace)


def test_coco_polygon_instance_masks_and_rle_rejection(workspace):
    image(workspace / "sample.png", 1)
    config = scenario("image_instance_segmentation", "coco")
    config["vision"]["annotations"] = "labels.json"
    coco = {
        "images": [{"id": 1, "file_name": "sample.png", "width": 24, "height": 24}],
        "categories": [{"id": 3, "name": "ship"}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 3, "bbox": [1, 1, 10, 10],
                         "segmentation": [[1, 1, 11, 1, 11, 11, 1, 11]], "iscrowd": 0}],
    }
    write_json(workspace / "labels.json", coco)
    record = _source_records(config, workspace)[0]
    assert record["label"][0]["polygons"] == coco["annotations"][0]["segmentation"]
    coco["annotations"][0]["segmentation"] = {"counts": "rle", "size": [24, 24]}
    write_json(workspace / "labels.json", coco)
    with pytest.raises(ValueError, match="RLE"):
        _source_records(config, workspace)


def test_untrusted_paths_and_conflicting_duplicates_rejected(workspace):
    source = make_jsonl(workspace / "raw", "image_classification")
    config = scenario("image_classification", "jsonl")
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    rows[0]["image_url"] = "../outside.png"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="safe dataset-relative"):
        prepare_vision(config, source, workspace / "prepared")
    source = make_jsonl(workspace / "raw", "image_classification")
    shutil.copyfile(workspace / "raw" / "0.png", workspace / "raw" / "1.png")
    with pytest.raises(ValueError, match="conflicting"):
        prepare_vision(config, source, workspace / "prepared")


def test_automl_model_adapter_is_explicitly_unsupported(workspace):
    with pytest.raises(ValueError, match="Unsupported AutoML"):
        evaluate_vision(scenario("image_object_detection", "jsonl"), workspace, workspace, workspace / "report")
    report = load_json(workspace / "report" / "responsible-ai.json")
    assert report["status"] == "unsupported-model-adapter"
    assert not (workspace / "report" / "metrics.json").exists()


@pytest.mark.parametrize("task", ["image_classification", "image_classification_multilabel",
                                 "image_object_detection", "image_instance_segmentation"])
def test_real_torchvision_optimizer_and_mlflow_roundtrip(task, workspace):
    pytest.importorskip("torch")
    pytest.importorskip("torchvision")
    pytest.importorskip("mlflow")
    pytest.importorskip("sklearn")
    pytest.importorskip("torchmetrics")
    pytest.importorskip("pycocotools")
    source = make_jsonl(workspace / "raw", task)
    config = scenario(task, "jsonl")
    prepared, model = workspace / "prepared", workspace / "model"
    prepare_vision(config, source, prepared)
    trained = train_vision(config, prepared, model)
    assert trained["optimizer_steps"] == 1
    assert len(trained["training_loss"]) == 1
    assert (model / "MLmodel").exists()
    report = evaluate_vision(config, prepared, model, workspace / "evaluation")
    assert report["test_rows"] >= 1
    assert report["metrics"]
    import base64
    import mlflow.pyfunc
    import pandas as pd

    relocated = workspace / "relocated-model"
    shutil.copytree(model, relocated)
    loaded = mlflow.pyfunc.load_model(str(relocated))
    encoded = base64.b64encode((workspace / "raw" / "0.png").read_bytes()).decode("ascii")
    scored = loaded.predict(pd.DataFrame({"image_base64": [encoded]}))
    assert len(scored) == 1 and isinstance(scored.iloc[0]["prediction"], str)
