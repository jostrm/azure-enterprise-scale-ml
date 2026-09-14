"""Local/Azure ML component entry points backed by the canonical model factory.

Bronze preserves source bytes; silver/gold use Delta unless Parquet is explicit.
Silver validates configured columns/types without learned cleaning. Imputation,
scaling and encoding belong to the training-only sklearn pipeline. Custom model
inputs are checked Parquet projections of pinned gold; separate AML inputs use
native pinned table MLTables.
Table completion manifests are write-last local markers, not atomic Azure uploads.
"""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any
from uuid import uuid4

from ml_model_factory.config import load_json, quality_gate, validate_scenario, write_json
from ml_model_factory.data import sha256


OPERATIONS = (
    "in2silver", "in2bronze", "bronze2silver", "merge", "split",
    "training_manual", "evaluate", "inference",
)


class FrameTransformer(ABC):
    """Consumer hook; return a DataFrame without fitting on held-out data."""

    @abstractmethod
    def transform(self, frame, context: Mapping[str, Any]):
        """Transform one source frame using the explicit operation context."""


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError(f"Symbolic links/junctions are not supported: {part}")


def _empty_outputs(outputs: list[Path], inputs: list[Path]) -> None:
    resolved = []
    for output in outputs:
        _no_links(output)
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError(f"Output must be an empty directory: {output}")
        selected = output.resolve()
        for other in resolved + [path.resolve() for path in inputs]:
            if selected == other or selected in other.parents or other in selected.parents:
                raise ValueError("Input and output paths, and separate outputs, must not overlap")
        resolved.append(selected)


def _check_frame(frame) -> None:
    import pandas as pd

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("A tabular transformer must return a pandas DataFrame")
    if frame.empty:
        raise ValueError("Tabular input must contain records and columns")
    if not frame.columns.is_unique or any(not isinstance(column, str) or not column for column in frame.columns):
        raise ValueError("Column names must be unique nonempty strings")


def _concat(frames: list):
    import pandas as pd
    from pandas.api.types import is_dtype_equal

    if not frames:
        raise ValueError("At least one tabular input is required")
    first = frames[0]
    _check_frame(first)
    for frame in frames[1:]:
        _check_frame(frame)
        if set(frame.columns) != set(first.columns):
            raise ValueError("Concat inputs must have exactly the same column set")
        for column in first.columns:
            if not is_dtype_equal(first[column].dtype, frame[column].dtype):
                raise ValueError(f"Concat inputs have incompatible dtypes for {column!r}")
    return pd.concat([frame.loc[:, first.columns] for frame in frames], ignore_index=True)


def _source_files(path: Path, dataset: Mapping[str, Any]):
    path, dataset = Path(path), dict(dataset or {})
    _no_links(path)
    if any((parent / "_delta_log").exists() for parent in path.parents):
        raise ValueError("Read the Delta table root, never a physical Parquet part")
    if not path.exists():
        raise FileNotFoundError(path)
    format_ = dataset.get("format")
    if format_ is not None and format_ not in ("csv", "parquet", "xlsx"):
        raise ValueError("dataset.format must be csv, parquet or xlsx for source files")
    pattern = dataset.get("file_pattern", f"*.{format_ or 'parquet'}")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("dataset.file_pattern must be a nonempty relative glob")
    pattern = pattern.replace("\\", "/")
    relative = PurePosixPath(pattern)
    if relative.is_absolute() or ".." in relative.parts or ":" in pattern:
        raise ValueError("dataset.file_pattern must not contain traversal or absolute paths")
    if path.is_file():
        files = [path]
        format_ = format_ or path.suffix.lower().lstrip(".")
    elif path.is_dir():
        inferred = relative.suffix.lower().lstrip(".")
        if inferred and inferred not in ("csv", "parquet", "xlsx"):
            raise ValueError("dataset.file_pattern must select CSV and Parquet, or XLSX")
        format_ = format_ or inferred or "parquet"
        if inferred and format_ != inferred:
            raise ValueError("dataset.format disagrees with dataset.file_pattern")
        for entry in path.rglob("*"):
            if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                raise ValueError(f"Symbolic links/junctions are not supported: {entry}")
            if entry.name in ("_delta_log", "_table.json"):
                raise ValueError("Read a table at its root, never discover its physical Parquet files")
        files = sorted(
            (file for file in path.glob(pattern) if file.is_file() and file.suffix.lower() == f".{format_}"),
            key=lambda file: file.relative_to(path).as_posix(),
        )
    else:
        raise ValueError(f"Expected a regular file or directory: {path}")
    if format_ not in ("csv", "parquet", "xlsx"):
        raise ValueError("Only CSV and Parquet inputs, or explicitly selected XLSX, are supported")
    if not files:
        raise ValueError(f"No {format_} records matched {pattern!r} in {path}")
    for file in files:
        _no_links(file)
        if file.suffix.lower() != f".{format_}":
            raise ValueError(f"Input extension disagrees with dataset.format: {file}")
    return files, format_


def _file_inventory(path: Path, files: list[Path]) -> dict:
    inventory = {}
    for file in files:
        name = file.name if path.is_file() else file.relative_to(path).as_posix()
        if ":" in name or any(ord(char) < 32 for char in name) or any(part in ("", ".", "..") for part in name.split("/")):
            raise ValueError("Source files require safe relative filenames")
        inventory[name] = sha256(file)
    return inventory


