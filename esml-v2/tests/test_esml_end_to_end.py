from pathlib import Path
import re
import shlex
import subprocess
import sys

import pandas as pd
import pytest

from azure_esml import ESMLProject, LakeSettings, PipelineRequest, PipelineType
from ml_model_factory.config import load_json


ROOT = Path(__file__).resolve().parents[1]


def local_commands(plan, raw_inputs, directory):
    """Execute the rendered commands, substituting only Azure's mount/binding transport."""
    produced = {}
    top_inputs = dict(plan.document["inputs"])
    top_inputs.update(raw_inputs)
    top_outputs = {}
    for name in plan.document.get("outputs", {}):
        path = directory / "outputs" / name
        path.mkdir(parents=True)
        top_outputs[name] = str(path)

    def input_value(value):
        if isinstance(value, dict):
            return value["path"]
        if not isinstance(value, str):
            return str(value)
        if value.startswith("${{parent.inputs."):
            return input_value(top_inputs[value.removeprefix("${{parent.inputs.").removesuffix("}}")])
        match = re.fullmatch(r"\$\{\{parent.jobs.([^.]+).outputs.([^}]+)}}", value)
        if match:
            return produced[match[1]][match[2]]
        return value

    for name, node in plan.document["jobs"].items():
        assert node["type"] == "command", "Native AutoML is schema-tested, not executed as fake local training"
        component = node["component"]
        assert isinstance(component, dict)
        inputs = {key: input_value(value) for key, value in node["inputs"].items()}
        outputs = {}
        for port, value in node["outputs"].items():
            if isinstance(value, str) and value.startswith("${{parent.outputs."):
                outputs[port] = top_outputs[value.removeprefix("${{parent.outputs.").removesuffix("}}")]
            else:
                path = directory / "steps" / name / port
                path.mkdir(parents=True)
                outputs[port] = str(path)
        command = component["command"]
        for port, value in inputs.items():
            command = command.replace("${{inputs." + port + "}}", str(value))
        for port, value in outputs.items():
            command = command.replace("${{outputs." + port + "}}", value)
        assert "${{" not in command
        arguments = shlex.split(command)
        assert arguments[:3] == ["python", "-m", "azure_esml.domain_layer.runtime"]
        code = (plan.base_path / component["code"]).resolve()
        completed = subprocess.run([sys.executable, *arguments[1:]], cwd=code, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr + completed.stdout
        produced[name] = outputs
    return {name: Path(path) for name, path in top_outputs.items()}


def config_for(task):
    value = load_json(ROOT / "examples" / "app_layer" / "lake_settings.json")
    model = value["models"][0]
    model.update(source={"provider": "lake", "kind": "dataset"}, ml_type=task,
                 features=["x"], label="y", quality={}, categorical_features=[], sensitive_features=[],
                 custom={"algorithm": "logistic_regression" if task == "classification" else "ridge"})
    model.pop("ml_metric")
    model.pop("automl")
    if task == "forecasting":
        model["forecast"] = {"time_column": "date", "frequency": "D", "horizon": 3}
        model["features"] = ["date"]
        model["custom"] = {"algorithm": "seasonal_naive", "seasonal_period": 7}
    return value


@pytest.mark.parametrize("task", ["classification", "regression", "forecasting"])
def test_generated_multi_dataset_training_and_inference_commands(task, tmp_path):
    config = config_for(task)
    project = ESMLProject(LakeSettings.from_dict(config))
    frame = pd.DataFrame({"x": [float(i % 7) + i / 1000 for i in range(100)],
                          "y": [(i % 7 > 2) * 1 if task == "classification" else 3.0 * (i % 7) + i / 100
                                for i in range(100)]})
    if task == "forecasting":
        frame = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=100), "y": [i % 7 + 1.0 for i in range(100)]})
    raw = {}
    for index, dataset in enumerate(project.settings.model().datasets):
        folder = tmp_path / dataset.name
        folder.mkdir()
        frame.iloc[index * 50:(index + 1) * 50].to_csv(folder / "data.csv", index=False)
        raw[dataset.name] = str(folder)
    plan = project.create_pipeline(PipelineType.IN_2_GOLD_TRAINING_MANUAL,
                                   PipelineRequest("2026-09-13", "training-local"), output=tmp_path / "training")
    source_ports = {key: value for key, value in plan.document["inputs"].items()
                    if isinstance(value, dict) and value.get("type") == "uri_folder"}
    mounts = {}
    for port, binding in source_ports.items():
        matching = [name for name in raw if f"/{name}/" in binding["path"]]
        assert len(matching) == 1, binding
        mounts[port] = raw[matching[0]]
    outputs = local_commands(plan, mounts, tmp_path / "execution")
    assert load_json(outputs["report"] / "quality-gate.json")["passed"]
    evidence = load_json(outputs["report"] / "comparison.json")
    assert evidence["scope"] == project.settings.scope
    assert evidence["task_type"] == task
    assert (outputs["model"] / "MLmodel").is_file()
    assert (outputs["gold"] / "_delta_log").is_dir()
    assert (outputs["train"] / "_delta_log").is_dir()
    assert (outputs["silver_ds01_diabetes"] / "_delta_log").is_dir()
    assert (outputs["bronze_ds01_diabetes"] / "data.csv").read_bytes() == (Path(raw["ds01_diabetes"]) / "data.csv").read_bytes()
    assert load_json(outputs["prepared"] / "gold-source.json")
    inference = project.create_pipeline(PipelineType.GOLD_INFERENCE,
                                        PipelineRequest("2026-09-14", "inference-local", model_version="7"),
                                        output=tmp_path / "inference")
    gold = tmp_path / "gold"
    gold.mkdir()
    selected = frame.tail(3) if task == "forecasting" else frame.head(5)
    features = selected.drop(columns="y").assign(request_id=[f"row-{i}" for i in range(len(selected))])
    from azure_esml.base_layer.tables import write_table
    write_table(features, gold)
    bindings = {"model": str(outputs["model"])}
    for key, binding in inference.document["inputs"].items():
        if isinstance(binding, dict) and binding.get("type") == "uri_folder":
            bindings[key] = str(gold)
    predictions = local_commands(inference, bindings, tmp_path / "inference-execution")
    assert (predictions["inference"] / "runinfo.json").is_file()


def test_notebooks_are_valid_and_render_without_cloud_calls(tmp_path):
    import nbformat
    for path in sorted((ROOT / "examples" / "app_layer").glob("*.ipynb")):
        document = nbformat.read(path, as_version=4)
        nbformat.validate(document)
        for cell in document.cells:
            if cell.cell_type == "code":
                compile(cell.source, str(path), "exec")
