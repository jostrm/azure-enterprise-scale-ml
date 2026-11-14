from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from azure_esml import ESMLProject, LakeSettings, PipelineRequest, PipelineType
from azure_esml.domain_layer.naming import ESMLNaming
from ml_model_factory.config import load_json, validate_scenario, write_json
from ml_model_factory.tags import build_tags


ROOT = Path(__file__).resolve().parents[1]


def document():
    return load_json(ROOT / "examples" / "app_layer" / "lake_settings.json")


def settings():
    return LakeSettings.from_dict(document())


def backend_for(config):
    backend = MagicMock()
    backend.target = ESMLProject(config).target
    return backend


def test_load_and_named_model_selection_preserve_mapping_and_no_side_effects():
    config = settings()
    assert config.project == "001"
    assert config.model().alias == "M11"
    assert tuple(item.name for item in config.model().datasets) == ("ds01_diabetes", "ds02_diabetes")
    project = ESMLProject(config)
    assert project.target.workspace_name == "example-ml-dev"
    with pytest.raises(ValueError, match="Inject"):
        project.connect_datastore()
    with pytest.raises(ValueError, match="not configured"):
        config.model(999)
    naming = ESMLNaming(config, config.model())
    assert naming.experiment(PipelineType.IN_2_GOLD_INFERENCE) == "project001_11_diabetes_classification_pipe_IN_2_GOLD_INFERENCE"
    assert naming.data("silver", dataset="ds01_diabetes", inference=True) == "M11_ds01_diabetes_inference_SILVER_dev"
    assert len(naming.endpoint(PipelineType.IN_2_GOLD_INFERENCE)) <= 32


@pytest.mark.parametrize("changes", [
    {"project_number": True}, {"project_number": 0}, {"project_number": 1000},
    {"project_folder_name": "project999"}, {"active_model": 2}, {"models": []}, {"aifactory": "../other"},
    {"storage": {}}, {"runtime": {}}, {"schema": "legacy/v1"},
])
def test_invalid_configuration(changes):
    value = document()
    value.update(changes)
    if changes == {"storage": {}}:
        value.pop("use_common_datalake_storage", None)
        value.pop("storage_targets", None)
    with pytest.raises(ValueError):
        LakeSettings.from_dict(value)


@pytest.mark.parametrize("field,value", [
    ("dataset_folder_names", ["one", "one"]), ("dataset_folder_names", ["../escape"]),
    ("discover_datasets", "true"), ("bronze", 1), ("features", ["Outcome"]),
    ("ml_type", "forecast"), ("model_number", True), ("model_short_alias", ""),
])
def test_invalid_model_settings(field, value):
    config = document()
    config["models"][0][field] = value
    with pytest.raises(ValueError):
        LakeSettings.from_dict(config)


def test_legacy_mapping_migration_is_explicit_and_generic_sources_not_fake_kaggle():
    old = {
        "project_number": 2, "project_folder_name": "project002", "active_model": 11,
        "models": [{"model_number": 11, "model_folder_name": "11_diabetes_model_reg", "model_short_alias": "M11",
                    "dataset_folder_names": ["ds01_diabetes", "ds02_other"], "label": "Y", "ml_type": "regression"}],
    }
    with pytest.raises(ValueError):
        LakeSettings.from_dict(old)
    old.update(aifactory="example-factory", storage=document()["storage"], runtime=document()["runtime"])
    migrated = LakeSettings.from_dict(old)
    scenario = migrated.model().scenario()
    assert scenario["dataset"]["provider"] == "lake"
    scenario["features"] = ["Age"]
    assert validate_scenario(scenario)
    with pytest.raises(ValueError, match="Kaggle ingestion"):
        validate_scenario(scenario, require_dataset=True)


@pytest.mark.parametrize("date", ["2026-09-13", "2026-09-13T08:30:00Z", "2026-09-13T23:00:00+00:00"])
def test_date_normalization_and_historical_request(date):
    request = PipelineRequest(date, "history-001", model_version="7")
    assert request.data_date_utc == "2026-09-13"
    assert request.version == "2026-09-13" and request.snapshot == "history-001"


