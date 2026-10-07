"""Copy generic templates without overwriting consumer edits or copying local data."""

import os
import shutil
from pathlib import Path

from .config import load_json, write_json
from .data import sha256
from .layout import source_root


MANIFEST = ".factory-template-manifest.json"
EXCLUDED = {
    ".git", ".venv", "__pycache__", ".pytest_cache", ".ipynb_checkpoints",
    "data", "ml-environment", "outputs", "generated", "mlruns", "build", "dist", "lake-data",
    ".cache", "cache", ".ruff_cache", ".mypy_cache",
    ".test-artifacts", ".azureml-test-artifacts", ".orchestration-matrix-artifacts",
}
DOCUMENTATION_ROOTS = (
    "data", "data/in", "data/out", "data/in/lake-data", "data/out/lake-data",
    "ml-environment", "ml-environment/outputs", "ml-environment/mlruns", "ml-environment/cache",
)


def _excluded(name: str) -> bool:
    return name in EXCLUDED or name.endswith(".egg-info") or name.startswith(".fixture-validation-")


def _template_files(source: Path):
    for directory, folders, files in os.walk(source):
        base = Path(directory)
        for name in folders:
            if not _excluded(name) and (base / name).is_symlink():
                raise ValueError(f"Template source contains a symbolic link: {(base / name).relative_to(source)}")
        folders[:] = [name for name in folders if not _excluded(name)]
        yield from (base / name for name in files if not _excluded(name))
    # Preserve ownership instructions, not generated data beneath those scaffolds.
    for relative in DOCUMENTATION_ROOTS:
        directory = source / relative
        if directory.is_dir() and not any(path.is_symlink() for path in (directory, *directory.parents)):
            yield from (file for file in directory.iterdir() if file.name.lower() == "readme.md")


def instantiate(source: Path | None, destination: Path) -> dict:
    source, destination = source_root(source), Path(destination).resolve()
    if source == destination or destination.is_relative_to(source):
        raise ValueError("Consumer destination must be outside the source template tree")
    old = load_json(destination / MANIFEST).get("files", {}) if (destination / MANIFEST).is_file() else {}
    files = {}
    for file in _template_files(source):
        relative = file.relative_to(source)
        if file.is_symlink():
            raise ValueError(f"Template source contains a symbolic link: {relative}")
        if not file.is_file() or file.suffix == ".pyc":
            continue
        if file.name in (".env", "kaggle.json", "runtime.json", MANIFEST) or file.name.endswith(".local.json"):
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