def read_tabular(path: Path, dataset: Mapping[str, Any] | None = None):
    """Read logical table snapshots or declared source files (``**`` opts into recursion)."""
    import pandas as pd
    from azure_esml.base_layer.tables import read_table

    path, dataset = Path(path), dict(dataset or {})
    _no_links(path)
    if path.is_dir() and ((path / "_table.json").exists() or (path / "_delta_log").exists()):
        frame, metadata = read_table(path, version=dataset.get("delta_version"))
        _check_frame(frame)
        return frame, {
            "path": str(path.resolve()), "files": metadata["files"],
            "sha256": metadata["data_fingerprint"], "format": metadata["format"],
            "delta_version": metadata.get("delta_version"),
        }
    if dataset.get("delta_version") is not None:
        raise ValueError("dataset.delta_version requires a Delta table")
    index = None
    if path.is_dir() and (path / "bronze.json").is_file():
        _no_links(path / "bronze.json")
        index = load_json(path / "bronze.json")
        if index.get("format") != "raw" or not isinstance(index.get("files"), dict) or not index["files"]:
            raise ValueError("Invalid raw bronze source index")
        dataset = {"format": index["source_format"], "file_pattern": index["file_pattern"]}
    files, format_ = _source_files(path, dataset)
    inventory = _file_inventory(path, files)
    if index is not None and (inventory != index["files"] or _hash(inventory) != index.get("fingerprint")):
        raise ValueError("Raw bronze content does not match its source index")
    frames = []
    for file in files:
        if format_ == "csv":
            frame = pd.read_csv(file)
        elif format_ == "xlsx":
            frame = pd.read_excel(file)
        else:
            frame = pd.read_parquet(file)
        _check_frame(frame)
        frames.append(frame)
    return _concat(frames), {
        "path": str(path.resolve()), "files": inventory, "sha256": _hash(inventory), "format": format_,
    }


def _scenario(config: Mapping[str, Any]) -> dict:
    scenario = deepcopy(config.get("scenario"))
    if not isinstance(scenario, dict):
        raise ValueError("config.scenario must be a canonical model-factory scenario object")
    if scenario.get("task") not in ("classification", "regression", "forecasting"):
        raise ValueError("Built-in tabular runtime supports classification, regression and forecasting; use a vision adapter")
    return scenario


def _is_inference(config: Mapping[str, Any]) -> bool:
    request = config.get("request", {})
    return request.get("pipeline_type") in ("IN_2_GOLD_INFERENCE", "IN_2_GOLD_INFERENCE_DBX", "GOLD_INFERENCE")


def _reject_target(frame, scenario: dict) -> None:
    if scenario.get("target") in frame.columns:
        raise ValueError("Inference input must not contain the target/label column")


def _complete_labels(frame, target: str) -> bool:
    import numpy as np
    from pandas.api.types import is_numeric_dtype

    if target not in frame or frame[target].isna().any():
        return False
    values = frame[target]
    if is_numeric_dtype(values.dtype):
        return bool(np.isfinite(values).all())
    return not values.astype(str).str.strip().eq("").any()


def _validate_columns(frame, dataset: Mapping[str, Any]) -> None:
    from pandas.api.types import is_dtype_equal, pandas_dtype

    required = dataset.get("required_columns", [])
    expected = dataset.get("expected_columns")
    if not isinstance(required, list) or any(not isinstance(column, str) for column in required):
        raise ValueError("dataset.required_columns must be a list of column names")
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    if expected is not None:
        if not isinstance(expected, list) or set(frame.columns) != set(expected):
            raise ValueError("Input columns do not match dataset.expected_columns")
    types = dataset.get("column_types", {})
    if not isinstance(types, dict):
        raise ValueError("dataset.column_types must map column names to pandas dtype names")
    for column, dtype in types.items():
        if column not in frame or not is_dtype_equal(frame[column].dtype, pandas_dtype(dtype)):
            raise ValueError(f"Column {column!r} does not have the required dtype {dtype!r}")


