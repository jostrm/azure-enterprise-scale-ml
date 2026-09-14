from pathlib import Path

import pytest
import yaml

from ml_model_factory.azureml import render
from ml_model_factory.config import load_json


ROOT = Path(__file__).resolve().parents[2] / "usecase_code" / "50-ml-model-factory"


def test_explicit_custom_cpu_images_can_use_common_lake_without_fictitious_gpu(tmp_path):
    scenario = load_json(ROOT / "scenarios" / "image-object-detection.json")
    runtime = {"compute": "existing-cpu", "datastore": "common_lake",
               "input_data": "azureml://datastores/common_lake/paths/mlops/v1/projects/project001/dataset/in/"}
    bundle = render(scenario, runtime, tmp_path / "cpu", ROOT, mode="custom")
    pipeline = yaml.safe_load(Path(bundle["pipeline"]).read_text())
    assert pipeline["jobs"]["train"]["compute"] == "azureml:existing-cpu"
    assert pipeline["jobs"]["evaluate"]["compute"] == "azureml:existing-cpu"
    assert pipeline["inputs"]["raw"]["path"] == runtime["input_data"]
    with pytest.raises(ValueError, match="gpu_compute"):
        render(scenario, runtime, tmp_path / "automl", ROOT, mode="automl")
