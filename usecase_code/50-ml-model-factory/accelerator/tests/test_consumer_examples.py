"""Consumer scenarios: synthetic sources, narrowed example leaves and reviewed model numbers."""

import json
import subprocess
from pathlib import Path

import pytest

from ml_model_factory.config import load_json, write_json
from ml_model_factory.examples import render_all
from ml_model_factory.templates import instantiate
from ml_model_factory.usecases import catalog, find, scenarios_by_task, selected_scenarios


ROOT = Path(__file__).resolve().parents[2]
LEAF = "usecase-type/batch/classification/azureml-pipeline"
NAME = "49-agent-churn"


def consumer(**changes):
    template = load_json(ROOT / "user-config" / "model" / "scenarios" / "churn.json")
    scenario = {key: value for key, value in template.items() if key != "dataset"}
    scenario.update(name=NAME, example_leaves=[LEAF], dataset={
        "provider": "lake", "kind": "dataset", "file": "telco-churn-synthetic.csv", "version": 1,
        "status": "configured", "license": "synthetic",
        "synthetic": {"generator": "telco-churn", "seed": 49, "rows": 7043}})
    scenario.update(changes)
    return scenario


def code_of(path: Path) -> list[str]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]


def test_built_in_esml_notebooks_resolve_reviewed_model_numbers():
    source = "\n".join(code_of(ROOT / LEAF / "churn-custom-pipeline.ipynb"))
    assert 'scenario_number(config, scenario["name"])' in source
    assert "SCENARIO_NUMBERS[" not in source


def test_only_selected_leaves_render_a_consumer_scenario():
    leaf = find("batch", "classification", "azureml-pipeline")
    other = find("online", "classification", "azureml-pipeline")
    scenarios = [load_json(ROOT / "user-config" / "model" / "scenarios" / "churn.json"), consumer()]
    assert [item["name"] for item in selected_scenarios(leaf, scenarios)] == ["churn", NAME]
    assert [item["name"] for item in selected_scenarios(other, scenarios)] == ["churn"]


@pytest.mark.parametrize("leaves", [
    ["usecase-type/batch/regression/azureml-pipeline"],
    ["usecase-type/batch/classification/unknown-stack"],
])
def test_example_leaves_must_name_supported_leaves_of_the_task(tmp_path, leaves):
    write_json(tmp_path / f"{NAME}.json", consumer(example_leaves=leaves))
    with pytest.raises(ValueError, match="supported classification leaf"):
        scenarios_by_task(tmp_path)


def test_synthetic_consumer_copy_renders_one_notebook_that_runs_dry(tmp_path, monkeypatch):
    factory = tmp_path / "factory"
    instantiate(ROOT, factory)
    write_json(factory / "user-config" / "model" / "scenarios" / f"{NAME}.json", consumer())
    notebook = f"{LEAF}/{NAME}-custom-pipeline.ipynb"
    assert sorted(render_all(factory)["stale"]) == [notebook, f"{LEAF}/readme.md"]
    render_all(factory, write=True)
    check = render_all(factory)
    assert check["stale"] == [] and check["unexpected_notebooks"] == []
    assert f"[{NAME}-custom-pipeline.ipynb]" in (factory / LEAF / "readme.md").read_text(encoding="utf-8")
    code = code_of(factory / notebook)
    source = "\n".join(code)
    assert "RUN_SYNTHESIZE = False" in code[0] and "RUN_INGEST" not in source
    assert 'factory("synthesize", "--scenario", SCENARIO, "--output", RAW)' in source
    assert 'scenario_number(config, scenario["name"])' in source
    header = json.loads((factory / notebook).read_text(encoding="utf-8"))["cells"][0]["source"]
    assert "Synthetic source" in "".join(header) and "Kaggle-only" not in "".join(header)
    monkeypatch.chdir(factory / LEAF)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError(args)))
    namespace = {"__name__": "__main__"}
    for cell in code:
        exec(compile(cell, notebook, "exec"), namespace)
    assert namespace["scenario"]["name"] == NAME and namespace["MODE"] == "custom"
    assert len([leaf for leaf in catalog() if leaf.supported and selected_scenarios(leaf, [consumer()])]) == 1
