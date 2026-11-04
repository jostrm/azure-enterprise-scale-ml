from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from azure_esml import ESMLProject, LakeSettings, PipelineRequest, PipelineType
from ml_model_factory.config import load_json


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("common", [True, False])
@pytest.mark.parametrize("kind", [value for value in PipelineType if value != PipelineType.IN_2_GOLD_INFERENCE_DBX])
def test_esml_uses_same_storage_toggle_for_all_native_pipeline_patterns(tmp_path, common, kind):
    config = load_json(ROOT / "examples" / "app_layer" / "lake_settings.json")
    profiles = {"storage_targets": config["storage_targets"], "resource_group": config["runtime"]["resource_group"],
                "common_resource_group": config["runtime"]["common_resource_group"]}
    config.update(use_common_datalake_storage=common, storage_targets=profiles["storage_targets"])
    config["runtime"]["resource_group"] = profiles["resource_group"]
    config["runtime"]["common_resource_group"] = profiles["common_resource_group"]
    original = deepcopy(config)
    project = ESMLProject(LakeSettings.from_dict(config))
    chosen = profiles["storage_targets"]["common" if common else "project"]
    plan = project.create_pipeline(kind, PipelineRequest("2026-09-18", "choice-001",
                                   model_version="1" if kind.is_inference else None), output=tmp_path / "bundle")
    assert project.settings.storage["account_name"] == chosen["account_name"]
    assert plan.document["settings"]["default_datastore"] == "azureml:" + chosen["datastore"]
    for output in plan.document["outputs"].values():
        assert output["path"].startswith(f"azureml://datastores/{chosen['datastore']}/paths/")
    assert plan.manifest["project"] == "001" and plan.manifest["environment"] == "dev"
    assert config == original


def test_esml_submission_checks_actual_datastore_before_any_job_write(tmp_path):
    config = load_json(ROOT / "examples" / "app_layer" / "lake_settings.json")
    base = ESMLProject(LakeSettings.from_dict(config))
    backend = MagicMock()
    backend.target = base.target
    backend.get_datastore.return_value = {"type": "azure_blob", "account_name": "wrong", "container_name": "lake3"}
    project = ESMLProject(base.settings, backend=backend)
    plan = project.create_pipeline(PipelineType.IN_2_GOLD, PipelineRequest("2026-09-18", "storage-check"),
                                   output=tmp_path / "bundle")
    with pytest.raises(ValueError, match="does not bind"):
        project.execute_pipeline(plan)
    backend.submit.assert_not_called()
    backend.get_job.assert_not_called()


def test_seeded_runtime_drops_stale_input_selector(tmp_path):
    from azure_esml.domain_layer.lake_seed import write_common_runtimes
    from ml_model_factory.storage_selection import resolve_storage_selection
    settings = load_json(ROOT / "examples" / "app_layer" / "lake_settings.json")
    config = {
        "aifactory": settings["aifactory"], "project": "001", "environment": "dev",
        "use_common_datalake_storage": False, "storage_targets": settings["storage_targets"],
        "datasets": [{"scenario": "customers", "file": "data.csv"}],
    }
    runtime = {**settings["runtime"], "aifactory": settings["aifactory"], "project": "001",
               "input_path": "old/scenario/data.csv"}
    seed = {"version": "v1", "samples": [{"scenario": "customers", "dataset": "customers",
                                         "project_in": "mlops/v1/new/customers/in"}]}
    files = write_common_runtimes(config, seed, runtime, tmp_path)
    generated = load_json(Path(files[0]))
    assert "input_path" not in generated
    assert resolve_storage_selection(generated)["input_data"].endswith("/mlops/v1/new/customers/in/data.csv")
