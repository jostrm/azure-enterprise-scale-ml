"""Use-case catalog, generated leaf notebooks/READMEs and their CLI contracts."""

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

import pytest

from ml_model_factory import cli
from ml_model_factory.examples import render_all
from ml_model_factory.usecases import PATTERNS, TASK_FOLDERS, TECHNOLOGIES, catalog, find, scenarios_by_task


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = scenarios_by_task(ROOT / "user-config" / "model" / "scenarios")
LEAVES = [leaf for leaf in catalog() if leaf.supported]
NOTEBOOKS = [(leaf, scenario) for leaf in LEAVES for scenario in SCENARIOS[leaf.task]]


def test_catalog_covers_every_leaf_folder_and_states_unsupported_reasons():
    leaves = catalog()
    assert len(leaves) == len(PATTERNS) * len(TASK_FOLDERS) * len(TECHNOLOGIES) == 126
    for leaf in leaves:
        folder = ROOT / Path(*leaf.folder.parts)
        assert (folder / "readme.md").is_file(), folder
    unsupported = [leaf for leaf in leaves if not leaf.supported]
    assert {(leaf.pattern, leaf.task, leaf.mode) for leaf in unsupported} == {("streaming", "forecasting", "automl")}
    assert all("seasonal-naive" in leaf.reason for leaf in unsupported)
    assert find("batch", "classification", "notebook").run_key == "custom"
    assert find("online", "classification", "notebook").run_key == "online-custom"
    assert find("batch", "regression", "azureml-pipeline").esml
    assert not find("batch", "computer-vision/multi-class", "azureml-pipeline").esml


def test_generated_notebooks_and_readmes_match_the_catalog():
    result = render_all(ROOT)
    assert result["stale"] == [], "Run: python -m ml_model_factory usecase-examples --write"
    assert result["unexpected_notebooks"] == []
    assert result["notebooks"] == len(NOTEBOOKS) == 192


def test_root_readme_explains_implementation_dimensions_and_counts():
    text = (ROOT / "readme.md").read_text(encoding="utf-8")
    for count in ("12 use cases", "60 combinations", "105 implementations", "126 catalog leaves", "192 notebooks"):
        assert count in text
    for path in (
        r"usecase-type\batch\classification\azure-automl",
        r"usecase-type\batch\classification\databricks-azureml-pipeline-step",
        r"usecase-type\online\classification\azureml-pipeline",
        r"usecase-type\streaming\regression\databricks-notebook",
    ):
        assert path in text
    assert "both variants" in text


def test_root_readme_cloud_status_covers_all_implementations_without_private_scope():
    text = (ROOT / "readme.md").read_text(encoding="utf-8")
    section = text.split("## Azure test status\n", 1)[1].split("\n## Start here", 1)[0]
    rows = [line for line in section.splitlines() if re.match(r"^\| (batch|online|streaming) \|", line)]
    assert len(rows) == 21
    expected = {(leaf.pattern, leaf.task_folder) for leaf in catalog()}
    actual, passed = set(), 0
    for line in rows:
        fields = [field.strip() for field in line.strip("|").split("|")]
        assert len(fields) == 7
        actual.add(tuple(fields[:2]))
        for value in fields[2:]:
            assert re.fullmatch(r"(Tested and works|Impl TBA)(\[\^[a-z0-9-]+\])*", value)
            passed += value == "Tested and works"
            if value.startswith("Impl TBA"):
                assert "[^" in value
    assert actual == expected
    assert f"{passed}/105" in text.split("**Status:**", 1)[1].splitlines()[0]
    references = set(re.findall(r"\[\^([a-z0-9-]+)\](?!:)", section))
    definitions = set(re.findall(r"^\[\^([a-z0-9-]+)\]:", section, re.M))
    assert references == definitions
    assert not re.search(r"spider|/subscriptions/|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", section, re.I)


def _parsers():
    root = cli.parser()

    def walk(parser, prefix=()):
        found = {prefix: parser}
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    found.update(walk(child, prefix + (name,)))
        return found

    return walk(root)


PARSERS = _parsers()


def _factory_calls(source: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "factory":
            literals = [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
            yield literals


@pytest.mark.parametrize("leaf, scenario", NOTEBOOKS,
                         ids=[f"{leaf.folder.as_posix()}::{scenario['name']}" for leaf, scenario in NOTEBOOKS])
def test_leaf_notebooks_are_valid_cli_contracts_and_run_dry(leaf, scenario, monkeypatch):
    path = ROOT / Path(*leaf.folder.parts) / leaf.notebook_name(scenario["name"])
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4 and len({cell["id"] for cell in notebook["cells"]}) == len(notebook["cells"])
    code = [cell["source"] for cell in notebook["cells"] if cell["cell_type"] == "code"]
    text = json.dumps(notebook)
    assert "C:\\\\" not in text and "SharedAccessKey" not in text and "?sig=" not in text
    for source in code:
        for literals in _factory_calls(source):
            command, position = (), 0
            while position < len(literals) and command + (literals[position],) in PARSERS:
                command += (literals[position],)
                position += 1
            assert command, f"{path.name}: unknown factory command {literals[:2]}"
            options = {option for action in PARSERS[command]._actions for option in action.option_strings}
            unknown = [value for value in literals[position:] if value.startswith("--") and value not in options]
            assert not unknown, f"{path.name}: {' '.join(command)} does not accept {unknown}"
    switches = re.findall(r"^([A-Z_]+) = (True|False)$", code[0], re.M)
    assert switches and all(value == "False" for _, value in switches)
    monkeypatch.chdir(ROOT / Path(*leaf.folder.parts))
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError(f"Dry run must not start processes: {args}")

    monkeypatch.setattr(subprocess, "run", forbidden)
    namespace = {"__name__": "__main__"}
    for source in code:
        exec(compile(source, str(path), "exec"), namespace)
    assert namespace["PATTERN"] == leaf.pattern and namespace["MODE"] == leaf.mode
    assert namespace["WORK"] == ROOT / "ml-environment" / "outputs" / scenario["name"] / leaf.run_key


def test_usecases_cli_lists_routes_and_status(capsys):
    assert cli.main(["usecases", "--pattern", "streaming", "--task-folder", "timeseries-forecasting"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["total"] == 6 and result["supported"] == 4
    automl = next(item for item in result["leaves"] if item["technology"] == "azure-automl/notebook")
    assert automl["supported"] is False and automl["notebooks"] == []
    custom = next(item for item in result["leaves"] if item["technology"] == "notebook")
    assert custom["notebooks"] == ["air-passengers-custom.ipynb", "delhi-weather-custom.ipynb", "orangejuice-custom.ipynb"]
