from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ml_model_factory import azureml
from ml_model_factory.config import load_json, validate_runtime, write_json
from ml_model_factory.lake import LakeLayout
from ml_model_factory.storage_selection import (
    resolve_location, resolve_storage_selection, selected_profile, validate_job_storage, verify_datastore,
)


ROOT = Path(__file__).resolve().parents[1]


def configured(common=False):
    return {
        **load_json(ROOT / "storage-selection.example.json"),
        "use_common_datalake_storage": common,
        "subscription_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "aifactory": "example", "project": "001", "environment_name": "dev",
        "workspace_name": "workspace", "compute": "cpu", "gpu_compute": "gpu",
        "input_data": "azureml://datastores/ml_model_factory/paths/mlops/v1/input/data.csv",
        "lake": {
            "aifactory": "example", "project": "001", "environment": "dev", "dataset": "customers",
            "data_version": "v1", "snapshot_id": "s1", "run_id": "r1",
            "storage": {"datastore": "ml_model_factory"},
        },
    }


@pytest.mark.parametrize("common", [True, False])
def test_boolean_selects_account_container_datastore_and_preserves_lake_keys(common):
    value = configured(common)
    before = deepcopy(value)
    result = resolve_storage_selection(value)
    expected = result["storage_targets"]["common" if common else "project"]
    assert result["storage"] == expected == result["lake"]["storage"]
    assert result["datastore"] == expected["datastore"]
    assert result["input_data"] == f"azureml://datastores/{expected['datastore']}/paths/mlops/v1/input/data.csv"
    layout = LakeLayout.from_config(result["lake"], {"name": "customers"})
    assert layout.account_url == expected["account_url"] and layout.container == expected["container"]
    assert layout.key("landing") == "mlops/v1/projects/project001/environments/dev/datasets/customers/versions/v1/landing"
    assert value == before
    assert resolve_storage_selection(result) == result
    assert validate_runtime(value)["datastore"] == expected["datastore"]
    result["use_common_datalake_storage"] = not common
    switched = resolve_storage_selection(result)
    assert switched["storage"]["account_name"] != expected["account_name"]


@pytest.mark.parametrize("flag", ["false", "true", 0, 1, None, {}, []])
def test_ambiguous_booleans_are_rejected(flag):
    value = configured()
    value["use_common_datalake_storage"] = flag
    with pytest.raises(ValueError, match="JSON boolean"):
        resolve_storage_selection(value)


def test_omission_preserves_legacy_config_and_missing_target_never_falls_back():
    value = {"storage": {}, "datastore": "legacy"}
    assert resolve_storage_selection(value) == value
    value = configured(True)
    del value["storage_targets"]["common"]
    with pytest.raises(ValueError, match="No common"):
        resolve_storage_selection(value)
    value = configured()
    value["lake"]["use_common_datalake_storage"] = True
    with pytest.raises(ValueError, match="Conflicting"):
        resolve_storage_selection(value)


def test_nested_selector_profiles_are_canonical_and_idempotent():
    value = configured(True)
    value["lake"]["use_common_datalake_storage"] = value.pop("use_common_datalake_storage")
    value["lake"]["storage_targets"] = value.pop("storage_targets")
    result = resolve_storage_selection(value)
    assert resolve_storage_selection(result) == result
    assert selected_profile(result)["datastore"] == "esml_shared_lake"


@pytest.mark.parametrize("field,value", [
    ("account_name", "invalid-name"), ("account_url", "https://other.blob.core.windows.net"),
    ("container", "x?sig=secret"), ("resource_group", "other-rg"), ("datastore", ""),
])
def test_invalid_or_cross_scope_selected_profiles_fail(field, value):
    config = configured(False)
    config["storage_targets"]["project"][field] = value
    with pytest.raises(ValueError):
        resolve_storage_selection(config)


def test_uri_retargeting_is_structured_not_string_replacement():
    value = configured(True)
    assert resolve_location("wasbs://ml-model-factory@exampleprojectdata.blob.core.windows.net/a/data.csv", value) == (
        "wasbs://lake3@examplecommonlake.blob.core.windows.net/a/data.csv")
    assert resolve_location("abfss://ml-model-factory@exampleprojectdata.dfs.core.windows.net/a/", value) == (
        "abfss://lake3@examplecommonlake.dfs.core.windows.net/a/")
    assert resolve_location("data\\sample.csv", value) == "data\\sample.csv"
    for invalid in ("https://otheraccount.blob.core.windows.net/data/a.csv",
                    "https://exampleprojectdata.blob.core.windows.net/wrong-container/a.csv",
                    "azureml:opaque-data:3", "azureml://datastores/unknown/paths/a.csv"):
        with pytest.raises(ValueError):
            resolve_location(invalid, value)
    value["input_path"] = "mlops/v1/source/data.csv"
    value["input_data"] = "azureml:previous-opaque-asset:1"
    assert resolve_storage_selection(value)["input_data"].endswith("/mlops/v1/source/data.csv")


