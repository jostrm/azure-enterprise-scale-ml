from pathlib import Path
from unittest.mock import MagicMock

import pytest

from azure_esml import ESMLProject, LakeSettings
from azure_esml.domain_layer.rollout import AzureMLRollout, SCENARIO_NUMBERS, model_from_scenario
from ml_model_factory.config import load_json, write_json


ROOT = Path(__file__).resolve().parents[1]


def configuration():
    config = load_json(ROOT / "examples" / "app_layer" / "lake_settings.json")
    config.pop("use_common_datalake_storage", None)
    config.pop("storage_targets", None)
    return config


def test_all_scenarios_have_stable_model_numbers():
    assert SCENARIO_NUMBERS["titanic"] == 1
    assert SCENARIO_NUMBERS["diabetes"] == 2
    assert set(SCENARIO_NUMBERS.values()) == set(range(1, 12))
    scenario = {"name": "diabetes", "task": "classification", "target": "Outcome", "features": ["Glucose"],
                "dataset": {"provider": "kaggle", "kind": "dataset"}}
    model = model_from_scenario(scenario, input_path="mlops/v1/project/data/in", compute="m02-cpu-dev")
    assert model["model_name"] == "M02_diabetes"
    assert model["dataset_folder_names"] == ["diabetes"]
    assert model["naming_style"] == "model-prefix"
    assert model["datasets"]["diabetes"]["input_path"] == "mlops/v1/project/data/in"


def test_prepare_has_no_cloud_side_effects_and_keeps_all_outputs(tmp_path):
    project = ESMLProject(LakeSettings.from_dict(configuration()))
    backend = MagicMock()
    backend.target = project.target
    project = ESMLProject(project.settings, backend=backend)
    result = AzureMLRollout(project, tmp_path).prepare(model_number=11, mode="custom",
                                                     data_date_utc="2026-09-28", run_id="first-run")
    assert result["cloud_submitted"] is False
    assert {item["output"] for item in result["data_assets"]} >= {"gold", "train", "validation", "test", "report"}
    backend.submit.assert_not_called()
    assert Path(result["pipeline"]).is_file()


def test_training_registers_only_after_real_job_success_and_stops_duplicate_writes(tmp_path):
    project = ESMLProject(LakeSettings.from_dict(configuration()))
    rollout = AzureMLRollout(project, tmp_path)
    rollout.prepare(model_number=11, mode="custom", data_date_utc="2026-09-28", run_id="train-1")
    project.execute_pipeline = MagicMock(return_value={"name": "actual-azure-job", "status": "Running"})
    project.wait_for_completion = MagicMock(return_value={"name": "actual-azure-job", "status": "Completed"})
    project.register_outputs = MagicMock(return_value=[{"name": "gold", "id": "azureml:gold:1"}])
    project.register_model = MagicMock(return_value="azureml:diabetes-classification:1")
    receipt = rollout.execute_training("train-1")
    assert receipt["job"] == "actual-azure-job"
    assert receipt["deployment_created"] is False
    project.register_model.assert_called_once()
    with pytest.raises(ValueError, match="completion receipt"):
        rollout.execute_training("train-1")
    project.register_model.assert_called_once()


def test_failed_or_uncertain_runs_cannot_duplicate_registration(tmp_path):
    project = ESMLProject(LakeSettings.from_dict(configuration()))
    rollout = AzureMLRollout(project, tmp_path)
    rollout.prepare(model_number=11, mode="custom", data_date_utc="2026-09-28", run_id="failed-1")
    project.execute_pipeline = MagicMock(return_value={"name": "real-job", "status": "Running"})
    project.wait_for_completion = MagicMock(side_effect=RuntimeError("Job Failed"))
    project.register_outputs = MagicMock()
    project.register_model = MagicMock()
    with pytest.raises(RuntimeError, match="Failed"):
        rollout.execute_training("failed-1")
    project.register_outputs.assert_not_called()
    project.register_model.assert_not_called()
    write_json(tmp_path / "failed-1" / "model-registration-intent.json", {"status": "uncertain"})
    with pytest.raises(ValueError, match="reconcile"):
        rollout.execute_training("failed-1")


@pytest.mark.parametrize("mode", ["custom", "automl"])
def test_inference_deployment_is_not_implicit_in_training(tmp_path, mode):
    project = ESMLProject(LakeSettings.from_dict(configuration()))
    rollout = AzureMLRollout(project, tmp_path)
    original_mode = project.settings.model(11).options.get("inference_mode")
    rollout.prepare(model_number=11, mode=mode, data_date_utc="2026-09-28", run_id="trained")
    write_json(tmp_path / "trained" / "training-completion.json", {"model_id": "azureml:diabetes-classification:7"})
    planned = rollout.prepare_inference("trained", inference_date_utc="2026-09-28", inference_run_id="infer-1")
    assert planned["published"] is False
    assert "/models/7/runs/infer-1/gold/" in planned["input"]
    assert "/models/7/runs/infer-1/out/" in planned["output"]
    inference = load_json(tmp_path / "trained" / "inference" / "code" / "configs" / "inference.json")
    assert inference["mode"] == mode
    assert project.settings.model(11).options.get("inference_mode") == original_mode
