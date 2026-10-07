from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

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


FACTORY = ROOT.parent / "usecase_code" / "50-ml-model-factory"
SCENARIOS = FACTORY / "user-config" / "model" / "scenarios"


def rollout_config(**scenarios):
    config = load_json(FACTORY / "user-config" / "esml-rollout.example.json")
    if scenarios:
        config["scenarios"] = scenarios
    return config


def test_factory_rollout_example_compiles_to_esml_settings_offline():
    from azure_esml.domain_layer.rollout import settings_from_rollout_config

    settings, catalog = settings_from_rollout_config(rollout_config(), SCENARIOS)
    project = ESMLProject(LakeSettings.from_dict(settings))
    model = project.settings.model(SCENARIO_NUMBERS["diabetes"])
    assert model.use_case == "diabetes" and model.alias == "M02"
    assert model.options["inference_mode"] == "automl"
    assert model.options["evaluation_environment"] == settings["models"][0]["evaluation_environment"]
    selected = [row for row in catalog if row["selected"]]
    assert [row["scenario"] for row in selected] == ["diabetes"]
    assert {row["status"] for row in catalog if not row["selected"]} == {"not_selected"}


def test_rollout_bridge_selects_one_reviewed_binding_and_overrides_mode(tmp_path):
    from azure_esml.domain_layer.rollout import project_from_rollout_config

    project = project_from_rollout_config(rollout_config(), SCENARIOS, scenario="diabetes", mode="custom",
                                          base_path=tmp_path)
    model = project.settings.model(SCENARIO_NUMBERS["diabetes"])
    assert "inference_mode" not in model.options and "evaluation_environment" not in model.options
    request = AzureMLRollout(project, tmp_path / "runs").prepare(
        model_number=model.number, mode="custom", data_date_utc="2026-10-06", run_id="bridge-custom-1")
    assert request["cloud_submitted"] is False and Path(request["pipeline"]).is_file()
    with pytest.raises(ValueError, match="reviewed source binding"):
        project_from_rollout_config(rollout_config(), SCENARIOS, scenario="churn", base_path=tmp_path)


@pytest.mark.parametrize("name, message", [
    ("orangejuice", "selection/license gate"), ("image-multiclass", "selection/license gate"),
    ("image-object-detection", "vision"),
])
def test_rollout_bridge_keeps_dataset_and_vision_gates(name, message):
    from azure_esml.domain_layer.rollout import settings_from_rollout_config

    binding = {"mode": "custom", "compute": "cpu-cluster", "data_version": "v1", "run_id": "gate-1",
               "input_path": f"mlops/v1/projects/project001/environments/dev/datasets/{name}/versions/v1/in"}
    with pytest.raises(ValueError, match=message):
        settings_from_rollout_config(rollout_config(**{name: binding}), SCENARIOS)


def test_rollout_bridge_requires_automl_evaluation_environment_for_automl():
    from azure_esml.domain_layer.rollout import settings_from_rollout_config

    config = rollout_config()
    config.pop("automl_evaluation_environment")
    with pytest.raises(ValueError, match="automl_evaluation_environment"):
        settings_from_rollout_config(config, SCENARIOS)


def test_rollout_bridge_forwards_automl_forecast_inference_history(tmp_path):
    from azure_esml.domain_layer.rollout import project_from_rollout_config

    history = "mlops/v1/projects/project001/environments/dev/datasets/air-passengers/versions/v1/history"
    binding = {"mode": "automl", "compute": "cpu-cluster", "data_version": "v1", "run_id": "m05-automl-1",
               "input_path": "mlops/v1/projects/project001/environments/dev/datasets/air-passengers/versions/v1/in",
               "inference_history_path": history}
    project = project_from_rollout_config(rollout_config(**{"air-passengers": binding}), SCENARIOS,
                                          scenario="air-passengers", base_path=tmp_path)
    rollout = AzureMLRollout(project, tmp_path / "runs")
    rollout.prepare(model_number=SCENARIO_NUMBERS["air-passengers"], mode="automl",
                    data_date_utc="2026-10-06", run_id="m05-automl-1", data_version="v1")
    write_json(tmp_path / "runs" / "m05-automl-1" / "training-completion.json",
               {"model_id": "azureml:M05_air_passengers:3"})
    planned = rollout.prepare_inference("m05-automl-1", inference_date_utc="2026-10-06", inference_run_id="i-1")
    document = yaml.safe_load(Path(planned["pipeline"]).read_text(encoding="utf-8"))
    assert document["inputs"]["history"]["path"].endswith(history + "/")


def test_inference_plan_can_be_submitted_once_as_a_pipeline_job(tmp_path):
    project = ESMLProject(LakeSettings.from_dict(configuration()))
    rollout = AzureMLRollout(project, tmp_path)
    rollout.prepare(model_number=11, mode="custom", data_date_utc="2026-09-28", run_id="trained")
    write_json(tmp_path / "trained" / "training-completion.json", {"model_id": "azureml:diabetes-classification:7"})
    rollout.prepare_inference("trained", inference_date_utc="2026-09-28", inference_run_id="infer-2")
    project.execute_pipeline = MagicMock(return_value={"name": "inference-job", "status": "Queued"})
    assert rollout.submit_inference("trained")["name"] == "inference-job"
    assert rollout.submit_inference("trained")["name"] == "inference-job"
    project.execute_pipeline.assert_called_once()
    (tmp_path / "trained" / "inference-pipeline-job.json").unlink()
    with pytest.raises(ValueError, match="reconcile"):
        rollout.submit_inference("trained")
    project.execute_pipeline.assert_called_once()


def test_endpoint_and_pipeline_inference_routes_exclude_each_other(tmp_path):
    project = ESMLProject(LakeSettings.from_dict(configuration()))
    rollout = AzureMLRollout(project, tmp_path)
    rollout.prepare(model_number=11, mode="custom", data_date_utc="2026-09-28", run_id="trained")
    write_json(tmp_path / "trained" / "training-completion.json", {"model_id": "azureml:diabetes-classification:7"})
    rollout.prepare_inference("trained", inference_date_utc="2026-09-28", inference_run_id="infer-3")
    project.execute_pipeline = MagicMock(return_value={"name": "inference-job", "status": "Queued"})
    project.publish_pipeline = MagicMock()
    rollout.submit_inference("trained")
    with pytest.raises(ValueError, match="other route"):
        rollout.deploy_and_invoke("trained", component_version="5")
    project.publish_pipeline.assert_not_called()
    for name in ("inference-pipeline-job.json", "inference-pipeline-intent.json"):
        (tmp_path / "trained" / name).unlink()
    write_json(tmp_path / "trained" / "inference-invocation-intent.json", {"status": "invocation_requested"})
    with pytest.raises(ValueError, match="other route"):
        rollout.submit_inference("trained")
    project.execute_pipeline.assert_called_once()