@pytest.mark.parametrize("common", [True, False])
@pytest.mark.parametrize("task", sorted(azureml.TASK_SCHEMAS))
@pytest.mark.parametrize("mode", ["custom", "automl"])
def test_every_model_task_and_mode_renders_the_selected_storage(common, task, mode, tmp_path):
    scenario = {
        "name": "customers", "task": task, "target": "label", "features": ["age"],
        "dataset": {"provider": "kaggle", "kind": "dataset", "file": "data.csv"},
        "forecast": {"time_column": "date", "series_columns": [], "frequency": "D", "horizon": 3},
    }
    runtime = configured(common)
    result = azureml.render(scenario, runtime, tmp_path / "render", ROOT, mode)
    selected = selected_profile(runtime)
    rendered_runtime = load_json(Path(result["runtime"]))
    assert rendered_runtime["use_common_datalake_storage"] is common
    assert rendered_runtime["datastore"] == selected["datastore"]
    assert rendered_runtime["lake"]["storage"]["account_url"] == selected["account_url"]
    assert selected["datastore"] in yaml.safe_load(Path(result["prepare_job"]).read_text())["inputs"]["raw"]["path"] if "prepare_job" in result else True
    if "pipeline" in result:
        pipeline = yaml.safe_load(Path(result["pipeline"]).read_text())
        assert pipeline["settings"]["default_datastore"] == "azureml:" + selected["datastore"]
        assert all(selected["datastore"] in value["path"] for value in pipeline["outputs"].values())
        validate_job_storage(pipeline, runtime)


def test_submit_refuses_stale_job_and_wrong_actual_datastore(tmp_path):
    scenario = {"name": "customers", "task": "classification", "target": "y", "features": ["x"],
                "dataset": {"provider": "kaggle", "kind": "dataset"}}
    bundle = azureml.render(scenario, configured(False), tmp_path / "bundle", ROOT, "custom")
    with patch("ml_model_factory.azureml._client") as create, pytest.raises(ValueError, match="render again|Render"):
        azureml.submit(Path(bundle["pipeline"]), configured(True))
    create.assert_not_called()
    storage = selected_profile(configured(True))
    verify_datastore(storage, {"type": "azure_blob", "account_name": storage["account_name"], "container_name": storage["container"]})
    with pytest.raises(ValueError, match="does not bind"):
        verify_datastore(storage, SimpleNamespace(type="azure_blob", account_name="wrong", container_name="lake3"))


@pytest.mark.parametrize("uri", [
    "azureml:unresolved_data:1",
    "wasb://ml-model-factory@exampleprojectdata.blob.core.windows.net/a.csv",
    "abfs://ml-model-factory@exampleprojectdata.dfs.core.windows.net/a.csv",
    "azureml://subscriptions/00000000-0000-0000-0000-000000000001/resourcegroups/rg/workspaces/ws/datastores/wrong/paths/a.csv",
])
def test_submission_rejects_data_asset_or_qualified_datastore_bypasses(uri):
    with pytest.raises(ValueError):
        validate_job_storage({"inputs": {"raw": {"type": "uri_file", "path": uri}}}, configured(True))
    with pytest.raises(ValueError):
        validate_job_storage({"inputs": {"raw": uri}}, configured(True))
    validate_job_storage({"inputs": {"model": {"type": "mlflow_model", "path": "azureml:model:1"}}}, configured(True))


