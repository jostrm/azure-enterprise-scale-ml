"""Local image conversion and real, bounded torchvision training.

Prepared images and custom manifests are relocatable. AutoML manifests require
an explicitly configured immutable remote image root; local mount paths are
never presented as URLs that another Azure job could resolve.
"""

import json
import math
import random
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

from .config import load_json, quality_gate, safe_relative, validate_scenario, write_json
from .data import sha256


IMAGE_TASKS = {
    "image_classification", "image_classification_multilabel",
    "image_object_detection", "image_instance_segmentation",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def _inside(root, name):
    root = Path(root).resolve()
    path = (root / safe_relative(str(name))).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Image path escapes its dataset root: {name}")
    return path


def _box(label, x1, y1, x2, y2, width, height, polygons=None):
    coords = [float(x1), float(y1), float(x2), float(y2)]
    if not all(math.isfinite(x) for x in coords):
        raise ValueError("Bounding box coordinates must be finite")
    if not 0 <= coords[0] < coords[2] <= width or not 0 <= coords[1] < coords[3] <= height:
        raise ValueError(f"Bounding box outside image or empty: {coords} in {width}x{height}")
    result = {"label": str(label), "box": coords}
    if polygons is not None:
        if not isinstance(polygons, list) or not polygons:
            raise ValueError("Instance segmentation requires nonempty COCO polygons; RLE is not supported")
        for polygon in polygons:
            if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2:
                raise ValueError("A polygon requires at least three x/y coordinate pairs")
            if not all(isinstance(p, (int, float)) and math.isfinite(p) for p in polygon):
                raise ValueError("Polygon coordinates must be finite numbers")
            if not all(0 <= x <= width and 0 <= y <= height for x, y in zip(polygon[::2], polygon[1::2])):
                raise ValueError("Polygon coordinates are outside the image")
        result["polygons"] = polygons
    return result


def _source_records(scenario, input_path):
    from PIL import Image

    config = scenario["vision"]
    task = scenario["task"]
    input_path = Path(input_path).resolve()
    root = input_path if input_path.is_dir() else input_path.parent
    image_root = _inside(root, config.get("image_root", "."))
    format_name = config["format"]
    records = []

    def add(image, label):
        image = Path(image)
        with Image.open(image) as opened:
            width, height = opened.size
            opened.verify()
        records.append({"source": image, "label": label, "width": width, "height": height})

    if format_name == "image_folder":
        if task != "image_classification":
            raise ValueError("image_folder supports single-label image classification only")
        for folder in sorted(image_root.iterdir()):
            if folder.is_dir():
                for image in sorted(folder.rglob("*")):
                    if image.suffix.lower() in IMAGE_EXTENSIONS:
                        add(_inside(image_root, image.relative_to(image_root)), folder.name)
    elif format_name == "pascal_voc":
        if task not in {"image_object_detection", "image_classification_multilabel"}:
            raise ValueError("Pascal VOC boxes cannot be used as instance segmentation masks")
        annotations = _inside(root, config.get("annotations", "."))
        for annotation in sorted(annotations.rglob("*.xml")):
            if annotation.stat().st_size > 5 * 1024**2:
                raise ValueError("Unexpectedly large Pascal VOC annotation")
            text = annotation.read_text(encoding="utf-8")
            if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
                raise ValueError("XML entities/DTDs are not accepted")
            document = ET.fromstring(text)
            image = _inside(image_root, document.findtext("filename", ""))
            with Image.open(image) as opened:
                width, height = opened.size
            objects = []
            for obj in document.findall("object"):
                bbox = obj.find("bndbox")
                if bbox is None or not obj.findtext("name"):
                    raise ValueError(f"Unlabeled Pascal VOC object: {annotation}")
                # VOC uses one-based inclusive coordinates; torchvision uses zero-based xyxy.
                objects.append(_box(
                    obj.findtext("name"), float(bbox.findtext("xmin")) - 1,
                    float(bbox.findtext("ymin")) - 1, float(bbox.findtext("xmax")),
                    float(bbox.findtext("ymax")), width, height,
                ))
            label = sorted({obj["label"] for obj in objects}) if task.endswith("multilabel") else objects
            add(image, label)
    elif format_name == "coco":
        if task not in {"image_object_detection", "image_instance_segmentation", "image_classification_multilabel"}:
            raise ValueError("COCO conversion supports boxes, polygon masks, or image-level label sets")
        annotation_name = config.get("annotations")
        if annotation_name:
            annotation = _inside(root, annotation_name)
        elif input_path.is_file():
            annotation = input_path
        else:
            candidates = sorted(root.glob("*.json"))
            if len(candidates) != 1:
                raise ValueError("Set vision.annotations to the single COCO annotation JSON")
            annotation = candidates[0]
        coco = load_json(annotation)
        categories = {item["id"]: str(item["name"]) for item in coco["categories"]}
        images = {item["id"]: item for item in coco["images"]}
        grouped = {identifier: [] for identifier in images}
        for item in coco["annotations"]:
            if item["image_id"] not in images or item["category_id"] not in categories:
                raise ValueError("COCO annotation refers to an unknown image/category")
            if item.get("iscrowd", 0):
                raise ValueError("COCO crowd/RLE annotations need a separate reviewed adapter")
            image = images[item["image_id"]]
            x, y, w, h = item["bbox"]
            polygons = item.get("segmentation") if task == "image_instance_segmentation" else None
            if task == "image_instance_segmentation" and not polygons:
                raise ValueError("Instance segmentation cannot train from bounding boxes alone")
            grouped[item["image_id"]].append(_box(
                categories[item["category_id"]], x, y, x + w, y + h,
                image["width"], image["height"], polygons,
            ))
        for identifier, image in sorted(images.items()):
            labels = grouped[identifier]
            if task.endswith("multilabel"):
                labels = sorted({obj["label"] for obj in labels})
            add(_inside(image_root, image["file_name"]), labels)
            if (records[-1]["width"], records[-1]["height"]) != (image["width"], image["height"]):
                raise ValueError("COCO image dimensions disagree with the actual image")
    elif format_name == "jsonl":
        if not input_path.is_file():
            input_path = _inside(root, config.get("annotations", "annotations.jsonl"))
        for line in input_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            image = _inside(image_root, row[config.get("image_column", "image_url")])
            labels = row[config.get("label_column", "label")]
            if task in {"image_object_detection", "image_instance_segmentation"}:
                with Image.open(image) as opened:
                    width, height = opened.size
                objects = []
                for obj in labels:
                    if obj.get("isCrowd", 0):
                        raise ValueError("Crowd annotations require a separate reviewed adapter")
                    polygons = obj.get("polygon") if task == "image_instance_segmentation" else None
                    if task == "image_instance_segmentation" and not polygons:
                        raise ValueError("Instance JSONL requires normalized polygon coordinates")
                    if polygons:
                        polygons = [[v * (width if i % 2 == 0 else height) for i, v in enumerate(p)] for p in polygons]
                        xs = [v for polygon in polygons for v in polygon[::2]]
                        ys = [v for polygon in polygons for v in polygon[1::2]]
                        coords = [min(xs), min(ys), max(xs), max(ys)]
                    else:
                        coords = [obj["topX"] * width, obj["topY"] * height,
                                  obj["bottomX"] * width, obj["bottomY"] * height]
                    objects.append(_box(
                        obj["label"], *coords, width, height, polygons,
                    ))
                labels = objects
            add(image, labels)
    else:
        raise ValueError(f"Unsupported image format: {format_name}")
    if not records:
        raise ValueError("No labeled images found")
    return records


def _labels(record, task):
    label = record["label"]
    if task == "image_classification":
        if not isinstance(label, str) or not label:
            raise ValueError("Single-label image classification requires a nonempty string label")
        return {label}
    if not isinstance(label, list):
        raise ValueError("Image labels must be a list")
    values = label if task.endswith("multilabel") else [obj["label"] for obj in label]
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("Image class names must be nonempty strings")
    return set(values)


def _automl_row(record, image_url, task):
    label = record["label"]
    if task in {"image_object_detection", "image_instance_segmentation"}:
        label = []
        w, h = record["width"], record["height"]
        for obj in record["label"]:
            x1, y1, x2, y2 = obj["box"]
            converted = {"label": obj["label"], "topX": x1 / w, "topY": y1 / h,
                         "bottomX": x2 / w, "bottomY": y2 / h, "isCrowd": 0}
            if task == "image_instance_segmentation":
                converted = {
                    "label": obj["label"], "isCrowd": 0,
                    "polygon": [[v / (w if i % 2 == 0 else h) for i, v in enumerate(p)]
                                for p in obj["polygons"]],
                }
            label.append(converted)
    return {"image_url": image_url, "label": label}


def prepare_vision(scenario, input_path, output_dir) -> dict:
    validate_scenario(scenario)
    task = scenario["task"]
    if task not in IMAGE_TASKS:
        raise ValueError("prepare_vision requires an image task")
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Prepared vision output must be empty")
    remote = scenario["vision"].get("image_base_uri")
    if remote:
        parsed = urlsplit(remote)
        if (parsed.scheme not in {"azureml", "https", "wasbs", "abfss"} or not parsed.netloc
                or parsed.query or parsed.fragment or parsed.password
                or (parsed.scheme == "https" and parsed.username)):
            raise ValueError("image_base_uri must be a remote root without credentials/query/fragment")
    records = _source_records(scenario, input_path)
    deduplicated = {}
    for record in records:
        record["sha256"] = sha256(record["source"])
        old = deduplicated.get(record["sha256"])
        if old and old["label"] != record["label"]:
            raise ValueError("Identical image content has conflicting labels")
        deduplicated.setdefault(record["sha256"], record)
    duplicates = len(records) - len(deduplicated)
    records = list(deduplicated.values())
    classes = sorted(set().union(*(_labels(row, task) for row in records)))
    if not classes or (task.startswith("image_classification") and len(classes) < 2):
        raise ValueError("No trainable classes, or fewer than two classification labels")
    settings = scenario.get("split", {})
    rng = random.Random(settings.get("seed", 42))
    splits = {"train": [], "validation": [], "test": []}
    groups = [[row for row in records if row["label"] == label] for label in classes] if task == "image_classification" else [records]
    for group in groups:
        rng.shuffle(group)
        nt = max(1, math.ceil(len(group) * settings.get("test_size", .2)))
        nv = max(1, math.ceil(len(group) * settings.get("validation_size", .2)))
        if len(group) <= nt + nv:
            raise ValueError("Not enough distinct images to populate all three splits")
        splits["test"].extend(group[:nt])
        splits["validation"].extend(group[nt:nt + nv])
        splits["train"].extend(group[nt + nv:])
    training_labels = set().union(*(_labels(row, task) for row in splits["train"]))
    if training_labels != set(classes):
        raise ValueError("Some labels occur only in held-out data; choose a suitable stratified/group split")
    for name, rows in splits.items():
        folder = output / name
        (folder / "images").mkdir(parents=True)
        custom_rows, automl_rows = [], []
        for row in rows:
            relative = "images/" + row["sha256"] + row["source"].suffix.lower()
            shutil.copyfile(row["source"], folder / Path(relative))
            custom_rows.append({k: v for k, v in row.items() if k != "source"} | {"image": relative})
            image_url = f"{remote.rstrip('/')}/{name}/{relative}" if remote else relative
            automl_rows.append(_automl_row(row, image_url, task))
        for filename, values in [("annotations.jsonl", custom_rows), ("data.jsonl", automl_rows)]:
            (folder / filename).write_text("".join(json.dumps(value, allow_nan=False) + "\n" for value in values), encoding="utf-8")
        (folder / "MLTable").write_text(
            "paths:\n  - file: ./data.jsonl\ntransformations:\n  - read_json_lines:\n"
            "        encoding: utf8\n        invalid_lines: error\n"
            "  - convert_column_types:\n        - columns: image_url\n          column_type: stream_info\n",
            encoding="utf-8",
        )
    manifest = {
        "scenario": scenario["name"], "task": task, "dataset": scenario["dataset"],
        "classes": classes, "split_rows": {name: len(rows) for name, rows in splits.items()},
        "split": settings, "duplicates_removed": duplicates, "automl_ready": bool(remote),
        "image_base_uri": remote,
        "automl_note": "Upload this entire immutable prepared directory at image_base_uri before AutoML. Relative manifests are for local use only.",
        "split_sha256": {name: sha256(output / name / "annotations.jsonl") for name in splits},
        "limitations": ["Random image splits do not establish subject/site independence. Use reviewed group-level manifests where required."],
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def _torch():
    try:
        import torch
        import torchvision
    except ImportError as exc:
        raise RuntimeError("Vision training requires the declared [train,vision] extras; no fallback estimator is used") from exc
    return torch, torchvision


class VisionDataset:
    def __init__(self, folder, task, classes, image_size=64):
        self.folder, self.task, self.classes = Path(folder), task, classes
        self.image_size = image_size
        self.rows = [json.loads(line) for line in (self.folder / "annotations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        import numpy as np
        from PIL import Image, ImageDraw

        torch, torchvision = _torch()
        row = self.rows[index]
        with Image.open(_inside(self.folder, row["image"])) as opened:
            image = opened.convert("RGB")
        if self.task.startswith("image_classification"):
            image = image.resize((self.image_size, self.image_size))
            if self.task.endswith("multilabel"):
                target = torch.tensor([float(label in row["label"]) for label in self.classes])
            else:
                target = torch.tensor(self.classes.index(row["label"]), dtype=torch.int64)
        else:
            objects = row["label"]
            boxes = torch.tensor([obj["box"] for obj in objects], dtype=torch.float32).reshape(-1, 4)
            target = {
                "boxes": boxes,
                "labels": torch.tensor([self.classes.index(obj["label"]) + 1 for obj in objects], dtype=torch.int64),
                "image_id": torch.tensor(index),
                "area": (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]),
                "iscrowd": torch.zeros(len(objects), dtype=torch.int64),
            }
            if self.task == "image_instance_segmentation":
                masks = []
                for obj in objects:
                    mask = Image.new("L", image.size)
                    drawer = ImageDraw.Draw(mask)
                    for polygon in obj["polygons"]:
                        drawer.polygon(list(zip(polygon[::2], polygon[1::2])), fill=1)
                    masks.append(torch.from_numpy(np.array(mask, dtype=np.uint8)))
                target["masks"] = torch.stack(masks) if masks else torch.zeros((0, image.height, image.width), dtype=torch.uint8)
        return torchvision.transforms.functional.to_tensor(image), target


def _model(scenario, num_classes, *, initialize=False):
    torch, torchvision = _torch()
    options = scenario["vision"]
    pretrained = bool(options.get("pretrained", False)) and initialize
    if scenario["task"].startswith("image_classification"):
        if scenario.get("custom", {}).get("algorithm", "resnet18") != "resnet18":
            raise ValueError("Custom image classification supports resnet18")
        weights = torchvision.models.ResNet18_Weights.DEFAULT if pretrained else None
        model = torchvision.models.resnet18(weights=weights)
        model.fc = torch.nn.Linear(model.fc.in_features, num_classes)
        return model
    if pretrained:
        raise ValueError("Detection/segmentation pretrained weights are disabled; explicitly implement and review a weights adapter")
    expected = "fasterrcnn_resnet50_fpn" if scenario["task"] == "image_object_detection" else "maskrcnn_resnet50_fpn"
    if scenario.get("custom", {}).get("algorithm", expected) != expected:
        raise ValueError(f"Custom {scenario['task']} supports {expected}")
    kwargs = dict(
        weights=None, weights_backbone=None, num_classes=num_classes + 1,
        min_size=options.get("image_size", 128), max_size=options.get("max_image_size", 256),
        box_detections_per_img=options.get("max_detections", 30),
        rpn_pre_nms_top_n_train=200, rpn_post_nms_top_n_train=100,
        rpn_pre_nms_top_n_test=100, rpn_post_nms_top_n_test=50,
    )
    if scenario["task"] == "image_object_detection":
        return torchvision.models.detection.fasterrcnn_resnet50_fpn(**kwargs)
    return torchvision.models.detection.maskrcnn_resnet50_fpn(**kwargs)


def _collate(batch):
    return tuple(zip(*batch))


def _save_pyfunc(scenario, checkpoint, destination):
    import mlflow.pyfunc
    import numpy as np
    from mlflow.models import ModelSignature
    from mlflow.types import ColSpec, Schema
    from PIL import Image

    class ImageModel(mlflow.pyfunc.PythonModel):
        def load_context(self, context):
            torch, _ = _torch()
            saved = torch.load(context.artifacts["checkpoint"], map_location="cpu", weights_only=True)
            self.classes = saved["classes"]
            self.scenario = saved["scenario"]
            self.model = _model(self.scenario, len(self.classes))
            self.model.load_state_dict(saved["state_dict"])
            self.model.eval()

        def predict(self, context, model_input, params=None):
            import base64
            import io
            import pandas as pd

            torch, torchvision = _torch()
            if "image_base64" not in model_input:
                raise ValueError("Image pyfunc requires an image_base64 column; remote URLs and arbitrary filesystem paths are not accepted")
            images = []
            for value in model_input["image_base64"]:
                with Image.open(io.BytesIO(base64.b64decode(value, validate=True))) as opened:
                    image = opened.convert("RGB")
                if self.scenario["task"].startswith("image_classification"):
                    image = image.resize((self.scenario["vision"].get("image_size", 64),) * 2)
                images.append(torchvision.transforms.functional.to_tensor(image))
            classification = self.scenario["task"].startswith("image_classification")
            with torch.no_grad():
                output = self.model(torch.stack(images) if classification else images)
            if self.scenario["task"] == "image_classification":
                return pd.DataFrame({"prediction": [self.classes[i] for i in output.argmax(1).tolist()]})
            if self.scenario["task"].endswith("multilabel"):
                return pd.DataFrame({"prediction": [json.dumps([self.classes[i] for i in np.flatnonzero(row)])
                                                   for row in (output.sigmoid() >= .5).cpu().numpy()]})
            return pd.DataFrame({"prediction": [
                json.dumps({key: value.detach().cpu().tolist() for key, value in row.items()} |
                           {"label_names": [self.classes[i - 1] for i in row["labels"].tolist()]})
                for row in output
            ]})

    import importlib.metadata

    packages = ["torch", "torchvision", "Pillow", "numpy", "pandas", "PyYAML"]
    requirements = [f"{name}=={importlib.metadata.version(name)}" for name in packages]
    mlflow.pyfunc.save_model(
        path=str(destination), python_model=ImageModel(), artifacts={"checkpoint": str(checkpoint)},
        code_paths=[str(Path(__file__).parent)], pip_requirements=requirements,
        signature=ModelSignature(
            inputs=Schema([ColSpec("string", "image_base64")]),
            outputs=Schema([ColSpec("string", "prediction")]),
        ),
    )


def train_vision(scenario, prepared_dir, model_output) -> dict:
    validate_scenario(scenario)
    if scenario["task"] not in IMAGE_TASKS:
        raise ValueError("train_vision requires an image task")
    destination = Path(model_output)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Model output must be empty")
    torch, _ = _torch()
    options = scenario["vision"]
    epochs, batch_size = options.get("epochs", 1), options.get("batch_size", 2)
    steps = options.get("max_steps_per_epoch", 5)
    if not all(isinstance(v, int) and v > 0 for v in (epochs, batch_size, steps)):
        raise ValueError("epochs, batch_size, max_steps_per_epoch must be positive integers")
    device = torch.device(options.get("device", "cpu"))
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable; no implicit CPU fallback")
    torch.set_num_threads(options.get("num_threads", 2))
    torch.manual_seed(scenario.get("split", {}).get("seed", 42))
    manifest = load_json(Path(prepared_dir) / "manifest.json")
    if manifest["task"] != scenario["task"]:
        raise ValueError("Prepared image task differs from scenario")
    dataset = VisionDataset(Path(prepared_dir) / "train", scenario["task"], manifest["classes"], options.get("image_size", 64))
    loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=0, collate_fn=_collate)
    model = _model(scenario, len(manifest["classes"]), initialize=True).to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=options.get("learning_rate", .001), momentum=.9)
    classification = scenario["task"].startswith("image_classification")
    loss_function = torch.nn.BCEWithLogitsLoss() if scenario["task"].endswith("multilabel") else torch.nn.CrossEntropyLoss()
    losses, trained_images = [], 0
    for _ in range(epochs):
        model.train()
        # Small CPU batches cannot reliably estimate batch-normalization statistics.
        for layer in model.modules():
            if isinstance(layer, torch.nn.modules.batchnorm._BatchNorm):
                layer.eval()
        for step, (images, targets) in enumerate(loader):
            if step >= steps:
                break
            images = [image.to(device) for image in images]
            if classification:
                loss = loss_function(model(torch.stack(images)), torch.stack(targets).to(device))
            else:
                targets = [{key: value.to(device) for key, value in target.items()} for target in targets]
                loss = sum(model(images, targets).values())
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite training loss; no model has been published")
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
            trained_images += len(images)
    if not losses:
        raise ValueError("No training batches were executed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = destination.parent / (destination.name + ".factory-checkpoint.pt")
    if checkpoint.exists():
        raise ValueError(f"Refusing to overwrite checkpoint: {checkpoint}")
    try:
        torch.save({"state_dict": model.cpu().state_dict(), "classes": manifest["classes"], "scenario": scenario}, checkpoint)
        _save_pyfunc(scenario, checkpoint, destination)
    finally:
        checkpoint.unlink(missing_ok=True)
    result = {
        "scenario": scenario, "mode": "custom", "training_rows": len(dataset),
        "image_presentations": trained_images, "optimizer_steps": len(losses),
        "training_loss": losses, "pretrained": options.get("pretrained", False),
        "checkpoint": "artifacts/" + destination.name + ".factory-checkpoint.pt",
        "limitations": ["Small bounded training is a functional template, not an accuracy claim. Validation is reserved; no tuning uses test data."],
    }
    write_json(destination / "factory.json", result)
    return result


def evaluate_vision(scenario, prepared_dir, model_dir, output_dir) -> dict:
    validate_scenario(scenario)
    if scenario["task"] not in IMAGE_TASKS:
        raise ValueError("evaluate_vision requires an image task")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    factory_path = Path(model_dir) / "factory.json"
    if not factory_path.is_file():
        write_json(output / "responsible-ai.json", {
            "status": "unsupported-model-adapter", "task": scenario["task"],
            "reason": "AutoML image outputs need a task/version-specific inference adapter. No metrics or Azure RAI dashboard were fabricated.",
        })
        raise ValueError("Unsupported AutoML/external vision model adapter; custom torchvision checkpoint is required")
    import numpy as np
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, hamming_loss

    torch, _ = _torch()
    metadata = load_json(factory_path)
    saved = torch.load(_inside(model_dir, metadata["checkpoint"]), map_location="cpu", weights_only=True)
    if saved["scenario"]["task"] != scenario["task"]:
        raise ValueError("Model task differs from evaluation task")
    model = _model(saved["scenario"], len(saved["classes"]))
    model.load_state_dict(saved["state_dict"])
    model.eval()
    task = scenario["task"]
    dataset = VisionDataset(Path(prepared_dir) / "test", task, saved["classes"], saved["scenario"]["vision"].get("image_size", 64))
    truth, predictions, errors = [], [], []
    metric = None
    if not task.startswith("image_classification"):
        from torchmetrics.detection.mean_ap import MeanAveragePrecision

        metric = MeanAveragePrecision(iou_type="segm" if task == "image_instance_segmentation" else "bbox", class_metrics=True)
    with torch.no_grad():
        for index in range(len(dataset)):
            image, target = dataset[index]
            if task.startswith("image_classification"):
                scores = model(image.unsqueeze(0))[0]
                prediction = (scores.sigmoid() >= .5).to(torch.int64) if task.endswith("multilabel") else scores.argmax()
                truth.append(target.numpy().tolist())
                predictions.append(prediction.numpy().tolist())
                errors.append({"image": dataset.rows[index]["image"], "actual": truth[-1], "prediction": predictions[-1],
                               "error": truth[-1] != predictions[-1]})
            else:
                prediction = model([image])[0]
                if task == "image_instance_segmentation":
                    prediction["masks"] = prediction["masks"][:, 0] >= .5
                    target["masks"] = target["masks"].bool()
                metric.update([prediction], [target])
                errors.append({
                    "image": dataset.rows[index]["image"], "true_instances": len(target["labels"]),
                    "predicted_instances_at_0_5": int((prediction["scores"] >= .5).sum()),
                    "true_classes": target["labels"].tolist(),
                })
    report = {
        "task": task, "test_rows": len(dataset), "classes": saved["classes"],
        "responsible_ai": {
            "tooling": "Held-out torchvision inference, sklearn classification metrics or torchmetrics COCO mAP",
            "azure_dashboard": "Not generated; image tasks are not claimed to support Azure tabular RAI components.",
            "limitations": [
                "Image/class errors are diagnostic, not a fairness or causal guarantee.",
                "No sensitive attribute inference is performed; demographic/site cohorts need reviewed annotations.",
                "No saliency, counterfactual, or clinical validation claim is made.",
            ],
        },
    }
    if task.startswith("image_classification"):
        metrics = {"accuracy": float(accuracy_score(truth, predictions)),
                   "f1_weighted": float(f1_score(truth, predictions, average="weighted", zero_division=0))}
        if task.endswith("multilabel"):
            metrics["hamming_loss"] = float(hamming_loss(truth, predictions))
            actual, predicted = np.asarray(truth), np.asarray(predictions)
            report["class_errors"] = {
                label: {"positive_rows": int(actual[:, i].sum()), "errors": int((actual[:, i] != predicted[:, i]).sum())}
                for i, label in enumerate(saved["classes"])
            }
        else:
            labels = list(range(len(saved["classes"])))
            report["confusion_matrix"] = confusion_matrix(truth, predictions, labels=labels).tolist()
    else:
        computed = metric.compute()
        metrics = {key: float(computed[key]) for key in ("map", "map_50", "map_75", "mar_100")
                   if torch.isfinite(computed[key]) and float(computed[key]) >= 0}
        report["class_map"] = {
            saved["classes"][int(label) - 1]: float(value) if float(value) >= 0 else None
            for label, value in zip(computed["classes"].reshape(-1), computed["map_per_class"].reshape(-1))
        }
        if "map" not in metrics:
            raise ValueError("COCO mAP undefined for this held-out split; no quality claim can be made")
    report["metrics"] = metrics
    write_json(output / "metrics.json", metrics)
    write_json(output / "responsible-ai.json", report)
    write_json(output / "image-errors.json", errors)
    try:
        quality_gate(metrics, scenario.get("quality", {}))
    except ValueError as exc:
        write_json(output / "quality-gate.json", {"passed": False, "reason": str(exc)})
        raise
    write_json(output / "quality-gate.json", {"passed": True, "limits": scenario.get("quality", {})})
    return report
