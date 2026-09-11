"""Immutable local lake publications and schema-safe train/inference orchestration."""

import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .config import load_json, validate_scenario, write_json
from .data import read_frame, sha256
from .lake import LakeLayout, identifier, lake_manifest, local_key_path


def file_inventory(directory: Path) -> dict[str, str]:
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Source data and lake artifacts must not contain links")
        if path.is_file() and path.name != "_SUCCESS.json":
            result[path.relative_to(directory).as_posix()] = sha256(path)
    return result


def verified_manifest(directory: Path) -> dict:
    manifest = load_json(directory / "_SUCCESS.json")
    if manifest.get("state") != "committed" or manifest.get("files") != file_inventory(directory):
        raise ValueError(f"Lake publication is incomplete or its files changed: {directory}")
    return manifest


@contextmanager
def publication(root: Path, key: str):
    destination = local_key_path(root, key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f"Immutable lake destination already exists: {key}; use a new snapshot/run ID")
    lock = destination.with_name(destination.name + ".lock")
    with lock.open("x", encoding="utf-8") as stream:
        stream.write("Exclusive local publication; inspect interrupted writes before removing this lock.\n")
    staging = Path(tempfile.mkdtemp(prefix=".publishing-", dir=destination.parent))
    try:
        yield staging
        if not (staging / "_SUCCESS.json").is_file():
            raise ValueError("Publication did not produce a completion manifest")
        if destination.exists():
            raise ValueError("Another writer created the lake destination")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        lock.unlink()


def finish(directory: Path, metadata: dict):
    write_json(directory / "_SUCCESS.json", {
        "schema": "ml-model-factory-publication/v1", "state": "committed",
        **metadata, "files": file_inventory(directory),
    })


def source_fingerprint(input_path: Path) -> dict[str, str]:
    if input_path.is_symlink():
        raise ValueError("Dataset input must not be a symbolic link")
    if input_path.is_file():
        return {input_path.name: sha256(input_path)}
    if input_path.is_dir():
        inventory = file_inventory(input_path)
        if not inventory:
            raise ValueError("Dataset input directory is empty")
        return inventory
    raise FileNotFoundError(input_path)


def record_rejection(root: Path, layout: LakeLayout, area: str, source: str, code: str) -> Path:
    path = local_key_path(root, layout.key(area) + f"/{layout.run_id}-{uuid4().hex}/issue.json")
    write_json(path, {
        "status": "rejected", "reason_code": code, "source_reference": source,
        "raw_rows_copied": False, "action": "Correct the source/schema and publish a new immutable version.",
    })
    return path


def capture_source(scenario: dict, layout: LakeLayout, input_path: Path, root: Path) -> Path:
    input_path, root = Path(input_path).resolve(), Path(root).resolve()
    if input_path == root or root.is_relative_to(input_path):
        raise ValueError("Lake root must not be inside the source dataset")
    inventory = source_fingerprint(input_path)
    provenance_file = input_path.parent / "provenance.json" if input_path.is_file() else input_path / "provenance.json"
    provenance = load_json(provenance_file) if provenance_file.is_file() else None
    if provenance is not None:
        if provenance.get("provider") != "kaggle" or provenance.get("slug") != scenario["dataset"].get("slug"):
            raise ValueError("Download provenance does not match the configured Kaggle source")
        expected_files = provenance.get("files", {})
        for name, digest in inventory.items():
            if name != "provenance.json" and expected_files.get(name) != digest:
                raise ValueError("Downloaded source files do not match their provenance hashes")
    dataset_root = layout.local_path(root, "dataset_root")
    if dataset_root.exists():
        manifest = verified_manifest(dataset_root)
        if manifest.get("source_files") != inventory or manifest.get("declared_source") != scenario["dataset"]:
            raise ValueError("Dataset version already refers to different content or provenance; use a new data_version")
        if manifest.get("source_kind") != ("images" if scenario["task"].startswith("image_") else "tabular"):
            raise ValueError("Dataset source representation changed")
    else:
        with publication(root, layout.key("dataset_root")) as staging:
            landing = staging / "landing"
            if input_path.is_dir():
                shutil.copytree(input_path, landing)
            else:
                landing.mkdir()
                shutil.copy2(input_path, landing / input_path.name)
            if provenance is not None:
                write_json(staging / "download-provenance.json", provenance)
            if scenario["task"].startswith("image_"):
                write_json(staging / "bronze" / "source-index.json", {"images": inventory})
                # Pixel/annotation validation is task-specific and happens before gold publication.
                write_json(staging / "silver" / "source-contract.json", {
                    "status": "requires-task-specific-annotation-validation",
                    "source": layout.key("landing"), "image_files": len(inventory),
                })
            else:
                if not input_path.is_file():
                    raise ValueError("Tabular ingestion requires one explicit CSV or Parquet file")
                frame = read_frame(input_path)
                if frame.empty or not frame.columns.is_unique:
                    raise ValueError("Source table must be nonempty and have unique columns")
                (staging / "bronze").mkdir()
                frame.to_parquet(staging / "bronze" / "data.parquet", index=False)
                (staging / "silver").mkdir()
                frame.to_parquet(staging / "silver" / "data.parquet", index=False)
                write_json(staging / "silver" / "source-contract.json", {
                    "status": "validated", "rows": len(frame), "columns": frame.columns.tolist(),
                    "dtypes": {name: str(dtype) for name, dtype in frame.dtypes.items()},
                    "checks": ["nonempty", "unique-column-names", "Parquet-serializable"],
                    "transformations": [], "learned_preprocessing": "none",
                })
            finish(staging, {
                "kind": "source", "dataset": layout.dataset, "data_version": layout.data_version,
                "source_files": inventory, "declared_source": scenario["dataset"],
                "source_kind": "images" if scenario["task"].startswith("image_") else "tabular",
                "download_provenance_verified": provenance is not None,
                "provenance_note": "Download manifest hashes were verified." if provenance is not None else
                                   "Declared dataset identity is not independent verification of download provenance.",
            })
    return dataset_root / "landing" if scenario["task"].startswith("image_") else dataset_root / "silver" / "data.parquet"