@pytest.mark.parametrize("kwargs", [
    {"data_date_utc": "yesterday"}, {"data_date_utc": "2026-02-30"}, {"data_date_utc": "2026-09-13T10:00:00"},
    {"data_date_utc": "2026-09-13T10:00:00+02:00"}, {"run_id": "../x"}, {"model_version": "latest"},
    {"model_version": "0"}, {"allow_reuse": "false"}, {"data_version": "active"},
])
def test_request_rejects_ambiguous_dates_aliases_and_paths(kwargs):
    with pytest.raises(ValueError):
        PipelineRequest(**{"data_date_utc": "2026-09-13", "run_id": "run-1", **kwargs})


def test_project_configuration_is_copied_and_backend_scope_is_bound():
    config = settings()
    backend = backend_for(config)
    project = ESMLProject(config, backend=backend)
    config.runtime["compute"] = "other"
    assert project.settings.runtime["compute"] == "cpu-cluster"
    backend.submit.assert_not_called()
    backend.target = SimpleNamespace(workspace_name="wrong")
    with pytest.raises(ValueError, match="workspace differs"):
        ESMLProject(config, backend=backend)


def test_credentialless_binding_and_scoped_dataset_reads():
    config = settings()
    backend = backend_for(config)
    project = ESMLProject(config, backend=backend)
    project.connect_datastore()
    definition = backend.ensure_datastore.call_args.args[0]
    assert definition == {"name": "esml_lake", "type": "azure_blob",
                          "account_name": "exampleesmlstorage", "container_name": "lake3"}
    backend.get_data.return_value = {"name": "M11_GOLD", "version": "1", "tags": config.scope}
    assert project.get_dataset("M11_GOLD", "1")["version"] == "1"
    backend.get_data.return_value["tags"] = {**config.scope, "environment": "prod"}
    with pytest.raises(ValueError):
        project.get_dataset("M11_GOLD", "1")


def test_wait_uses_actual_status_and_does_not_cancel_on_timeout():
    config = settings()
    backend = backend_for(config)
    project = ESMLProject(config, backend=backend)
    backend.get_job.side_effect = [{"status": status, "tags": config.scope} for status in ("Running", "Completed")]
    assert project.wait_for_completion("job", clock=lambda: 0, sleep=lambda _: None)["status"] == "Completed"
    backend.get_job.side_effect = None
    for status in ("Failed", "Canceled", "NotAStatus", None):
        backend.get_job.return_value = {"status": status, "tags": config.scope}
        with pytest.raises(RuntimeError):
            project.wait_for_completion("job", clock=lambda: 0, sleep=lambda _: None)
    backend.get_job.return_value = {"status": "Running", "tags": config.scope}
    ticks = iter((0, 0, 0, 5))
    with pytest.raises(TimeoutError):
        project.wait_for_completion("job", timeout_seconds=1, clock=lambda: next(ticks), sleep=lambda _: None)


def test_dataset_publication_validates_scope_run_and_actual_output():
    config = settings()
    backend = backend_for(config)
    project = ESMLProject(config, backend=backend)
    asset = {"output": "gold", "name": "M11_training_GOLD_dev", "version": "run-1",
             "type": "uri_folder", "path": "azureml://datastores/esml_lake/paths/mlops/v1/gold/", "tags": config.scope}
    plan = SimpleNamespace(document={"experiment_name": "exp", "tags": {**config.scope, "run_id": "run-1"}},
                           manifest={"data_assets": [asset]})
    job = {"status": "Completed", "experiment_name": "exp", "tags": plan.document["tags"],
           "outputs": {"gold": {"path": asset["path"]}}}
    backend.get_job.return_value = job
    project.register_outputs(plan, "actual-job")
    assert "output" not in backend.register_data.call_args.args[0]
    for field, invalid in (("status", "Running"), ("experiment_name", "other"), ("outputs", {})):
        backend.get_job.return_value = {**job, field: invalid}
        backend.register_data.reset_mock()
        with pytest.raises(ValueError):
            project.register_outputs(plan, "actual-job")
        backend.register_data.assert_not_called()


