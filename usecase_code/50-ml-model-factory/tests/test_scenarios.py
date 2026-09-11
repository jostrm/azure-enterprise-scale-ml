"""Offline contract tests; generated fixtures are not Kaggle-run evidence."""

import ast
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from ml_model_factory.config import TASKS, load_json, validate_scenario
from ml_model_factory.notebooks import render_notebooks


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = sorted((ROOT / "scenarios").glob("*.json"))


@pytest.fixture
def workspace():
    path = ROOT / ".test-artifacts" / uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_scenario_contract(path):
    scenario = validate_scenario(load_json(path))
    assert scenario["name"] == path.stem
    assert scenario["dataset"]["provider"] == "kaggle"
    if scenario["dataset"].get("status") in {"required-selection", "license-review"}:
        with pytest.raises(ValueError, match="Dataset"):
            validate_scenario(scenario, require_dataset=True)
    else:
        validate_scenario(scenario, require_dataset=True)
    if scenario["task"] == "forecasting":
        assert scenario["custom"]["algorithm"] == "seasonal_naive"
        assert scenario["custom"]["seasonal_period"] > 0
    if scenario["task"].startswith("image_"):
        assert scenario["vision"]["pretrained"] is False
        assert scenario["vision"]["max_steps_per_epoch"] <= 5


def test_all_tasks_and_honest_regression():
    scenarios = [load_json(path) for path in SCENARIOS]
    assert {scenario["task"] for scenario in scenarios} == TASKS
    assert load_json(ROOT / "scenarios" / "titanic.json")["task"] == "classification"
    assert load_json(ROOT / "scenarios" / "insurance-regression.json")["target"] == "charges"


def test_orangejuice_never_substitutes_brand_classification():
    scenario = load_json(ROOT / "scenarios" / "orangejuice.json")
    assert scenario["dataset"]["status"] == "required-selection"
    assert scenario["dataset"]["slug"] is None
    with pytest.raises(ValueError, match="required-selection"):
        validate_scenario(scenario, require_dataset=True)
    assert "Ask the user before substituting" in scenario["dataset"]["notes"]


@pytest.mark.parametrize("mode", ["custom", "automl"])
@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_notebooks_are_portable_valid_python(path, mode, workspace):
    result = render_notebooks(load_json(path), workspace, mode)
    assert len(result["notebooks"]) == 1
    notebook = load_json(Path(result["notebooks"][0]))
    assert notebook["nbformat"] == 4
    assert len({cell["id"] for cell in notebook["cells"]}) == len(notebook["cells"])
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            ast.parse(cell["source"])
            assert cell["execution_count"] is None
            assert not cell["outputs"]
    source = json.dumps(notebook)
    assert "from ml_model_factory.azureml import submit" in source
    assert "azureml_cli.py" in source
    assert "USE_LAKE = False" in source and "lake-plan" in source
    assert "C:\\\\" not in source
    assert "SUBMIT_SDK = False" in source


def test_databricks_sources_parse_and_have_no_inline_credential():
    for path in (ROOT / "databricks").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"))
    stream = (ROOT / "databricks" / "stream_score.py").read_text(encoding="utf-8")
    assert "dbutils.secrets.get" in stream
    assert "SharedAccessKey=" not in stream
    assert "checkpointLocation" in stream and "event_time" in stream
    assert "dropDuplicatesWithinWatermark" in stream
    job = load_json(ROOT / "databricks" / "job-template.json")
    assert "existing_cluster_id" in job["tasks"][0]
    assert "new_cluster" not in job["tasks"][0]


def test_checked_in_notebooks_match_renderer(workspace):
    categories = {
        "classification": Path("classification"),
        "regression": Path("regression"),
        "forecasting": Path("timeseries-forecasting"),
        "image_classification": Path("computer-vision") / "multi-class",
        "image_classification_multilabel": Path("computer-vision") / "multi-label",
        "image_object_detection": Path("computer-vision") / "object-detection",
        "image_instance_segmentation": Path("computer-vision") / "instance-segmentation",
    }
    for path in SCENARIOS:
        scenario = load_json(path)
        for mode in ("automl", "custom"):
            suffix = Path("azure-automl") / "notebook" if mode == "automl" else Path("notebook")
            checked_in = ROOT / "batch" / categories[scenario["task"]] / suffix / f"{scenario['name']}-{mode}.ipynb"
            rendered = Path(render_notebooks(scenario, workspace, mode)["notebooks"][0])
            assert load_json(checked_in) == load_json(rendered)
