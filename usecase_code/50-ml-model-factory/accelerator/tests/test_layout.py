"""Checkout, notebook, and isolated submission layout contracts."""

import configparser
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from ml_model_factory import layout
from ml_model_factory.azureml import render
from ml_model_factory.cli import parser
from ml_model_factory.config import load_json
from ml_model_factory.notebooks import render_notebooks
from ml_model_factory.templates import instantiate


ROOT = Path(__file__).resolve().parents[2]


def checkout(path):
    (path / layout.PACKAGE).mkdir(parents=True)
    (path / layout.PACKAGE / "__init__.py").write_text("")
    (path / "pyproject.toml").write_text(
        '[tool.setuptools.packages.find]\nwhere = ["accelerator/src"]\ninclude = ["ml_model_factory*"]\n'
    )
    return path


def test_package_metadata_stays_in_generated_environment():
    config = configparser.ConfigParser()
    config.read(ROOT / "setup.cfg")
    assert config["egg_info"]["egg_base"] == "ml-environment"
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert manifest["tool"]["setuptools"]["packages"]["find"]["where"] == ["accelerator/src"]


def test_source_manifest_includes_templates_but_not_local_payloads():
    from setuptools._distutils.filelist import FileList

    maintained = (
        "pyproject.toml", "setup.cfg", "MANIFEST.in", "readme.md",
        "accelerator/src/ml_model_factory/__init__.py",
        "accelerator/scripts/azureml_prepare.py", "accelerator/environments/azureml-custom.yml",
        "accelerator/databricks/train.py", "accelerator/schemas/monitoring.schema.json",
        "user-config/model/scenarios/titanic.json", "user-config/model/model-selection.json",
        "user-config/lake.example.json", "user-config/databricks/job-template.json",
        "usecase-type/batch/classification/notebook/titanic-custom.ipynb",
        "data/readme.md", "data/in/readme.md", "data/out/readme.md",
        "ml-environment/readme.md", "ml-environment/outputs/readme.md", "ml-environment/mlruns/readme.md",
    )
    generated = (
        "data/in/private.csv", "data/out/private.parquet", "ml-environment/outputs/model/MLmodel",
        "ml-environment/mlruns/secret.json", ".venv/Lib/site-packages/example.py",
        "user-config/runtime.local.json", "user-config/lake.local.json",
        "accelerator/src/ml_model_factory/__pycache__/config.pyc",
        "usecase-type/batch/classification/notebook/.ipynb_checkpoints/titanic-custom-checkpoint.ipynb",
    )
    files = FileList()
    files.set_allfiles([str(Path(path)) for path in (*maintained, *generated)])
    for line in (ROOT / "MANIFEST.in").read_text().splitlines():
        files.process_template_line(line)
    selected = set(files.files)
    assert {str(Path(path)) for path in maintained}.issubset(selected)
    assert not selected.intersection(str(Path(path)) for path in generated)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_bundle_metadata_transforms_captured_text_without_reading_source(newline, monkeypatch):
    from ml_model_factory.azureml import bundle_metadata

    captured = newline.join((
        "[project]", 'name = "example"', "[tool.setuptools.packages.find]",
        'where = ["accelerator/src"]', 'include = ["ml_model_factory*"]', "",
    ))
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("Must use captured bytes"))
    result = bundle_metadata(captured)
    assert 'where = ["."]\n' in result
    assert 'name = "example"\n' in result
    assert "\r" not in result


def test_default_source_from_nested_consumer_and_explicit_source(tmp_path, monkeypatch):
    consumer = checkout(tmp_path / "consumer")
    nested = consumer / "usecase-type" / "batch"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert layout.source_root() == consumer
    assert layout.source_root(ROOT) == ROOT
    assert parser().parse_args(["instantiate", "--destination", str(tmp_path / "copy")]).source is None


def test_editable_source_detection_outside_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "cwd", lambda: Path(tmp_path.anchor))
    assert layout.source_root() == ROOT


def test_installed_package_never_implies_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "cwd", lambda: Path(tmp_path.anchor))
    module = tmp_path / "site-packages" / "ml_model_factory" / "layout.py"
    module.parent.mkdir(parents=True)
    module.write_text("")
    (module.parent.parent / "pyproject.toml").write_text("")
    monkeypatch.setattr(layout, "__file__", str(module))
    with pytest.raises(ValueError, match="pass --source"):
        layout.source_root()
    with pytest.raises(ValueError, match="template root"):
        layout.source_root(module.parent.parent)