def test_list_runs_never_returns_other_project_or_environment():
    config = settings()
    backend = backend_for(config)
    backend.list_jobs.return_value = [
        {"name": "own", "tags": config.scope},
        {"name": "other", "tags": {**config.scope, "project": "002"}},
        {"name": "prod", "tags": {**config.scope, "environment": "prod"}},
    ]
    assert [job["name"] for job in ESMLProject(config, backend=backend).list_runs()] == ["own"]


@pytest.mark.parametrize("change", ["code", "config", "document"])
def test_changed_bundle_is_rejected_before_cloud_reads_or_publication(tmp_path, change):
    config = settings()
    backend = backend_for(config)
    project = ESMLProject(config, backend=backend)
    plan = project.create_pipeline(PipelineType.IN_2_GOLD_INFERENCE,
                                   PipelineRequest("2026-09-13", "tamper-test", model_version="7"),
                                   output=tmp_path / "bundle")
    if change == "document":
        plan.document["inputs"]["esml_model_version"] = "8"
    elif change == "config":
        path = next((plan.base_path / "code" / "configs").glob("*.json"))
        path.write_text(path.read_text() + "\n")
    else:
        path = plan.base_path / "code" / "azure_esml" / "domain_layer" / "runtime.py"
        path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="changed after rendering"):
        project.execute_pipeline(plan)
    with pytest.raises(ValueError, match="changed after rendering"):
        project.publish_pipeline(plan, version="1")
    backend.get_job.assert_not_called()
    backend.publish.assert_not_called()


def test_model_registration_reuses_gate_through_injected_backend(tmp_path):
    config = settings()
    backend = backend_for(config)
    project = ESMLProject(config, backend=backend)
    scenario = config.model().scenario()
    tags = build_tags(scenario, config.scope, mode="custom", engine="azureml", require_scope=True)
    backend.get_job.return_value = {
        "type": "pipeline", "status": "Completed", "jobs": {"evaluate": {}},
        "outputs": {"model": {}, "report": {}},
        "tags": {**tags, "factory_quality_gate": "evaluate", "factory_scenario": scenario["name"],
                 "factory_task": scenario["task"], "factory_mode": "custom"},
    }

    def download(name, destination, output_name):
        assert name == "trained-job" and output_name == "report"
        write_json(destination / "quality-gate.json", {"passed": True})
        write_json(destination / "lineage.json", {
            "model_output": "model", "scenario": scenario["name"], "task": scenario["task"],
            "mode": "custom", "model_tags": tags,
        })

    backend.download_job.side_effect = download
    backend.register_model.return_value = {"id": "azureml:diabetes-classification:4"}
    assert project.register_model("trained-job") == "azureml:diabetes-classification:4"
    definition = backend.register_model.call_args.args[0]
    assert definition["tags"]["lifecycle_status"] == "candidate"
    assert definition["path"] == "azureml://jobs/trained-job/outputs/model/paths/"
    wrong_tags = {**tags, "use_case": "other"}
    backend.get_job.return_value["tags"].update(use_case="other", factory_scenario="other")
    def wrong_model_download(name, destination, output_name):
        download(name, destination, output_name)
        write_json(destination / "lineage.json", {
            "model_output": "model", "scenario": "other", "task": scenario["task"],
            "mode": "custom", "model_tags": wrong_tags,
        })
    backend.download_job.side_effect = wrong_model_download
    backend.register_model.reset_mock()
    with pytest.raises(ValueError, match="selected model"):
        project.register_model("trained-job")
    backend.register_model.assert_not_called()
    backend.get_job.return_value["status"] = "Failed"
    backend.register_model.reset_mock()
    with pytest.raises(ValueError, match="successful"):
        project.register_model("trained-job")
    backend.register_model.assert_not_called()
