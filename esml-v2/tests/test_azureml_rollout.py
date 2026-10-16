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


CONSUMER = "49-telco-churn-agent"


def consumer_scenarios(tmp_path, **overrides):
    folder = tmp_path / "scenarios"
    folder.mkdir(parents=True)
    for path in SCENARIOS.glob("*.json"):
        (folder / path.name).write_bytes(path.read_bytes())
    template = load_json(SCENARIOS / "churn.json")
    scenario = {**template, "name": CONSUMER, "dataset": {
        "provider": "lake", "kind": "dataset", "file": "telco.csv", "version": 1, "status": "configured",
        "license": "synthetic"}, **overrides}
    write_json(folder / f"{CONSUMER}.json", scenario)
    return folder


def consumer_binding():
    return {"mode": "custom", "compute": "cpu-cluster", "data_version": "synth-v1", "run_id": "m49-1",
            "input_path": f"mlops/v1/projects/project001/environments/dev/datasets/{CONSUMER}/versions/synth-v1/in"}


def test_reviewed_consumer_scenarios_get_explicit_model_numbers(tmp_path):
    from azure_esml.domain_layer.rollout import project_from_rollout_config, scenario_number, settings_from_rollout_config

    folder = consumer_scenarios(tmp_path)
    config = {**rollout_config(**{CONSUMER: consumer_binding()}), "model_numbers": {CONSUMER: 49}}
    assert scenario_number(config, "diabetes") == 2 and scenario_number(None, "churn") == 3
    assert scenario_number(config, CONSUMER) == 49
    settings, catalog = settings_from_rollout_config(config, folder)
    model = settings["models"][0]
    assert (model["model_number"], model["model_short_alias"], model["model_name"]) == (
        49, "M49", "M49_49_telco_churn_agent")
    assert model["use_case"] == model["model_folder_name"] == CONSUMER
    assert {row["scenario"]: row["model_alias"] for row in catalog}[CONSUMER] == "M49"
    project = project_from_rollout_config(config, folder, scenario=CONSUMER, base_path=tmp_path)
    request = AzureMLRollout(project, tmp_path / "runs").prepare(
        model_number=49, mode="custom", data_date_utc="2026-10-16", run_id="m49-1", data_version="synth-v1")
    assert request["model_name"] == "M49_49_telco_churn_agent"
    assert request["experiment_name"] == f"M49_{CONSUMER}_IN_2_GOLD_TRAINING_MANUAL"
    assert {item["name"] for item in request["data_assets"]} >= {f"M49_{CONSUMER}_gold_train"}


@pytest.mark.parametrize("numbers, message", [
    ({CONSUMER: 5}, "12 to 999"), ({CONSUMER: 1000}, "12 to 999"), ({CONSUMER: "49"}, "12 to 999"),
    ({"diabetes": 49}, "built-in"), ({CONSUMER: 49, "other-agent": 49}, "assigned twice"),
    ([CONSUMER], "map reviewed"),
])
def test_consumer_model_numbers_are_validated(tmp_path, numbers, message):
    from azure_esml.domain_layer.rollout import scenario_number, settings_from_rollout_config

    folder = consumer_scenarios(tmp_path)
    config = {**rollout_config(**{CONSUMER: consumer_binding()}), "model_numbers": numbers}
    with pytest.raises(ValueError, match=message):
        settings_from_rollout_config(config, folder)
    with pytest.raises(ValueError, match=message):
        scenario_number(config, CONSUMER)


def test_consumer_scenarios_need_their_reviewed_file_and_matching_name(tmp_path):
    from azure_esml.domain_layer.rollout import scenario_number, settings_from_rollout_config

    config = {**rollout_config(**{CONSUMER: consumer_binding()}), "model_numbers": {CONSUMER: 49}}
    with pytest.raises(ValueError, match="scenario file"):
        settings_from_rollout_config(config, SCENARIOS)
    folder = consumer_scenarios(tmp_path, name="another-name")
    with pytest.raises(ValueError, match="name"):
        settings_from_rollout_config(config, folder)
    with pytest.raises(ValueError, match="reviewed model number"):
        scenario_number({}, CONSUMER)
    unbound = rollout_config(**{CONSUMER: consumer_binding()})
    with pytest.raises(ValueError, match="known scenarios"):
        settings_from_rollout_config(unbound, consumer_scenarios(tmp_path / "second"))


