"""Kaggle ingestion and leakage-aware tabular preparation."""

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import safe_relative, validate_scenario, write_json


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest(scenario: dict, output: Path) -> Path:
    validate_scenario(scenario, require_dataset=True)
    import kagglehub
    from kagglehub.exceptions import UnauthenticatedError

    dataset = scenario["dataset"]
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Refusing to overwrite nonempty dataset directory: {output}")
    try:
        if dataset["kind"] == "competition":
            downloaded = Path(kagglehub.competition_download(dataset["slug"]))
        else:
            handle = f"{dataset['slug']}/versions/{dataset['version']}"
            downloaded = Path(kagglehub.dataset_download(handle))
    except UnauthenticatedError as exc:
        raise ValueError(
            "Kaggle authentication is required. Configure your Kaggle credentials securely and "
            "accept any applicable competition rules yourself before retrying; the factory does not accept terms."
        ) from exc
    relative = safe_relative(dataset["file"])
    selected = downloaded / relative
    if not selected.exists():
        raise FileNotFoundError(f"Kaggle archive does not contain {relative}; check dataset.file")
    files = sorted(downloaded.rglob("*"))
    total = sum(path.stat().st_size for path in files if path.is_file())
    maximum = dataset.get("max_unpacked_bytes", 10 * 1024**3)
    if total > maximum:
        raise ValueError(f"Dataset expands to {total} bytes, exceeding {maximum}")
    if any(path.is_symlink() for path in files):
        raise ValueError("Dataset contains symbolic links; refusing to copy")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(downloaded, output, dirs_exist_ok=True)
    manifest = {
        "provider": "kaggle", "slug": dataset["slug"], "kind": dataset["kind"],
        "version": dataset.get("version"), "license": dataset.get("license"),
        "source_url": dataset.get("source_url"),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            str(path.relative_to(output)).replace("\\", "/"): sha256(path)
            for path in sorted(output.rglob("*")) if path.is_file()
        },
    }
    write_json(output / "provenance.json", manifest)
    return output / relative


def read_frame(path: Path):
    import pandas as pd

    path = Path(path)
    if path.is_dir():
        path = path / "data.parquet"
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported tabular input {path}; expected CSV or Parquet")


def prepare(scenario: dict, input_path: Path, output: Path) -> dict:
    import pandas as pd
    from sklearn.model_selection import GroupShuffleSplit, train_test_split

    validate_scenario(scenario)
    frame = read_frame(input_path)
    required = list(dict.fromkeys(
        scenario["features"] + [scenario["target"]] + scenario.get("sensitive_features", [])
    ))
    group_column = scenario.get("split", {}).get("group_column")
    if group_column:
        required = list(dict.fromkeys(required + [group_column]))
    if scenario["task"] == "forecasting":
        forecast = scenario["forecast"]
        required = list(dict.fromkeys(required + [forecast["time_column"]] + forecast.get("series_columns", [])))
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")
    frame = frame.loc[:, required].copy()
    if frame.empty or frame[scenario["target"]].isna().any():
        raise ValueError("Training data must be nonempty and every target must be labeled")
    if scenario["task"] != "forecasting":
        for column in scenario["features"]:
            if column not in scenario.get("categorical_features", []):
                numeric = pd.to_numeric(frame[column], errors="raise")
                if ((numeric < -(2**53)) | (numeric > 2**53)).any() and pd.api.types.is_integer_dtype(numeric):
                    raise ValueError(f"{column} contains integers too large for lossless floating-point conversion")
                frame[column] = numeric.astype("float64")
    config = scenario.get("split", {})
    if scenario["task"] == "forecasting":
        time = forecast["time_column"]
        frame[time] = pd.to_datetime(frame[time], errors="raise")
        series = forecast.get("series_columns", [])
        if frame.duplicated(series + [time]).any():
            raise ValueError("Each series/timestamp pair must be unique")
        horizon = forecast["horizon"]
        groups = frame.groupby(series, dropna=False) if series else [(None, frame)]
        parts = {"train": [], "validation": [], "test": []}
        for key, group in groups:
            group = group.sort_values(time)
            if len(group) < 2 * horizon + 4:
                raise ValueError(f"Series {key!r} needs at least {2*horizon+4} rows")
            expected = pd.date_range(group[time].iloc[0], periods=len(group), freq=forecast["frequency"])
            if not (group[time].to_numpy() == expected.to_numpy()).all():
                raise ValueError(f"Series {key!r} has gaps or does not match the configured frequency")
            parts["train"].append(group.iloc[:-2*horizon])
            parts["validation"].append(group.iloc[-2*horizon:-horizon])
            parts["test"].append(group.iloc[-horizon:])
        splits = {key: pd.concat(groups, ignore_index=True) for key, groups in parts.items()}
    elif group_column:
        groups = frame[group_column]
        if groups.isna().any() or groups.nunique() < 3:
            raise ValueError("Entity-group splitting requires at least three nonempty groups")
        seed = config.get("seed", 42)
        first = GroupShuffleSplit(n_splits=1, test_size=config.get("test_size", 0.2), random_state=seed)
        train_indices, test_indices = next(first.split(frame, groups=groups))
        remainder, test = frame.iloc[train_indices], frame.iloc[test_indices]
        fraction = config.get("validation_size", 0.2) / (1 - config.get("test_size", 0.2))
        second = GroupShuffleSplit(n_splits=1, test_size=fraction, random_state=seed)
        train_indices, validation_indices = next(second.split(remainder, groups=remainder[group_column]))
        train, validation = remainder.iloc[train_indices], remainder.iloc[validation_indices]
        if scenario["task"] == "classification":
            observed = set(train[scenario["target"]])
            if len(observed) < 2 or not set(frame[scenario["target"]]).issubset(observed):
                raise ValueError("Entity split leaves unseen classes outside training; revise groups or split seed")
        splits = {"train": train, "validation": validation, "test": test}
    else:
        seed = config.get("seed", 42)
        test_size = config.get("test_size", 0.2)
        validation_size = config.get("validation_size", 0.2)
        classification = scenario["task"] == "classification"
        if classification and frame[scenario["target"]].nunique() < 2:
            raise ValueError("Classification requires at least two target classes")
        train, test = train_test_split(
            frame, test_size=test_size, random_state=seed,
            stratify=frame[scenario["target"]] if classification else None,
        )
        train, validation = train_test_split(
            train, test_size=validation_size / (1 - test_size), random_state=seed,
            stratify=train[scenario["target"]] if classification else None,
        )
        splits = {"train": train, "validation": validation, "test": test}
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Prepared output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        folder = output / name
        folder.mkdir()
        rows.to_parquet(folder / "data.parquet", index=False)
        (folder / "MLTable").write_text(
            "paths:\n  - file: ./data.parquet\ntransformations:\n  - read_parquet:\n", encoding="utf-8"
        )
    if scenario["name"] == "titanic":
        frame.to_parquet(output / "titanic.parquet", index=False)
    manifest = {
        "scenario": scenario["name"], "task": scenario["task"],
        "dataset": scenario["dataset"], "source_sha256": sha256(Path(input_path)),
        "split_rows": {name: len(rows) for name, rows in splits.items()},
        "split_sha256": {name: sha256(output / name / "data.parquet") for name in splits},
        "split": config, "features": scenario["features"],
        "split_policy": "chronological-per-series" if scenario["task"] == "forecasting" else
                        "entity-group-disjoint" if group_column else "random-stratified" if scenario["task"] == "classification" else "random",
        "note": "Source hash is recorded; Kaggle download provenance is in the ingestion directory.",
    }
    write_json(output / "manifest.json", manifest)
    return manifest
