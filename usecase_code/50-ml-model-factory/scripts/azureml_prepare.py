"""Expose real MLTable output ports instead of unsupported output subpath bindings."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    for name in ("scenario", "input", "prepared"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("train", "validation", "test"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--lake-config", type=Path)
    args = parser.parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    lake = None
    if args.lake_config is not None:
        from ml_model_factory.azureml import _lake_context

        lake = _lake_context(scenario, {"lake": json.loads(args.lake_config.read_text(encoding="utf-8"))})
        destinations = [path.resolve() for path in (
            args.prepared, args.train, args.validation, args.test,
        ) if path is not None]
        for index, destination in enumerate(destinations):
            if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
                raise ValueError("Lake preparation outputs must be empty; use a new run_id")
            for other in destinations[:index]:
                if destination == other or destination in other.parents or other in destination.parents:
                    raise ValueError("Prepared and split output ports must not overlap")
    subprocess.run([
        sys.executable, "-m", "ml_model_factory", "prepare",
        "--scenario", str(args.scenario), "--input", str(args.input),
        "--output", str(args.prepared),
    ], check=True)
    for split in ("train", "validation", "test"):
        if getattr(args, split) is None:
            continue
        origin = args.prepared / split
        if not (origin / "MLTable").is_file():
            raise FileNotFoundError(f"Preparation did not emit {split}/MLTable")
        shutil.copytree(origin, getattr(args, split), dirs_exist_ok=True)
        from ml_model_factory.data import read_frame
        columns = list(scenario["features"]) + [scenario["target"]]
        if scenario["task"] == "forecasting":
            columns += scenario["forecast"].get("series_columns", []) + [scenario["forecast"]["time_column"]]
        read_frame(origin).loc[:, list(dict.fromkeys(columns))].to_parquet(
            getattr(args, split) / "data.parquet", index=False,
        )
    if lake is not None:
        from ml_model_factory.config import write_json

        manifest_path = args.prepared / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["lake"] = lake
        write_json(manifest_path, manifest)
        write_json(args.prepared / "lake-manifest.json", lake)


if __name__ == "__main__":
    main()