def _load_transformer(hook):
    if hook is None:
        return None
    if isinstance(hook, (FrameTransformer, Callable)) or callable(getattr(hook, "transform", None)):
        return hook() if isinstance(hook, type) and callable(getattr(hook, "transform", None)) else hook
    if isinstance(hook, str):
        file, separator, function = hook.rpartition(":")
        if not separator or len(function) == 0 or "/" in function or "\\" in function:
            file, function = hook, "transform"
    elif isinstance(hook, Mapping):
        file, function = hook.get("file"), hook.get("function", "transform")
    else:
        raise ValueError("hook must be a callable, FrameTransformer, or explicit Python file/function")
    if not file or not isinstance(function, str) or not function.isidentifier():
        raise ValueError("hook requires a file and a Python function/class name")
    path = Path(file)
    _no_links(path)
    if not path.is_file() or path.suffix != ".py":
        raise ValueError("hook.file must identify an existing Python source file")
    spec = importlib.util.spec_from_file_location("esml_consumer_" + sha256(path), path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load consumer hook: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    transformer = getattr(module, function)
    # The -m entry point and consumer imports may hold different copies of the ABC.
    if isinstance(transformer, type) and callable(getattr(transformer, "transform", None)):
        transformer = transformer()
    if not callable(transformer) and not callable(getattr(transformer, "transform", None)):
        raise TypeError("Consumer hook must be callable or implement FrameTransformer")
    return transformer


def _transformer_identity(transformer) -> dict:
    import inspect

    method = getattr(transformer, "transform", transformer)
    if not inspect.isfunction(method) and not inspect.ismethod(method):
        method = type(transformer).__call__
    identity = {"callable": f"{getattr(method, '__module__', type(transformer).__module__)}.{method.__qualname__}"}
    file = inspect.getsourcefile(method) if hasattr(method, "__code__") else None
    if file is not None and Path(file).is_file():
        identity.update(file=str(Path(file).resolve()), sha256=sha256(Path(file)))
    return identity


def _context(config: Mapping[str, Any], operation: str) -> dict:
    return {
        "operation": operation, "scenario": deepcopy(config["scenario"]),
        "tags": deepcopy(config.get("tags", {})), "request": deepcopy(config.get("request", {})),
    }


def _lineage(config: Mapping[str, Any], operation: str, sources: dict) -> dict:
    return {
        "schema": "azure-esml.runtime/v1", **_context(config, operation),
        "inputs": sources, "scope": _scope(config),
        "source_fingerprint": _hash({name: item["files"] for name, item in sources.items()}),
    }


def _scope(config: Mapping[str, Any]) -> dict:
    from ml_model_factory.tags import scope_tags

    requested = scope_tags(config.get("request", {}).get("scope", {}))
    tagged = scope_tags(config.get("tags", {}))
    if any(key in tagged and tagged[key] != value for key, value in requested.items()):
        raise ValueError("Request scope disagrees with model artifact tags")
    return {**tagged, **requested}


def _require_gold(config: Mapping[str, Any]) -> bool:
    value = config.get("require_gold", True)
    if not isinstance(value, bool):
        raise ValueError("config.require_gold must be a boolean; False is only a legacy migration adapter")
    return value


def _scenario_binding(scenario: dict) -> dict:
    return {key: deepcopy(scenario.get(key)) for key in (
        "name", "task", "target", "features", "categorical_features",
        "sensitive_features", "forecast", "split",
    )}


def _model_frame(frame, scenario: dict):
    import pandas as pd

    if scenario["task"] == "forecasting":
        frame = frame.copy()
        column = scenario["forecast"]["time_column"]
        # Classic Delta stores UTC instants; MLflow's datetime signature expects
        # timezone-naive UTC. Only the model boundary changes this representation.
        frame[column] = pd.to_datetime(frame[column], errors="raise", utc=True).dt.tz_localize(None)
    return frame


def _write_frame(frame, output: Path, lineage: dict, *, format: str = "delta") -> dict:
    from azure_esml.base_layer.tables import write_table
    from ml_model_factory.lake_flow import finish

    _check_frame(frame)
    metadata = write_table(frame, output, format=format)
    lineage["output"] = {
        **metadata, "rows": metadata["row_count"],
        "fingerprint": metadata["data_fingerprint"], "sha256": metadata["data_fingerprint"],
    }
    write_json(output / "lineage.json", lineage)
    stage = lineage.get("medallion_stage")
    if stage in ("silver", "gold"):
        finish(output, {
            "kind": "medallion-table", "medallion_stage": stage, **lineage["scope"],
            "use_case": lineage["scenario"]["name"],
        })
    return lineage


def _raw_bronze(config: Mapping[str, Any], name: str, path: Path, output: Path, dataset: dict) -> dict:
    path = Path(path)
    files, format_ = _source_files(path, dataset)
    inventory = _file_inventory(path, files)
    total_bytes = sum(file.stat().st_size for file in files)
    if not total_bytes:
        raise ValueError("Raw bronze input must contain nonempty source bytes")
    source = {"path": str(path.resolve()), "format": format_, "files": inventory, "sha256": _hash(inventory)}
    output.mkdir(parents=True, exist_ok=True)
    for file, relative in zip(files, inventory):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, destination)
        if sha256(destination) != inventory[relative]:
            raise ValueError("Raw bronze copy differs from the original source bytes")
    index = {
        "schema": "azure-esml.bronze/v1", "format": "raw", "source_format": format_,
        "file_pattern": f"**/*.{format_}", "files": inventory,
        "fingerprint": _hash(inventory), "bytes": total_bytes,
    }
    write_json(output / "bronze.json", index)
    lineage = {
        **_lineage(config, "in2bronze", {name: source}), "medallion_stage": "bronze",
        "transformation": "none", "learned_preprocessing": False, "output": index,
    }
    write_json(output / "lineage.json", lineage)
    return lineage


def _gold_source(config: Mapping[str, Any], path: Path, source: dict) -> dict:
    required = _require_gold(config)
    lineage_path = path / "lineage.json" if path.is_dir() else path.parent / "lineage.json"
    _no_links(lineage_path)
    lineage = load_json(lineage_path) if lineage_path.is_file() else {}
    stage = lineage.get("medallion_stage")
    if required:
        if source.get("format") not in ("delta", "parquet"):
            raise ValueError("Gold training inputs must be Delta or Parquet analytical tables, not raw formats")
        if not path.is_dir() or stage != "gold":
            raise ValueError("Split requires a gold artifact with medallion_stage='gold' lineage")
        if _is_inference(config) or _is_inference(lineage):
            raise ValueError("Inference gold cannot be used for training")
        if lineage.get("scope") != _scope(config):
            raise ValueError("Gold scope does not match the selected training scope")
        if _scenario_binding(lineage.get("scenario", {})) != _scenario_binding(config["scenario"]):
            raise ValueError("Gold lineage does not match the selected scenario")
        metadata = lineage.get("output", {})
        if (metadata.get("files") != source["files"] or metadata.get("fingerprint") != source["sha256"]
                or metadata.get("format") != source["format"]
                or metadata.get("delta_version") != source.get("delta_version")):
            raise ValueError("Gold content does not match its lineage fingerprint/version")
        for key in ("data_version", "snapshot_id"):
            expected = config.get("request", {}).get(key)
            if expected is not None and lineage.get("request", {}).get(key) != expected:
                raise ValueError(f"Gold {key} does not match the selected snapshot")
    return {
        "schema": "azure-esml.gold-source/v1", "medallion_stage": stage or "legacy",
        "input_format": source["format"], "delta_version": source.get("delta_version"),
        "input_fingerprint": source["sha256"], "files": source["files"],
        "source_path": source["path"], "scope": _scope(config),
        "use_case": config["scenario"]["name"], "scenario": _scenario_binding(config["scenario"]),
        "purpose": "inference" if _is_inference(config) else "training",
        "data_version": config.get("request", {}).get("data_version"),
        "snapshot_id": config.get("request", {}).get("snapshot_id"),
        "lineage_sha256": sha256(lineage_path) if lineage_path.is_file() else None,
        "legacy_adapter": not required,
    }