def prepare_snapshot(scenario: dict, layout: LakeLayout, source: Path, root: Path) -> Path:
    dataset_root = layout.local_path(root, "dataset_root")
    source_manifest = verified_manifest(dataset_root)
    snapshot = layout.local_path(root, "training_snapshot")
    signature = {
        "scenario": scenario, "dataset_key": layout.key("dataset_root"),
        "source_manifest_sha256": sha256(dataset_root / "_SUCCESS.json"),
    }
    if snapshot.exists():
        existing = verified_manifest(snapshot)
        if existing.get("signature") != signature:
            raise ValueError("Snapshot ID already refers to different data or preparation settings")
    else:
        with publication(root, layout.key("training_snapshot")) as staging:
            if scenario["task"].startswith("image_"):
                from .vision import prepare_vision
                prepare_vision(scenario, source, staging / "gold")
            else:
                from .data import prepare
                prepare(scenario, source, staging / "gold")
            write_json(staging / "lineage.json", {**signature, "source_kind": source_manifest["source_kind"]})
            finish(staging, {"kind": "training-snapshot", "signature": signature})
    return snapshot / "gold"


def train_in_lake(scenario: dict, config: dict, input_path: Path, root: Path) -> dict:
    validate_scenario(scenario)
    layout = LakeLayout.from_config(config, scenario)
    root = Path(root).resolve()
    if layout.local_path(root, "training_run").exists():
        raise ValueError("Training run ID already exists; use a new run_id")
    try:
        source = capture_source(scenario, layout, input_path, root)
        prepared = prepare_snapshot(scenario, layout, source, root)
    except (ValueError, KeyError) as exc:
        record_rejection(root, layout, "dataset_quarantine", layout.key("landing"), type(exc).__name__)
        raise
    with publication(root, layout.key("training_run")) as staging:
        if scenario["task"].startswith("image_"):
            from .vision import evaluate_vision, train_vision
            train_vision(scenario, prepared, staging / "model")
            evaluator = evaluate_vision
        else:
            from .training import train
            from .evaluation import evaluate
            train(scenario, prepared, staging / "model")
            evaluator = evaluate
        try:
            report = evaluator(scenario, prepared, staging / "model", staging / "evaluation")
        except ValueError:
            # Persist diagnostic reports separately; rejected models never receive a success manifest.
            rejected = local_key_path(root, layout.key("training_run") + "-rejected")
            if rejected.exists():
                raise ValueError("Rejected run already exists; use a new run_id")
            rejected.mkdir()
            if (staging / "evaluation").exists():
                shutil.copytree(staging / "evaluation", rejected / "evaluation")
            write_json(rejected / "status.json", {"state": "rejected", "model_promoted": False})
            raise
        manifest = lake_manifest(layout, scenario)
        manifest["source_snapshot_sha256"] = sha256(layout.local_path(root, "training_snapshot") / "_SUCCESS.json")
        write_json(staging / "lineage.json", manifest)
        finish(staging, {"kind": "training-run", "run_id": layout.run_id,
                         "snapshot_id": layout.snapshot_id, "scenario": scenario})
    return {
        "state": "committed", "paths": layout.as_dict(),
        "model": str(layout.local_path(root, "training_model")),
        "metrics": report.get("metrics", report),
    }


def normalize_inference(model, frame, scenario):
    import pandas as pd

    required = list(scenario["features"])
    if scenario["task"] == "forecasting":
        required = list(dict.fromkeys(required + scenario["forecast"].get("series_columns", []) +
                                     [scenario["forecast"]["time_column"]]))
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Inference input is missing model features: {sorted(missing)}")
    if scenario["target"] in frame.columns:
        raise ValueError("Inference input must not contain labels; store observed labels in feedback")
    result = frame.loc[:, required].copy()
    schema = model.metadata.get_input_schema()
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