def test_interrupted_training_resumes_the_recorded_job_without_resubmitting(tmp_path):
    project = ESMLProject(LakeSettings.from_dict(configuration()))
    rollout = AzureMLRollout(project, tmp_path)
    rollout.prepare(model_number=11, mode="custom", data_date_utc="2026-09-28", run_id="resume-1")
    project.execute_pipeline = MagicMock(return_value={"name": "recorded-job", "status": "Running"})
    project.wait_for_completion = MagicMock(side_effect=TimeoutError("still running"))
    project.register_outputs = MagicMock(return_value=[])
    project.register_model = MagicMock(return_value="azureml:diabetes-classification:3")
    with pytest.raises(TimeoutError):
        rollout.execute_training("resume-1")
    with pytest.raises(ValueError, match="submitted"):
        rollout.prepare(model_number=11, mode="custom", data_date_utc="2026-09-28", run_id="resume-1")
    project.wait_for_completion = MagicMock(return_value={"name": "recorded-job", "status": "Completed"})
    receipt = rollout.execute_training("resume-1")
    assert receipt["job"] == "recorded-job" and receipt["model_id"].endswith(":3")
    project.execute_pipeline.assert_called_once()
    project.wait_for_completion.assert_called_once_with("recorded-job", timeout_seconds=7200, poll_seconds=30)
    project.register_model.assert_called_once()


def test_uncertain_training_submission_is_never_repeated(tmp_path):
    project = ESMLProject(LakeSettings.from_dict(configuration()))
    rollout = AzureMLRollout(project, tmp_path)
    rollout.prepare(model_number=11, mode="custom", data_date_utc="2026-09-28", run_id="uncertain-1")
    project.execute_pipeline = MagicMock(side_effect=ConnectionError("reset after send"))
    with pytest.raises(ConnectionError):
        rollout.execute_training("uncertain-1")
    project.execute_pipeline = MagicMock()
    with pytest.raises(ValueError, match="uncertain"):
        rollout.execute_training("uncertain-1")
    project.execute_pipeline.assert_not_called()


def test_retained_champion_can_be_scored_only_after_a_rejected_candidate(tmp_path):
    project = ESMLProject(LakeSettings.from_dict(configuration()))
    rollout = AzureMLRollout(project, tmp_path)
    request = rollout.prepare(model_number=11, mode="custom", data_date_utc="2026-09-28", run_id="kept-1")
    champion = f"azureml:{request['model_name']}:7"
    with pytest.raises(ValueError, match="rejected"):
        rollout.prepare_inference("kept-1", inference_date_utc="2026-09-28", inference_run_id="i-1",
                                  model_id=champion)
    write_json(tmp_path / "kept-1" / "selection-decision.json", {"decision": "champion_kept"})
    write_json(tmp_path / "kept-1" / "model-registration-intent.json", {"status": "registration_requested"})
    with pytest.raises(ValueError, match="model name"):
        rollout.prepare_inference("kept-1", inference_date_utc="2026-09-28", inference_run_id="i-1",
                                  model_id="azureml:other-model:7")
    planned = rollout.prepare_inference("kept-1", inference_date_utc="2026-09-28", inference_run_id="i-1",
                                        model_id=champion)
    assert planned["model_id"] == champion and planned["model_source"] == "retained_champion"
    assert "/models/7/runs/i-1/gold/" in planned["input"]
    write_json(tmp_path / "kept-1" / "training-completion.json", {"model_id": f"azureml:{request['model_name']}:8"})
    with pytest.raises(ValueError, match="rejected"):
        rollout.prepare_inference("kept-1", inference_date_utc="2026-09-28", inference_run_id="i-2",
                                  model_id=champion)
