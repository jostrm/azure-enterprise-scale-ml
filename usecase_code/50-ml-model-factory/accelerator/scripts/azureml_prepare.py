"""Expose real MLTable output ports instead of unsupported output subpath bindings."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Checkouts use accelerator/src; rendered job bundles use a flat package.
_code_root = Path(__file__).resolve().parents[1]
_import_root = _code_root / "src" if (_code_root / "src" / "ml_model_factory").is_dir() else _code_root
sys.path.insert(0, str(_import_root))

from ml_model_factory.layout import python_environment


def main():
    parser = argparse.ArgumentParser()
    for name in ("scenario", "input", "prepared"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("train", "validation", "test"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--lake-config", type=Path)
    args = parser.parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    image = scenario["task"].startswith("image_")
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
    ], env=python_environment(), check=True)
    for split in ("train", "validation", "test"):
        if getattr(args, split) is None:
            continue
        origin = args.prepared / split
        if not (origin / "MLTable").is_file():
            raise FileNotFoundError(f"Preparation did not emit {split}/MLTable")
        # AutoML reads image bytes from the absolute prepared-tree URLs in data.jsonl; copy only manifests.
        shutil.copytree(origin, getattr(args, split), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("images") if image else None)
        if image:
            continue
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