def infer_in_lake(scenario: dict, config: dict, input_path: Path, model_path: Path, root: Path) -> dict:
    import mlflow.pyfunc
    import pandas as pd
    from mlflow.exceptions import MlflowException
    from .evaluation import prediction_vector

    validate_scenario(scenario)
    layout = LakeLayout.from_config(config, scenario)
    layout.key("inference_root")
    model_path = Path(model_path).resolve()
    training = verified_manifest(model_path.parent)
    if training.get("kind") != "training-run":
        raise ValueError("Use a model from a committed, quality-gated lake training run")
    if training.get("scenario") != scenario:
        raise ValueError("Model scenario/schema does not match inference configuration")
    binding_key = layout.key("use_case_root") + f"/models/{layout.model_version}/binding"
    binding = local_key_path(root, binding_key)
    expected = {"training_manifest_sha256": sha256(model_path.parent / "_SUCCESS.json")}
    if binding.exists():
        existing = verified_manifest(binding)
        if existing.get("binding") != expected:
            raise ValueError("This model_version is already bound to a different model")
    else:
        with publication(root, binding_key) as staging:
            write_json(staging / "model.json", expected)
            finish(staging, {"kind": "model-version-binding", "binding": expected})
    model = mlflow.pyfunc.load_model(str(model_path))
    with publication(root, layout.key("inference_root")) as staging:
        (staging / "in").mkdir()
        shutil.copy2(input_path, staging / "in" / Path(input_path).name)
        try:
            raw = read_frame(input_path)
            request_column = config.get("request_id_column", "request_id")
            if request_column not in raw or raw[request_column].isna().any() or raw[request_column].duplicated().any():
                raise ValueError("Inference requires a nonempty unique request_id per row for output/feedback joins")
            if scenario["task"].startswith("image_"):
                if scenario.get("target", "label") in raw or "image_base64" not in raw:
                    raise ValueError("Vision inference requires image_base64 requests without training labels")
                features = raw.loc[:, ["image_base64"]].copy()
            else:
                features = normalize_inference(model, raw, scenario)
            if features.empty:
                raise ValueError("Inference input must not be empty")
            predictions = prediction_vector(model.predict(features), len(features))
            (staging / "gold").mkdir()
            features.to_parquet(staging / "gold" / "features.parquet", index=False)
            (staging / "out").mkdir()
            pd.DataFrame({
                request_column: raw[request_column].to_numpy(), "prediction": predictions,
                "model_version": layout.model_version, "run_id": layout.run_id,
            }).to_parquet(staging / "out" / "predictions.parquet", index=False)
        except (ValueError, KeyError, MlflowException) as exc:
            record_rejection(root, layout, "quarantine", layout.key("input"), type(exc).__name__)
            raise
        write_json(staging / "lineage.json", {
            **lake_manifest(layout, scenario), "model_mlmodel_sha256": sha256(model_path / "MLmodel"),
            "training_run_manifest_sha256": sha256(model_path.parent / "_SUCCESS.json"),
            "input_sha256": sha256(Path(input_path)), "rows": len(features),
        })
        finish(staging, {"kind": "inference-run", "model_version": layout.model_version,
                         "training_run": training["run_id"], "run_id": layout.run_id})
    return {"state": "committed", "rows": len(features), "output": str(layout.local_path(root, "output"))}


def feedback_in_lake(scenario: dict, config: dict, input_path: Path, root: Path) -> dict:
    import pandas as pd

    validate_scenario(scenario)
    layout = LakeLayout.from_config(config, scenario)
    feedback_version = identifier(config.get("feedback_version"), "feedback_version")
    feedback_source = config.get("feedback_source")
    if not isinstance(feedback_source, str) or not feedback_source.strip():
        raise ValueError("feedback_source must describe the observed-label source, not model predictions")
    inference = verified_manifest(layout.local_path(root, "inference_root"))
    request = config.get("request_id_column", "request_id")
    target = scenario.get("target", "label")
    labels = read_frame(input_path)
    required = {request, target, "observed_at"}
    if not required.issubset(labels.columns) or labels.empty or labels[list(required)].isna().any().any():
        raise ValueError("Feedback requires request_id, observed label, and observed_at for every row")
    if labels[request].duplicated().any():
        raise ValueError("A feedback version must contain at most one observed label per request")
    predicted = read_frame(layout.local_path(root, "output") / "predictions.parquet")
    if not set(labels[request]).issubset(set(predicted[request])):
        raise ValueError("Feedback request IDs must belong to this exact inference run")
    labels = labels.loc[:, [request, target, "observed_at"]].copy()
    labels["observed_at"] = pd.to_datetime(labels["observed_at"], utc=True, errors="raise")
    key = layout.key("feedback") + "/versions/" + feedback_version
    with publication(root, key) as staging:
        labels.to_parquet(staging / "labels.parquet", index=False)
        finish(staging, {
            "kind": "observed-feedback", "source": feedback_source,
            "inference_run": inference["run_id"], "model_version": layout.model_version,
            "source_sha256": sha256(Path(input_path)), "training_eligible": False,
            "review_required": "Join, review leakage/consent/quality, then explicitly create a new training snapshot.",
        })
    return {"state": "committed", "feedback": key, "rows": len(labels), "training_eligible": False}