class TabularDataSteps:
    def __init__(self, config: Mapping[str, Any], transformer=None):
        self.config = deepcopy(dict(config))
        self.scenario = _scenario(config)
        self.transformer = transformer
        self.table_format = self.config.get("table_format", "delta")
        self.bronze_mode = self.config.get("bronze_mode", "raw")
        if self.table_format not in ("delta", "parquet"):
            raise ValueError("config.table_format must be delta or parquet")
        if self.bronze_mode not in ("raw", "normalized"):
            raise ValueError("config.bronze_mode must be raw or normalized")
        _require_gold(self.config)

    def convert(self, operation: str, inputs: Mapping[str, Path], output: Path) -> dict:
        if operation not in ("in2silver", "in2bronze", "bronze2silver"):
            raise ValueError(f"Unsupported conversion: {operation}")
        if len(inputs) != 1:
            raise ValueError("A source conversion requires exactly one named input")
        output = Path(output)
        _empty_outputs([output], [Path(path) for path in inputs.values()])
        name, path = next(iter(inputs.items()))
        dataset = {**self.config.get("dataset", {}), **self.config.get("dataset_overrides", {}).get(name, {})}
        if operation == "in2bronze" and self.bronze_mode == "raw":
            return _raw_bronze(self.config, name, path, output, dataset)
        if operation == "bronze2silver":
            # Legacy normalized bronze is a table, not the declared original CSV/XLSX.
            normalized = ((Path(path).is_dir() and (Path(path) / "data.parquet").is_file())
                          or (Path(path).is_file() and Path(path).suffix.lower() == ".parquet"))
            read_dataset = {} if normalized else dataset
        else:
            read_dataset = dataset
        frame, source = read_tabular(path, read_dataset)
        transformed = False
        transformer = None
        if operation != "in2bronze":
            hook = self.transformer if self.transformer is not None else self.config.get("hook")
            transformer = _load_transformer(hook)
            if transformer is not None:
                context = {**_context(self.config, operation), "input_name": name, "dataset": deepcopy(dataset)}
                method = getattr(transformer, "transform", transformer)
                frame = method(frame.copy(), context)
                _check_frame(frame)
                transformed = True
            _validate_columns(frame, dataset)
        lineage = _lineage(self.config, operation, {name: source})
        lineage["medallion_stage"] = "bronze" if operation == "in2bronze" else "silver"
        lineage["transformation"] = "consumer-hook" if transformed else "none"
        if transformed:
            lineage["transformer"] = _transformer_identity(transformer)
        lineage["learned_preprocessing"] = False
        return _write_frame(frame, output, lineage, format="parquet" if operation == "in2bronze" else self.table_format)

    def merge(self, inputs: Mapping[str, Path], output: Path) -> dict:
        if not inputs:
            raise ValueError("Merge requires at least one named input")
        output = Path(output)
        _empty_outputs([output], [Path(path) for path in inputs.values()])
        frames, sources = [], {}
        versions = self.config.get("input_versions", {})
        if not isinstance(versions, Mapping):
            raise ValueError("config.input_versions must map input names to Delta versions")
        for name, path in inputs.items():
            dataset = dict(self.config.get("dataset_overrides", {}).get(name, {}))
            if versions.get(name) is not None:
                if dataset.get("delta_version") is not None and dataset["delta_version"] != versions[name]:
                    raise ValueError("dataset_overrides.delta_version disagrees with input_versions")
                dataset["delta_version"] = versions[name]
            frame, source = read_tabular(path, dataset)
            _validate_columns(frame, self.config.get("dataset_overrides", {}).get(name, {}))
            if _is_inference(self.config):
                _reject_target(frame, self.scenario)
            frames.append(frame)
            sources[name] = source
        policy = self.config.get("merge", {"mode": "concat"})
        mode = policy.get("mode", "concat")
        if mode == "concat":
            merged = _concat(frames)
        elif mode == "join":
            keys, how, validate = policy.get("on"), policy.get("how", "inner"), policy.get("validate")
            if (not isinstance(keys, list) or not keys or len(set(keys)) != len(keys)
                    or any(not isinstance(key, str) or not key for key in keys)):
                raise ValueError("Join requires explicit unique nonempty merge.on keys")
            if how not in ("inner", "left") or validate not in ("one_to_one", "many_to_one"):
                raise ValueError("Join requires inner/left and explicit one_to_one/many_to_one validation")
            for index, frame in enumerate(frames):
                if not set(keys).issubset(frame.columns) or frame[keys].isna().any().any():
                    raise ValueError("Join keys must exist and must not contain missing values")
                if (validate == "one_to_one" or index > 0) and frame.duplicated(keys).any():
                    from pandas.errors import MergeError
                    raise MergeError(f"Join keys are not unique for {validate} validation")
            merged = frames[0]
            for frame in frames[1:]:
                if (set(merged.columns) & set(frame.columns)) - set(keys):
                    raise ValueError("Join inputs have overlapping non-key columns; rename explicitly in a consumer hook")
                merged = merged.merge(frame, on=keys, how=how, validate=validate, sort=False)
        else:
            raise ValueError("merge.mode must be concat or join")
        _validate_columns(merged, self.config.get("merged_dataset", {}))
        lineage = _lineage(self.config, "merge", sources)
        lineage["medallion_stage"] = "gold"
        lineage["transformation"] = mode
        lineage["learned_preprocessing"] = False
        lineage["merge"] = deepcopy(policy)
        return _write_frame(merged, output, lineage, format=self.table_format)

    def split(self, inputs: Mapping[str, Path], output: Path, *, train=None, validation=None, test=None) -> dict:
        import pandas as pd
        from azure_esml.base_layer.tables import read_table, write_table
        from ml_model_factory.data import prepare

        if len(inputs) != 1:
            raise ValueError("Split requires exactly one merged gold input")
        output = Path(output)
        external = {name: Path(path) for name, path in {"train": train, "validation": validation, "test": test}.items()
                    if path is not None}
        if external and len(external) != 3:
            raise ValueError("Provide all three separate train, validation and test outputs, or none")
        aml_format = self.config.get("aml_table_format", self.table_format)
        if aml_format not in ("delta", "parquet"):
            raise ValueError("config.aml_table_format must be delta or parquet")
        _empty_outputs([output, *external.values()], [Path(path) for path in inputs.values()])
        validate_scenario(self.scenario)
        name, selected = next(iter(inputs.items()))
        selected = Path(selected)
        read_dataset = dict(self.config.get("gold_dataset", {}))
        if _require_gold(self.config):
            gold_lineage = selected / "lineage.json"
            _no_links(gold_lineage)
            if not selected.is_dir() or not gold_lineage.is_file():
                raise ValueError("Split requires a gold artifact with medallion_stage='gold' lineage")
            metadata = load_json(gold_lineage).get("output", {})
            if metadata.get("format") == "delta":
                read_dataset.setdefault("delta_version", metadata.get("delta_version"))
        frame, source = read_tabular(selected, read_dataset)
        binding = _gold_source(self.config, selected, source)
        if not _complete_labels(frame, self.scenario["target"]):
            raise ValueError("Every training record must have a complete target label")
        # Keep the canonical custom/evaluation splitter and its Parquet projections.
        # Separate AML inputs are written below as native, version-pinned tables.
        projection = Path.cwd() / f".esml-projection-{uuid4().hex}"
        projection.mkdir()
        try:
            canonical = projection / "data.parquet"
            _model_frame(frame, self.scenario).to_parquet(canonical, index=False)
            binding["projection_sha256"] = sha256(canonical)
            binding["rows"] = len(frame)
            manifest = prepare(self.scenario, canonical, output)
        finally:
            shutil.rmtree(projection)
        binding["model_input_format"] = "parquet"
        binding["timestamp_policy"] = "UTC-naive at forecasting model boundary; gold is unchanged"
        binding["split_sha256"] = manifest["split_sha256"]
        binding["split_rows"] = manifest["split_rows"]
        manifest["gold_source"] = binding
        manifest["source_sha256"] = source["sha256"]
        manifest["note"] = "Parquet model-boundary projections of the pinned gold snapshot; gold-source.json binds lineage and hashes."
        if external:
            manifest["aml_tables"] = {}
            for split, path in external.items():
                if aml_format == self.table_format == "parquet" and self.bronze_mode == "normalized":
                    # The explicit normalized/Parquet migration adapter preserves
                    # existing exported bytes as well as their canonical hashes.
                    shutil.copytree(output / split, path, dirs_exist_ok=True)
                    _, metadata = read_table(path)
                else:
                    metadata = write_table(pd.read_parquet(output / split / "data.parquet"), path, format=aml_format)
                manifest["aml_tables"][split] = metadata
        write_json(output / "gold-source.json", binding)
        write_json(output / "manifest.json", manifest)
        lineage = _lineage(self.config, "split", {name: source})
        lineage["split_sha256"] = manifest["split_sha256"]
        lineage["gold_source"] = binding
        write_json(output / "lineage.json", lineage)
        return manifest


