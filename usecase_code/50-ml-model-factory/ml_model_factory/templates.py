"""Copy generic templates without overwriting consumer edits or copying local data."""

import shutil
from pathlib import Path

from .config import load_json, write_json
from .data import sha256


MANIFEST = ".factory-template-manifest.json"
EXCLUDED = {
    ".git", ".venv", "__pycache__", ".pytest_cache", ".ipynb_checkpoints",
    "data", "outputs", "generated", "mlruns", "build", "dist", "lake-data",
    ".test-artifacts", ".azureml-test-artifacts", ".orchestration-matrix-artifacts",
}


def instantiate(source: Path, destination: Path) -> dict:
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.is_relative_to(source):
        raise ValueError("Consumer destination must be outside the source template tree")
    if not (source / "pyproject.toml").is_file() or not (source / "ml_model_factory").is_dir():
        raise ValueError("Source is not a model-factory template root")
    old = load_json(destination / MANIFEST).get("files", {}) if (destination / MANIFEST).is_file() else {}
    files = {}
    for file in source.rglob("*"):
        relative = file.relative_to(source)
        if any(part in EXCLUDED or part.endswith(".egg-info") or part.startswith(".fixture-validation-")
               for part in relative.parts):
            continue
        if file.is_symlink():
            raise ValueError(f"Template source contains a symbolic link: {relative}")
        if not file.is_file() or file.suffix == ".pyc":
            continue
        if file.name in (".env", "kaggle.json", MANIFEST) or file.name.startswith("runtime") or file.name.endswith(".local.json"):
            continue
        files[relative.as_posix()] = sha256(file)
    conflicts = []
    for relative, digest in files.items():
        target = destination / relative
        if target.exists() and (not target.is_file() or sha256(target) not in (digest, old.get(relative))):
            conflicts.append(relative)
    if conflicts:
        raise ValueError("Consumer files have local edits; no files copied: " + ", ".join(conflicts))
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    manifest = {"schema": 1, "template_version": "0.1.0", "files": files,
                "retained_removed_files": sorted(set(old) - set(files))}
    write_json(destination / MANIFEST, manifest)
    return {"destination": str(destination), "copied_files": len(files),
            "retained_removed_files": manifest["retained_removed_files"]}