def test_discovery_verifies_account_in_selected_rg_and_exact_datastore(tmp_path):
    from ml_model_factory.project import discover
    config = configured(True)
    project = {key: value for key, value in config.items() if key not in (
        "tenant_id", "subscription_id", "project", "environment_name", "workspace_name", "compute", "gpu_compute")}
    project.update(variables_file="variables.json", environment="dev")
    write_json(tmp_path / "project.json", project)
    write_json(tmp_path / "variables.json", {"dev": {
        "enableAzureMachineLearning": "true", "tenantId": config["tenant_id"],
        "dev_sub_id": config["subscription_id"], "project_number_000": "001",
    }})
    replies = [
        {"id": config["subscription_id"], "tenantId": config["tenant_id"]},
        [{"name": "workspace", "type": "Microsoft.MachineLearningServices/workspaces"}],
        [{"name": "cpu", "type": "amlcompute", "size": "Standard_DS3_v2"}],
        [{"name": "examplecommonlake", "type": "Microsoft.Storage/storageAccounts"},
         {"name": "mrvellegacy", "type": "Microsoft.Storage/storageAccounts"}],
        [{"name": "esml_shared_lake", "type": "azure_blob",
          "account_name": "examplecommonlake", "container_name": "lake3"}],
    ]
    with patch("ml_model_factory.project.azure_cli", side_effect=replies) as cli:
        result = discover(tmp_path / "project.json")
    assert result["datastore"] == "esml_shared_lake"
    assert cli.call_args_list[3].args[-1] == "example-common-dev"
    replies[3] = [{"name": "mrvellegacy", "type": "Microsoft.Storage/storageAccounts"}]
    with patch("ml_model_factory.project.azure_cli", side_effect=replies), pytest.raises(ValueError, match="Select exactly"):
        discover(tmp_path / "project.json")


def test_monitoring_reads_and_publishes_to_the_same_selected_lake(tmp_path):
    from scripts.monitoring_job import render, create_schedule
    runtime = configured(True)
    runtime["lake"]["model_version"] = "7"
    scenario = {"name": "customers", "task": "classification", "target": "y", "features": ["x"],
                "dataset": {"provider": "kaggle", "kind": "dataset"}}
    prefix = "azureml://datastores/ml_model_factory/paths/monitoring/"
    paths = render(runtime, scenario, tmp_path / "schedule", config_uri=prefix + "config.json",
                   reference_uri=prefix + "reference.parquet", current_uri=prefix + "current.parquet", publish=True)
    job = yaml.safe_load(Path(paths["job"]).read_text())
    assert all("esml_shared_lake" in job["inputs"][name]["path"] for name in ("config", "reference", "current"))
    context = load_json(Path(paths["job"]).parent / "context.json")
    assert context["lake"]["storage"]["container"] == "lake3"
    with patch("ml_model_factory.azureml._client") as client, pytest.raises(ValueError, match="render|storage"):
        create_schedule(Path(paths["schedule"]), configured(False), execute=True)
    client.assert_not_called()
    client = MagicMock()
    client.datastores.get.return_value = SimpleNamespace(type="azure_blob", account_name="wrong", container_name="lake3")
    with patch("ml_model_factory.azureml._client", return_value=client), pytest.raises(ValueError, match="does not bind"):
        create_schedule(Path(paths["schedule"]), runtime, execute=True)
    client.schedules.begin_create_or_update.assert_not_called()


def test_databricks_adapter_and_adf_use_selected_lake_without_new_storage_logic():
    spec = importlib.util.spec_from_file_location("storage_dbx", ROOT / "databricks" / "lake_utils.py")
    dbx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dbx)
    import json
    from ml_model_factory.storage_selection import resolve_storage_selection
    runtime = resolve_storage_selection(configured(True))
    scenario = {"name": "customers", "dataset": {"file": "data.csv"}}
    layout = dbx.load_lake(json.dumps(runtime["lake"]), scenario)
    assert dbx.landing_file(layout, scenario).startswith("wasbs://lake3@examplecommonlake.blob.core.windows.net/")
    path = ROOT.parents[1] / "copy_my_subfolders_to_my_grandparent" / "dataops" / "azure-datafactory" / "prepare_run.py"
    spec = importlib.util.spec_from_file_location("storage_adf", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = {"properties": {"jobType": "Command", "inputs": {"raw": {"jobInputType": "uri_file", "uri": "old"}}}}
    parameters = module.build_parameters(configured(True),
        {"loadMode": "initial", "sourceContainer": "incoming", "sourceFolder": "input", "filePattern": "data.csv"},
        payload, scenario=scenario)
    assert parameters["sinkContainer"] == "lake3"
    assert parameters["lakeParameters"]["storageAccountUrl"] == "https://examplecommonlake.blob.core.windows.net"
    assert "esml_shared_lake" in parameters["jobPayload"]["properties"]["inputs"]["raw"]["uri"]
    payload["properties"]["outputs"] = {"model": {"jobOutputType": "mlflow_model",
        "uri": "azureml://datastores/ml_model_factory/paths/old-model"}}
    with pytest.raises(ValueError, match="render again"):
        module.build_parameters(configured(True),
            {"loadMode": "initial", "sourceContainer": "incoming", "sourceFolder": "input", "filePattern": "data.csv"},
            payload, scenario=scenario)
