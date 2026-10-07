"""Explicit checkout layout; submission bundles keep their own flat code layout."""

from pathlib import Path
import os
import re


PACKAGE = Path("accelerator") / "src" / "ml_model_factory"


def python_environment() -> dict[str, str]:
    environment = os.environ.copy()
    import_root = Path(__file__).resolve().parent.parent
    environment["PYTHONPATH"] = str(import_root) + os.pathsep + environment.get("PYTHONPATH", "")
    return environment


def is_template_root(path: Path) -> bool:
    return (path / "pyproject.toml").is_file() and (path / PACKAGE / "__init__.py").is_file()


def source_root(source: Path | None = None) -> Path:
    """Locate templates, never treating an installed site-packages directory as a checkout."""
    if source is not None:
        root = Path(source).expanduser().resolve()
        if not is_template_root(root):
            raise ValueError(f"Source is not a model-factory template root: {root}")
        return root
    current = Path.cwd().resolve()
    for root in (current, *current.parents):
        if is_template_root(root):
            return root
    module = Path(__file__).resolve()
    if module.parent.name == "ml_model_factory" and module.parent.parent.name == "src":
        root = module.parents[3]
        if is_template_root(root):
            return root
    raise ValueError("Model-factory templates were not found; pass --source with a checkout root")


def bundle_metadata(manifest: str) -> str:
    """Transform captured checkout metadata into a flat bundle manifest with LF newlines."""
    manifest = manifest.replace("\r\n", "\n").replace("\r", "\n")
    manifest, count = re.subn(
        r'(?m)^where = \["accelerator/src"\]$',
        'where = ["."]',
        manifest,
    )
    if count != 1:
        raise ValueError("Expected accelerator/src package discovery in the source pyproject.toml")
    return manifest


def bundle_metadata_bytes(source: Path) -> bytes:
    """Return deterministic metadata for a flat job bundle, including provenance hashing."""
    return bundle_metadata((source / "pyproject.toml").read_text(encoding="utf-8")).encode("utf-8")


def write_bundle_metadata(source: Path, destination: Path) -> None:
    destination.write_bytes(bundle_metadata_bytes(source))
