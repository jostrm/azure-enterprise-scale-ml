"""Build one self-contained distribution from the canonical, shared v2 engines."""

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile

from setuptools import build_meta


ROOT = Path(__file__).resolve().parent


@contextmanager
def _source():
    # The sdist already contains the engines; repository builds take their canonical source.
    engines = ROOT / "ml_model_factory"
    if not engines.is_dir():
        engines = ROOT.parent / "usecase_code" / "50-ml-model-factory" / "ml_model_factory"
    if not (engines / "__init__.py").is_file():
        raise RuntimeError("Shared v2 engine source is missing; build from the repository or complete sdist")
    with tempfile.TemporaryDirectory(prefix="azure-esml-build-") as folder:
        staging = Path(folder)
        for name in ("pyproject.toml", "esml_build.py", "MANIFEST.in", "LICENSE"):
            shutil.copy2(ROOT / name, staging / name)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".*", "*.egg-info")
        shutil.copytree(ROOT / "azure_esml", staging / "azure_esml", ignore=ignore)
        shutil.copytree(engines, staging / "ml_model_factory", ignore=ignore)
        policy = engines.parent / "model-selection.json"
        if policy.is_file():
            resources = staging / "azure_esml" / "resources"
            resources.mkdir(exist_ok=True)
            shutil.copy2(policy, resources / policy.name)
        for name in ("examples", "tests"):
            if (ROOT / name).is_dir():
                shutil.copytree(ROOT / name, staging / name, ignore=ignore)
        previous = Path.cwd()
        os.chdir(staging)
        try:
            yield
        finally:
            os.chdir(previous)


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    destination = str(Path(metadata_directory).resolve())
    with _source():
        return build_meta.prepare_metadata_for_build_wheel(destination, config_settings)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    destination = str(Path(wheel_directory).resolve())
    metadata = str(Path(metadata_directory).resolve()) if metadata_directory else None
    with _source():
        return build_meta.build_wheel(destination, config_settings, metadata)


def build_sdist(sdist_directory, config_settings=None):
    destination = str(Path(sdist_directory).resolve())
    with _source():
        return build_meta.build_sdist(destination, config_settings)