def _model_tags(config: Mapping[str, Any], scenario: dict, mode: str) -> dict:
    from ml_model_factory.tags import TAG_KEYS, build_tags, validate_tags

    supplied = {key: value for key, value in config.get("tags", {}).items() if key in TAG_KEYS}
    scope = {key: supplied[key] for key in ("aifactory", "project", "environment") if key in supplied}
    engine = supplied.get("training_engine", config.get("training_engine", "azureml"))
    tags = build_tags(scenario, scope, mode=mode, engine=engine, require_scope=True)
    for field in ("tag_schema", "aifactory", "project", "environment", "use_case", "task_type",
                  "training_environment", "training_mode", "training_engine"):
        if field in supplied and supplied[field] != tags.get(field):
            raise ValueError(f"Model tag {field!r} disagrees with this scenario or training mode")
    return validate_tags({**tags, **supplied}, require_scope=True)


def _prepared(scenario: dict, path: Path, config: Mapping[str, Any] | None = None) -> None:
    config = dict(config or {})
    _no_links(path)
    _no_links(path / "manifest.json")
    manifest = load_json(path / "manifest.json")
    if (manifest.get("scenario") != scenario["name"] or manifest.get("task") != scenario["task"]
            or manifest.get("features") != scenario["features"]):
        raise ValueError("Prepared manifest does not match the selected scenario/task/features")
    if _require_gold(config):
        gold_path = path / "gold-source.json"
        _no_links(gold_path)
        if not gold_path.is_file():
            raise ValueError("Prepared input requires a verified gold-source binding")
        binding = load_json(gold_path)
        if binding != manifest.get("gold_source"):
            raise ValueError("Prepared gold-source binding does not match its manifest")
        if (binding.get("medallion_stage") != "gold" or binding.get("legacy_adapter") is not False
                or binding.get("purpose") != "training" or _is_inference(config)):
            raise ValueError("Training requires gold-derived training snapshots, never inference/legacy inputs")
        if (binding.get("scope") != _scope(config) or binding.get("use_case") != scenario["name"]
                or binding.get("scenario") != _scenario_binding(scenario)):
            raise ValueError("Prepared gold scope/scenario does not match the selected configuration")
        for key in ("data_version", "snapshot_id"):
            expected = config.get("request", {}).get(key)
            if expected is not None and binding.get(key) != expected:
                raise ValueError(f"Prepared gold {key} does not match the selected snapshot")
        if (binding.get("input_format") not in ("delta", "parquet")
                or binding.get("model_input_format") != "parquet"
                or not isinstance(binding.get("files"), dict) or not binding["files"]
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in binding["files"].values())
                or not isinstance(binding.get("input_fingerprint"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", binding["input_fingerprint"])
                or _hash(binding["files"]) != binding["input_fingerprint"]
                or binding["input_fingerprint"] != manifest.get("source_sha256")
                or binding.get("split_sha256") != manifest.get("split_sha256")
                or binding.get("split_rows") != manifest.get("split_rows")
                or binding.get("rows") != sum(manifest.get("split_rows", {}).values())):
            raise ValueError("Prepared gold fingerprint/projection binding is invalid")
        version = binding.get("delta_version")
        if binding["input_format"] == "delta" and (isinstance(version, bool) or not isinstance(version, int) or version < 0):
            raise ValueError("Prepared Delta gold requires an immutable integer delta_version")
    for name in ("train", "validation", "test"):
        frame, _ = read_tabular(path / name)
        if sha256(path / name / "data.parquet") != manifest.get("split_sha256", {}).get(name):
            raise ValueError(f"Prepared {name} content does not match its manifest hash")
        if len(frame) != manifest.get("split_rows", {}).get(name):
            raise ValueError(f"Prepared {name} row count does not match its manifest")
        if not _complete_labels(frame, scenario["target"]):
            raise ValueError("Every prepared record must have a complete target label")


def _forecast_history(scenario: dict, future, history) -> None:
    import pandas as pd

    forecast = scenario["forecast"]
    series, time = forecast.get("series_columns", []), forecast["time_column"]
    keys = series + [time]
    if not _complete_labels(history, scenario["target"]):
        raise ValueError("Forecast history requires complete observed target values")
    for frame in (future, history):
        if not set(keys).issubset(frame.columns) or frame[keys].isna().any().any():
            raise ValueError("Forecast series/time keys must exist and must not be missing")
        if frame.duplicated(keys).any():
            raise ValueError("Forecast series/time keys must be unique")
    historical, requested = history.loc[:, keys].copy(), future.loc[:, keys].copy()
    historical[time] = pd.to_datetime(historical[time], errors="raise")
    requested[time] = pd.to_datetime(requested[time], errors="raise")
    if not series:
        if historical[time].max() >= requested[time].min():
            raise ValueError("Forecast history must precede every requested timestamp")
        return
    last = historical.groupby(series, dropna=False, sort=False)[time].max().rename("history_end")
    first = requested.groupby(series, dropna=False, sort=False)[time].min().rename("future_start")
    bounds = first.to_frame().join(last, how="left", validate="one_to_one")
    if bounds["history_end"].isna().any() or (bounds["history_end"] >= bounds["future_start"]).any():
        raise ValueError("Every forecast series needs observed history preceding requested timestamps")


def _forecast_evaluation(scenario: dict, prepared: Path, model: Path, output: Path) -> dict:
    import pandas as pd
    from ml_model_factory.evaluation import metrics_for
    from ml_model_factory.serving import forecast_predictions

    test, _ = read_tabular(prepared / "test")
    history, _ = read_tabular(prepared / "validation")
    _forecast_history(scenario, test, history)
    predictions = forecast_predictions(model, test, history, scenario)
    availability = {}
    metrics = metrics_for("forecasting", test[scenario["target"]], predictions, metric_availability=availability)
    cohorts = {}
    columns = scenario["forecast"].get("series_columns", []) + scenario.get("sensitive_features", [])
    for column in dict.fromkeys(columns):
        cohorts[column] = {
            str(value): {
                "rows": len(rows), "small_sample_warning": len(rows) < 30,
                **metrics_for("forecasting", rows[scenario["target"]], predictions[rows.index]),
            }
            for value, rows in test.reset_index(drop=True).groupby(column, dropna=False)
        }
    report = {
        "scenario": scenario["name"], "task": "forecasting", "test_rows": len(test),
        "metrics": metrics, "metric_availability": availability, "cohorts": cohorts,
        "responsible_ai": {
            "tooling": "Held-out temporal/series errors; MLflow sklearn forecast adapter",
            "azure_dashboard": "Not generated; use a supported task-specific RAI component separately.",
            "limitations": [
                "Validation observations are known history; test targets are never supplied to the model.",
                "Cohort differences are observational, not proof of fairness.",
                "TCN/PyTorch forecasting requires a task-specific adapter.",
            ],
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"actual": test[scenario["target"]].to_numpy(), "prediction": predictions}).to_parquet(
        output / "predictions.parquet", index=False,
    )
    write_json(output / "metrics.json", metrics)
    write_json(output / "responsible-ai.json", report)
    try:
        quality_gate(metrics, scenario.get("quality", {}))
    except ValueError as exc:
        write_json(output / "quality-gate.json", {"passed": False, "reason": str(exc)})
        raise
    write_json(output / "quality-gate.json", {"passed": True, "limits": scenario.get("quality", {})})
    return report


class FactoryModelSteps:
    def __init__(self, config: Mapping[str, Any]):
        self.config = deepcopy(dict(config))
        self.scenario = _scenario(config)
        self.mode = config.get("mode", config.get("tags", {}).get("training_mode", "custom"))
        if self.mode not in ("custom", "automl"):
            raise ValueError("config.mode must be custom or automl")

    def training_manual(self, prepared: Path, output: Path) -> dict:
        from ml_model_factory.tags import stamp_model
        from ml_model_factory.training import train

        prepared, output = Path(prepared), Path(output)
        _empty_outputs([output], [prepared])
        if self.mode != "custom":
            raise ValueError("training_manual requires custom training mode")
        validate_scenario(self.scenario)
        tags = _model_tags(self.config, self.scenario, self.mode)
        _prepared(self.scenario, prepared, self.config)
        train(self.scenario, prepared, output)
        stamp_model(output, tags)
        write_json(output / "runinfo.json", {
            **_context(self.config, "training_manual"), "model_tags": tags,
            "prepared": str(prepared.resolve()), "prepared_manifest_sha256": sha256(prepared / "manifest.json"),
            "mlmodel_sha256": sha256(output / "MLmodel"),
        })
        return tags

    def evaluate(self, prepared: Path, model: Path, output: Path) -> dict:
        import yaml
        from ml_model_factory.evaluation import evaluate
        from ml_model_factory.selection import build_evidence
        from ml_model_factory.tags import scope_tags

        prepared, model, output = Path(prepared), Path(model), Path(output)
        _empty_outputs([output], [prepared, model])
        validate_scenario(self.scenario)
        _prepared(self.scenario, prepared, self.config)
        tags = _model_tags(self.config, self.scenario, self.mode)
        definition = yaml.safe_load((model / "MLmodel").read_text(encoding="utf-8"))
        if self.mode == "custom" and definition.get("metadata", {}).get("model_factory_tags") != tags:
            raise ValueError("Custom model artifact tags disagree with the evaluated job metadata")
        evaluator = _forecast_evaluation if self.mode == "automl" and self.scenario["task"] == "forecasting" else evaluate
        report = evaluator(self.scenario, prepared, model, output)
        gate = load_json(output / "quality-gate.json")
        if gate.get("passed") is not True:
            raise ValueError("Evaluator did not emit a passing quality gate")
        lineage = {
            "scenario": self.scenario["name"], "task": self.scenario["task"], "mode": self.mode,
            "model_output": "model", "mlmodel_sha256": sha256(model / "MLmodel"), "model_tags": tags,
        }
        write_json(output / "lineage.json", lineage)
        write_json(output / "model-tags.json", tags)
        evidence = build_evidence(self.scenario, prepared, model, load_json(output / "metrics.json"), gate)
        evidence["scope"] = scope_tags(tags, require=True)
        write_json(output / "comparison.json", evidence)
        return report

    def inference(self, inputs: Mapping[str, Path], model: Path, output: Path) -> dict:
        import mlflow.pyfunc
        import numpy as np
        import pandas as pd
        import yaml
        from ml_model_factory.evaluation import prediction_vector
        from ml_model_factory.serving import forecast_predictions
        from ml_model_factory.tags import assert_scope, scope_tags

        model, output = Path(model), Path(output)
        _empty_outputs([output], [model, *[Path(path) for path in inputs.values()]])
        named = {name: path for name, path in inputs.items() if name != "history"}
        if len(named) != 1:
            raise ValueError("Inference requires one named feature input and optional named history")
        request = self.config.get("request", {})
        version = request.get("model_version")
        if (isinstance(version, bool) or not isinstance(version, (str, int))
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(version))
                or str(version).lower() in ("latest", "active", "champion", "production", "0")):
            raise ValueError("Inference requires an explicit immutable request.model_version, never latest")
        if not isinstance(request.get("run_id"), str) or not request["run_id"].strip():
            raise ValueError("Inference requires an explicit request.run_id")
        scope = scope_tags(self.config.get("tags", {}), require=True)
        name, path = next(iter(named.items()))
        frame, source = read_tabular(path, self.config.get("inference_dataset", {}))
        _reject_target(frame, self.scenario)
        column = self.config.get("request_id_column", request.get("request_id_column", "request_id"))
        if not isinstance(column, str) or not column.strip() or column == "prediction":
            raise ValueError("request_id_column must be a nonempty name distinct from prediction")
        if column not in frame:
            raise ValueError(f"Inference requires the request ID column {column!r}")
        ids = frame[column]
        if ids.isna().any() or ids.astype(str).str.strip().eq("").any() or not ids.astype(str).is_unique:
            raise ValueError("Inference request IDs must be unique, nonblank and nonmissing")
        definition = yaml.safe_load((model / "MLmodel").read_text(encoding="utf-8"))
        stored = definition.get("metadata", {}).get("model_factory_tags")
        if stored:
            assert_scope(stored, scope)
            if stored.get("use_case") != self.scenario["name"] or stored.get("task_type") != self.scenario["task"]:
                raise ValueError("Model identity disagrees with the selected inference scenario")
        factory_path = model / "factory.json"
        factory = load_json(factory_path) if factory_path.is_file() else {}
        recorded_versions = ((stored or {}).get("model_version"), factory.get("model_version"))
        if any(value is not None and str(value) != str(version) for value in recorded_versions):
            raise ValueError("Model artifact version disagrees with the pinned request.model_version")
        features = list(self.scenario["features"])
        sources = {name: source}
        if self.scenario["task"] == "forecasting":
            forecast = self.scenario["forecast"]
            features = list(dict.fromkeys(features + forecast.get("series_columns", []) + [forecast["time_column"]]))
        missing = set(features) - set(frame.columns)
        if missing:
            raise ValueError(f"Inference is missing model features: {sorted(missing)}")
        if self.scenario["task"] == "forecasting" and self.mode == "automl":
            if "history" not in inputs:
                raise ValueError("AutoML forecasting inference requires --input history PATH with observed labels")
            history, history_source = read_tabular(inputs["history"])
            frame = _model_frame(frame, self.scenario)
            history = _model_frame(history, self.scenario)
            _forecast_history(self.scenario, frame, history)
            sources["history"] = history_source
            predictions = forecast_predictions(model, frame, history, self.scenario)
        else:
            if "history" in inputs:
                raise ValueError("This model uses its fitted history; external history requires the AutoML forecast adapter")
            features_frame = frame.loc[:, features].copy()
            if self.scenario["task"] == "forecasting":
                features_frame = _model_frame(features_frame, self.scenario)
            predictions = mlflow.pyfunc.load_model(str(model)).predict(features_frame)
        predictions = prediction_vector(predictions, len(frame))
        if pd.isna(predictions).any() or (np.issubdtype(predictions.dtype, np.number) and not np.isfinite(predictions).all()):
            raise ValueError("Model must produce a finite, nonmissing prediction for each request")
        result = pd.DataFrame({column: ids.to_numpy(), "prediction": predictions})
        output.mkdir(parents=True, exist_ok=True)
        result.to_parquet(output / "predictions.parquet", index=False)
        info = {
            **_lineage(self.config, "inference", sources), "scope": scope,
            "run_id": request["run_id"], "data_date_utc": request.get("data_date_utc"),
            "model_version": str(version), "model_path": str(model.resolve()),
            "mlmodel_sha256": sha256(model / "MLmodel"), "request_id_column": column,
            "rows": len(result), "predictions_sha256": sha256(output / "predictions.parquet"),
        }
        write_json(output / "runinfo.json", info)
        return info