def test_template_ownership_docs_and_customer_config_are_preserved(tmp_path):
    source = checkout(tmp_path / "source")
    destination = tmp_path / "consumer"
    for relative in (
        "data/in/private.csv", "data/out/prepared.parquet", "data/out/lake-data/private.json",
        "ml-environment/outputs/private.json", "ml-environment/cache/private.bin",
        "ml-environment/mlruns/private.json", "data/in/readme-private.txt",
        ".venv/secret", "accelerator/src/package.egg-info/PKG-INFO",
        "user-config/runtime.local.json", "user-config/lake.local.json",
    ):
        file = source / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("private")
    for relative in (
        "data/README.md", "data/in/README.md", "data/out/README.md",
        "ml-environment/README.md", "ml-environment/outputs/README.md",
        "ml-environment/mlruns/readme.md",
        "user-config/model/scenarios/example.json", "user-config/runtime.example.json",
    ):
        file = source / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("template")
    instantiate(source, destination)
    assert not any(file.read_text() == "private" for file in destination.rglob("*") if file.is_file())
    assert (destination / "data/in/README.md").read_text() == "template"
    assert (destination / "ml-environment/outputs/README.md").read_text() == "template"
    assert (destination / "ml-environment/mlruns/readme.md").read_text() == "template"
    assert (destination / "user-config/runtime.example.json").is_file()
    customer = destination / "user-config/model/scenarios/example.json"
    customer.write_text("customer")
    with pytest.raises(ValueError, match="local edits"):
        instantiate(source, destination)
    assert customer.read_text() == "customer"


def test_flat_render_bundle_is_self_contained_and_packages_only_engine(tmp_path):
    from setuptools import find_packages

    runtime = {"compute": "existing-cpu", "input_data": "azureml://datastores/raw/paths/train.csv"}
    render(load_json(ROOT / "user-config/model/scenarios/titanic.json"), runtime, tmp_path / "bundle", ROOT, "custom")
    code = tmp_path / "bundle/code"
    assert (code / "pyproject.toml").read_bytes() == layout.bundle_metadata_bytes(ROOT)
    metadata = tomllib.loads((code / "pyproject.toml").read_text())
    assert metadata["tool"]["setuptools"]["packages"]["find"]["where"] == ["."]
    assert find_packages(where=str(code), include=["ml_model_factory*"]) == ["ml_model_factory"]
    assert all(file.suffix == ".py" for file in (code / "ml_model_factory").rglob("*") if file.is_file())
    assert (code / "scripts/azureml_prepare.py").is_file()
    assert (tmp_path / "bundle/environments/azureml-custom.yml").is_file()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import ml_model_factory; print(ml_model_factory.__file__)"],
        cwd=code, env=env, capture_output=True, text=True, check=True,
    )
    assert Path(result.stdout.strip()) == code / "ml_model_factory/__init__.py"


@pytest.mark.parametrize("script", [
    "azureml_prepare.py", "azureml_evaluate.py", "azureml_cli.py", "azureml_sdk.py",
    "monitoring_job.py", "activate_monitoring.py",
])
def test_direct_scripts_bootstrap_src_from_unrelated_directory(tmp_path, script):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "accelerator/scripts" / script), "--help"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", ["custom", "automl"])
def test_notebook_paths_and_child_imports(tmp_path, monkeypatch, mode):
    scenario = load_json(ROOT / "user-config/model/scenarios/titanic.json")
    notebook = load_json(Path(render_notebooks(scenario, tmp_path, mode)["notebooks"][0]))
    monkeypatch.chdir(ROOT / "usecase-type/batch")
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    namespace = {}
    exec(next(cell["source"] for cell in notebook["cells"] if cell["cell_type"] == "code"), namespace)
    assert namespace["ROOT"] == ROOT
    assert namespace["RAW"] == ROOT / "data/in/titanic"
    assert namespace["PREPARED"] == ROOT / "data/out/titanic" / mode / "prepared"
    assert namespace["WORK"] == ROOT / "ml-environment/outputs/titanic" / mode
    assert namespace["LAKE_ROOT"] == ROOT / "data/out/lake-data"
    assert namespace["LAKE_CONFIG"] == ROOT / "user-config/lake.local.json"
    assert namespace["RUNTIME"] == ROOT / "user-config/runtime.local.json"
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    namespace["factory"]("validate", "--scenario", namespace["SCENARIO"])
    assert calls[0][1]["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(ROOT / "accelerator/src")
    assert calls[0][1]["env"]["MLFLOW_TRACKING_URI"] == (ROOT / "ml-environment/mlruns").as_uri()