def run_operation(
    operation: str, config: Mapping[str, Any], output: Path, *,
    inputs: Mapping[str, Path] | None = None, prepared: Path | None = None,
    model: Path | None = None, train: Path | None = None,
    validation: Path | None = None, test: Path | None = None, transformer=None,
    data_date_utc: str | None = None, run_id: str | None = None, model_version: str | None = None,
    data_version: str | None = None, snapshot_id: str | None = None,
    project_name: str | None = None, environment: str | None = None,
) -> dict:
    """Execute a step, rejecting request rebinding behind compiled artifact paths."""
    if operation not in OPERATIONS:
        raise ValueError(f"Unsupported runtime operation: {operation!r}")
    supplied = {
        "data_date_utc": data_date_utc, "run_id": run_id, "model_version": model_version,
        "data_version": data_version, "snapshot_id": snapshot_id,
        "project_name": project_name, "environment": environment,
    }
    tags = config.get("tags", {})
    expected_values = {
        **config.get("request", {}),
        "project_name": f"project{tags['project']}" if tags.get("project") else None,
        "environment": tags.get("environment"),
    }
    for key, value in supplied.items():
        if value is None:
            continue
        expected = expected_values.get(key)
        if (key == "model_version" and value == "none" and expected is None
                and operation != "inference" and not _is_inference(config)):
            continue
        if expected is None or str(value) != str(expected):
            raise ValueError(f"Runtime {key} differs from the compiled request; rebuild the plan to rebind artifact paths")
    inputs = {name: Path(path) for name, path in (inputs or {}).items()}
    if any(not isinstance(name, str) or not name.strip() for name in inputs):
        raise ValueError("Input names must be nonempty strings")
    if operation in ("in2silver", "in2bronze", "bronze2silver", "merge", "split"):
        steps = TabularDataSteps(config, transformer=transformer)
        if operation == "merge":
            return steps.merge(inputs, output)
        if operation == "split":
            return steps.split(inputs, output, train=train, validation=validation, test=test)
        return steps.convert(operation, inputs, output)
    steps = FactoryModelSteps(config)
    if operation in ("training_manual", "evaluate") and prepared is None:
        raise ValueError(f"{operation} requires --prepared")
    if operation in ("evaluate", "inference") and model is None:
        raise ValueError(f"{operation} requires --model")
    if operation == "training_manual":
        return steps.training_manual(prepared, output)
    if operation == "evaluate":
        return steps.evaluate(prepared, model, output)
    return steps.inference(inputs, model, output)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=OPERATIONS, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", action="append", nargs=2, metavar=("NAME", "PATH"), default=[])
    for name in ("prepared", "model", "train", "validation", "test"):
        parser.add_argument("--" + name, type=Path)
    for name in ("data-date-utc", "run-id", "model-version", "data-version", "snapshot-id", "project-name", "environment"):
        parser.add_argument("--" + name)
    args = parser.parse_args(argv)
    inputs = {}
    for name, path in args.input:
        if name in inputs:
            parser.error(f"Duplicate input name: {name}")
        inputs[name] = Path(path)
    run_operation(
        args.operation, load_json(args.config), args.output, inputs=inputs,
        prepared=args.prepared, model=args.model, train=args.train, validation=args.validation, test=args.test,
        data_date_utc=args.data_date_utc, run_id=args.run_id, model_version=args.model_version,
        data_version=args.data_version, snapshot_id=args.snapshot_id,
        project_name=args.project_name, environment=args.environment,
    )


if __name__ == "__main__":
    main()
