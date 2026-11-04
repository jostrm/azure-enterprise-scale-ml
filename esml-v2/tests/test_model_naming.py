"""Offline model-prefixed names and isolated per-model pipeline runtimes."""

from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import re
import shutil
import uuid

import pytest
import yaml

from azure_esml import (
    DictionaryStepMap, LakeSettings, PipelineRequest, PipelineType, StepOverride, StepType,
)
from azure_esml.domain_layer.naming import ESMLNaming
from azure_esml.domain_layer.pipeline import ESMLPipelineFactory
from ml_model_factory.selection import canonical_hash


@pytest.fixture
def workspace():
    path = Path(__file__).parent / ".model-naming-runs" / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def document(count=1, style="model-prefix"):
    return {
        "aifactory": "factory01", "project_number": 1, "active_model": 1,
        "storage": {"datastore": "lake", "prefix": "mlops/v1"},
        "runtime": {
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "subscription_id": "22222222-2222-2222-2222-222222222222",
            "resource_group": "rg-test", "workspace_name": "ws-test",
            "environment_name": "dev", "compute": "shared-cpu", "environment": "azureml:runtime:7",
        },
        "models": [{
            "model_number": 1, "model_folder_name": "01_titanic", "model_short_alias": "M01",
            "use_case": "titanic", "model_name": "M01_titanic", "naming_style": style,
            "dataset_folder_names": [f"ds{index:02}" for index in range(count)],
            "ml_type": "classification", "label": "target", "features": ["x", "y"],
        }],
    }


def request(kind):
    return PipelineRequest("2026-09-28", "naming-test", model_version="9" if kind.is_inference else None)


def names(settings):
    return ESMLNaming(settings, settings.model())


@pytest.mark.parametrize("style", [None, "legacy"])
@pytest.mark.parametrize("count", [1, 2])
def test_legacy_names_remain_identical(style, count):
    config = document(count)
    if style is None:
        config["models"][0].pop("naming_style")
    else:
        config["models"][0]["naming_style"] = style
    naming = names(LakeSettings.from_dict(config))
    kind = PipelineType.IN_2_GOLD_TRAINING_AUTOML
    assert naming.experiment(kind) == "project001_01_titanic_pipe_IN_2_GOLD_TRAINING_AUTOML"
    assert naming.component(kind) == "esml_" + naming.experiment(kind)
    assert naming.endpoint(kind).startswith("esml-project001-")
    assert naming.data("bronze", dataset="ds00") == "M01_ds00_training_BRONZE_dev"
    assert naming.data("silver", dataset="ds00", inference=True) == "M01_ds00_inference_SILVER_dev"
    assert naming.data("train") == "M01_training_TRAIN_dev"


@pytest.mark.parametrize("stage,expected", [
    ("bronze", "bronze"), ("SILVER", "silver"), ("gold", "gold"),
    ("train", "gold_train"), ("validation", "gold_validation"), ("test", "gold_test"),
    ("prepared", "gold_prepared"), ("report", "evaluation"),
    ("inference", "predictions"), ("out", "predictions"),
])
def test_model_prefix_stage_names(stage, expected):
    naming = names(LakeSettings.from_dict(document()))
    assert naming.data(stage, dataset="ds00") == f"M01_titanic_{expected}"


def test_inference_names_and_multibranch_assets_do_not_collide():
    naming = names(LakeSettings.from_dict(document(2)))
    assert naming.data("bronze", dataset="ds00") == "M01_titanic_ds00_bronze"
    assert naming.data("silver", dataset="ds01") == "M01_titanic_ds01_silver"
    assert naming.data("gold", inference=True) == "M01_titanic_gold_inference"
    assert naming.data("out", inference=True) == "M01_titanic_predictions"
    assert naming.data("gold_inference", inference=True) == "M01_titanic_gold_inference"
    all_names = [
        naming.data(stage, dataset=dataset, inference=inference)
        for dataset in ("ds00", "ds01")
        for stage in ("bronze", "silver")
        for inference in (False, True)
    ]
    assert len(set(all_names)) == len(all_names)


def test_component_endpoint_and_compute_names_are_bounded_and_distinct():
    config = document()
    config["models"][0].update(model_short_alias="M02", use_case="diabetes")
    naming = names(LakeSettings.from_dict(config))
    kind = PipelineType.IN_2_GOLD_TRAINING_AUTOML
    assert naming.experiment(kind) == "M02_diabetes_IN_2_GOLD_TRAINING_AUTOML"
    assert naming.component(kind) == "m02_diabetes_in_2_gold_training_automl"
    assert naming.endpoint(PipelineType.IN_2_GOLD_INFERENCE) == "m02-diabetes-batch"
    assert naming.compute() == "m02-cpu-dev"
    assert naming.compute("GPU") == "m02-gpu-dev"
    config["models"][0]["use_case"] = "diabetes_" + "a" * 54
    naming = names(LakeSettings.from_dict(config))
    endpoints = [naming.endpoint(kind) for kind in PipelineType]
    assert len(set(endpoints)) == len(PipelineType)
    assert all(re.fullmatch(r"m02-[a-z0-9-]{1,28}", value) for value in endpoints)
    first = naming.compute("large-training-cpu")
    second = naming.compute("large-training-gpu")
    assert first != second
    assert re.fullmatch(r"m02-[a-z0-9-]{1,12}", first)
    assert first == naming.compute("large-training-cpu")
    with pytest.raises(ValueError, match="purpose"):
        naming.compute("../gpu")


@pytest.mark.parametrize("style,alias", [("legacy", "M1"), ("model-prefix", "M01")])
def test_default_alias_remains_legacy_unless_opted_in(style, alias):
    config = document(style=style)
    config["models"][0].pop("model_short_alias")
    assert LakeSettings.from_dict(config).model().alias == alias


@pytest.mark.parametrize("field,value", [
    ("naming_style", "model_prefix"), ("naming_style", None), ("naming_style", {}),
    ("model_short_alias", "M1"), ("model_short_alias", "m01"), ("model_short_alias", "M1000"),
    ("compute", ""), ("compute", None), ("compute", 17), ("compute", "../gpu"),
    ("compute", "azureml:gpu"),
    ("environment", None), ("environment", {}), ("environment", "runtime"),
    ("environment", "azureml:runtime"), ("environment", "azureml:runtime:latest"),
    ("environment", "azureml:runtime:Active"), ("environment", "azureml:runtime@latest"),
])
def test_invalid_model_options_fail_before_rendering(workspace, field, value):
    config = document()
    config["models"][0][field] = value
    output = workspace / "invalid"
    with pytest.raises(ValueError):
        ESMLPipelineFactory(LakeSettings.from_dict(config)).create_batch_pipeline(
            PipelineType.IN_2_GOLD, request(PipelineType.IN_2_GOLD), output=output)
    assert not output.exists()


@pytest.mark.parametrize("kind", list(PipelineType))
@pytest.mark.parametrize("count", [1, 2])
def test_model_prefix_pipeline_and_component_load_in_real_sdk(workspace, kind, count):
    ml = pytest.importorskip("azure.ai.ml")
    config = document(count)
    config["models"][0].update(compute="m01-cpu-dev", environment="azureml:titanic-env:4")
    settings = LakeSettings.from_dict(config)
    mapping = None
    if kind == PipelineType.IN_2_GOLD_INFERENCE_DBX:
        mapping = DictionaryStepMap({
            step: StepOverride(f"azureml:bridge_{step.value.lower()}:3", engine="databricks")
            for step in StepType
        })
    plan = ESMLPipelineFactory(settings, step_map=mapping).create_batch_pipeline(
        kind, request(kind), output=workspace / "bundle")
    assert plan.document["experiment_name"] == f"M01_titanic_{kind.value}"
    assert plan.document["settings"]["default_compute"] == "azureml:m01-cpu-dev"
    assert plan.manifest["compute"] == "m01-cpu-dev"
    assert plan.manifest["environment_asset"] == "azureml:titanic-env:4"
    assert plan.manifest["table_format"] == plan.manifest["aml_table_format"] == "delta"
    assert json.loads((plan.base_path / "manifest.json").read_text()) == plan.manifest
    assert yaml.safe_load(plan.yaml_path.read_text()) == plan.document
    assets = {item["output"]: item["name"] for item in plan.manifest["data_assets"]}
    assert len(set(assets.values())) == len(assets)
    suffix = "_inference" if kind.is_inference else ""
    if kind != PipelineType.GOLD_INFERENCE:
        for index in range(count):
            branch = f"_ds{index:02}" if count > 1 else ""
            for stage in ("bronze", "silver"):
                assert assets[f"{stage}_ds{index:02}"] == f"M01_titanic{branch}_{stage}{suffix}"
        assert assets["gold"] == f"M01_titanic_gold{suffix}"
    if kind.is_training:
        for stage in ("train", "validation", "test", "prepared"):
            assert assets[stage] == f"M01_titanic_gold_{stage}"
        assert assets["report"] == "M01_titanic_evaluation"
    if kind.is_inference:
        assert assets["inference"] == "M01_titanic_predictions"
        assert plan.document["inputs"]["model"]["path"] == "azureml:M01_titanic:9"
    for node in plan.document["jobs"].values():
        assert node["compute"] == "azureml:m01-cpu-dev"
        if isinstance(node.get("component"), dict):
            assert node["component"]["environment"] == "azureml:titanic-env:4"
    unsigned = deepcopy(plan.document)
    digest = unsigned["tags"].pop("esml_request_sha256")
    assert canonical_hash(unsigned) == digest
    unsigned["settings"]["default_compute"] = "azureml:other"
    assert canonical_hash(unsigned) != digest
    validation = plan.to_sdk()._validate()
    assert validation.passed, str(validation)
    component = plan.as_component(names(settings).component(kind), "1")
    validation = ml.load_component(StringIO(yaml.safe_dump(component)), relative_origin=plan.yaml_path)._validate()
    assert validation.passed, str(validation)


@pytest.mark.parametrize("task", ["classification", "regression", "forecasting"])
@pytest.mark.parametrize("kind", [
    PipelineType.IN_2_GOLD_TRAINING_AUTOML, PipelineType.IN_2_GOLD_TRAINING_MANUAL,
])
def test_model_overrides_and_budgets_do_not_bleed(workspace, task, kind):
    pytest.importorskip("azure.ai.ml")
    config = document()
    first = config["models"][0]
    first.update(ml_type=task, compute="m01-cpu-dev", environment="azureml:titanic-env:4",
                 automl={"limits": {"max_trials": 2, "timeout_minutes": 10}})
    if task == "forecasting":
        first["forecast"] = {"time_column": "date", "horizon": 7, "frequency": "D"}
    second = deepcopy(first)
    second.update(model_number=2, model_folder_name="02_diabetes", model_short_alias="M02",
                  use_case="diabetes", model_name="M02_diabetes", compute="m02-cpu-dev",
                  environment="azureml:diabetes-env:5", automl={"limits": {"max_trials": 3}})
    third = deepcopy(second)
    third.update(model_number=3, model_folder_name="03_housing", model_short_alias="M03",
                 use_case="housing", model_name="M03_housing")
    third.pop("compute")
    third.pop("environment")
    config["models"].extend([second, third])
    original = deepcopy(config)
    settings = LakeSettings.from_dict(config)
    factory = ESMLPipelineFactory(settings)
    for number in (1, 2, 3, 1):
        selected = config["models"][number - 1]
        compute = selected.get("compute", config["runtime"]["compute"])
        environment = selected.get("environment", config["runtime"]["environment"])
        plan = factory.create_batch_pipeline(kind, request(kind), model_number=number,
                                             output=workspace / uuid.uuid4().hex)
        assert plan.manifest["model_name"] == selected["model_name"]
        assert plan.manifest["compute"] == compute
        assert plan.manifest["environment_asset"] == environment
        assert plan.document["settings"]["default_compute"] == "azureml:" + compute
        for node in plan.document["jobs"].values():
            assert node["compute"] == "azureml:" + compute
            if isinstance(node.get("component"), dict):
                assert node["component"]["environment"] == environment
        if kind == PipelineType.IN_2_GOLD_TRAINING_AUTOML:
            assert plan.document["jobs"]["train"]["limits"]["max_trials"] == selected["automl"]["limits"]["max_trials"]
        validation = plan.to_sdk()._validate()
        assert validation.passed, str(validation)
    assert config == original
    assert settings.runtime == original["runtime"]
    assert [model.options for model in settings.models] == original["models"]


def test_discovered_branches_receive_unique_names(workspace):
    config = document()
    config["models"][0]["discover_datasets"] = True

    class Catalog:
        def list_folders(self, prefix):
            return ("ds00", "ds01")

    plan = ESMLPipelineFactory(LakeSettings.from_dict(config), folder_catalog=Catalog()).create_batch_pipeline(
        PipelineType.IN_2_GOLD, request(PipelineType.IN_2_GOLD), output=workspace / "bundle")
    assets = {item["name"] for item in plan.manifest["data_assets"]}
    assert {"M01_titanic_ds00_silver", "M01_titanic_ds01_silver"}.issubset(assets)
    assert len(assets) == len(plan.manifest["data_assets"])


def test_style_changes_only_asset_names_not_lake_paths_or_model_name(workspace):
    plans = []
    for style in ("legacy", "model-prefix"):
        config = document(style=style)
        config["models"][0].pop("model_name")
        plans.append(ESMLPipelineFactory(LakeSettings.from_dict(config)).create_batch_pipeline(
            PipelineType.IN_2_GOLD, request(PipelineType.IN_2_GOLD), output=workspace / style))
    assert plans[0].manifest["paths"] == plans[1].manifest["paths"]
    assert plans[0].manifest["model_name"] == plans[1].manifest["model_name"] == "01_titanic"
    assert plans[0].document["outputs"] == plans[1].document["outputs"]


def test_step_compute_override_takes_priority_over_model_runtime(workspace):
    config = document()
    config["models"][0]["compute"] = "m01-cpu-dev"
    mapping = DictionaryStepMap({
        StepType.IN_2_BRONZE: StepOverride("azureml:custom_bronze:1", compute="custom-gpu"),
    })
    plan = ESMLPipelineFactory(LakeSettings.from_dict(config), step_map=mapping).create_batch_pipeline(
        PipelineType.IN_2_GOLD, request(PipelineType.IN_2_GOLD), output=workspace / "bundle")
    assert plan.document["jobs"]["in2bronze_ds00"]["compute"] == "azureml:custom-gpu"
    assert plan.document["jobs"]["merge"]["compute"] == "azureml:m01-cpu-dev"
    assert plan.manifest["compute"] == "m01-cpu-dev"


@pytest.mark.parametrize("task", ["classification", "regression", "forecasting"])
@pytest.mark.parametrize("identity", [
    {"type": "managed"},
    {"type": "managed", "client_id": "33333333-3333-4333-8333-333333333333"},
])
def test_managed_identity_and_command_timeout_load_in_sdk(workspace, task, identity):
    ml = pytest.importorskip("azure.ai.ml")
    from azure.ai.ml.entities import ManagedIdentityConfiguration
    config = document()
    config["runtime"].update(job_identity=identity, command_timeout_seconds=900)
    config["models"][0].update(ml_type=task, automl={"limits": {"timeout_minutes": 12}})
    if task == "forecasting":
        config["models"][0]["forecast"] = {"time_column": "date", "horizon": 7, "frequency": "D"}
    original = deepcopy(config)
    settings = LakeSettings.from_dict(config)
    kind = PipelineType.IN_2_GOLD_TRAINING_AUTOML
    plan = ESMLPipelineFactory(settings).create_batch_pipeline(kind, request(kind), output=workspace / "bundle")
    nodes = list(plan.document["jobs"].values())
    for node in nodes:
        assert node["identity"] == identity
        assert node["identity"] is not settings.runtime["job_identity"]
        if node["type"] == "command":
            assert node["limits"] == {"timeout": 900}
        else:
            assert node["type"] == "automl"
            assert node["limits"]["timeout_minutes"] == 12
            assert "timeout" not in node["limits"]
    assert len({id(node["identity"]) for node in nodes}) == len(nodes)
    loaded = plan.to_sdk()
    validation = loaded._validate()
    assert validation.passed, str(validation)
    for node in loaded.jobs.values():
        assert isinstance(node.identity, ManagedIdentityConfiguration)
        assert node.identity.client_id == identity.get("client_id")
        if node.type == "command":
            assert node.limits.timeout == 900
    component = plan.as_component(names(settings).component(kind), "1")
    validation = ml.load_component(StringIO(yaml.safe_dump(component)), relative_origin=plan.yaml_path)._validate()
    assert validation.passed, str(validation)
    unsigned = deepcopy(plan.document)
    digest = unsigned["tags"].pop("esml_request_sha256")
    assert canonical_hash(unsigned) == digest
    unsigned["jobs"]["train"]["identity"] = {"type": "managed", "client_id": "44444444-4444-4444-8444-444444444444"}
    assert canonical_hash(unsigned) != digest
    assert config == original
    assert settings.runtime == original["runtime"]


@pytest.mark.parametrize("runtime", [
    {}, {"job_identity": {"type": "managed"}}, {"command_timeout_seconds": 1800},
])
def test_job_contract_options_are_independent_and_apply_to_overrides(workspace, runtime):
    config = document()
    config["runtime"].update(runtime)
    mapping = DictionaryStepMap({
        StepType.IN_2_BRONZE: StepOverride("azureml:custom_bronze:1", compute="custom-gpu"),
    })
    kind = PipelineType.IN_2_GOLD_TRAINING_MANUAL
    plan = ESMLPipelineFactory(LakeSettings.from_dict(config), step_map=mapping).create_batch_pipeline(
        kind, request(kind), output=workspace / "bundle")
    for node in plan.document["jobs"].values():
        assert ("identity" in node) == ("job_identity" in runtime)
        assert ("limits" in node) == ("command_timeout_seconds" in runtime)
        if "job_identity" in runtime:
            assert node["identity"] == runtime["job_identity"]
        if "command_timeout_seconds" in runtime:
            assert node["limits"]["timeout"] == runtime["command_timeout_seconds"]


@pytest.mark.parametrize("runtime", [
    {"job_identity": None}, {"job_identity": "managed"}, {"job_identity": {}},
    {"job_identity": {"type": "user_identity"}}, {"job_identity": {"type": "managed", "object_id": "id"}},
    {"job_identity": {"type": "managed", "client_id": None}},
    {"job_identity": {"type": "managed", "client_id": "not-a-uuid"}},
    {"job_identity": {"type": "managed", "client_id": "33333333333343338333333333333333"}},
    {"command_timeout_seconds": None}, {"command_timeout_seconds": True},
    {"command_timeout_seconds": "900"}, {"command_timeout_seconds": 1.5},
    {"command_timeout_seconds": 0}, {"command_timeout_seconds": -1},
])
def test_invalid_job_contract_fails_before_rendering(workspace, runtime):
    config = document()
    config["runtime"].update(runtime)
    output = workspace / "invalid"
    with pytest.raises(ValueError, match="runtime."):
        ESMLPipelineFactory(LakeSettings.from_dict(config)).create_batch_pipeline(
            PipelineType.IN_2_GOLD, request(PipelineType.IN_2_GOLD), output=output)
    assert not output.exists()


@pytest.mark.parametrize("environment", [
    "azureml:automl-runtime:60",
    "azureml://registries/azureml/environments/ai-ml-automl/versions/60",
])
@pytest.mark.parametrize("kind", [
    PipelineType.IN_2_GOLD_TRAINING_AUTOML, PipelineType.IN_2_GOLD_INFERENCE,
])
def test_scoring_environments_are_isolated_from_data_preparation(workspace, environment, kind):
    pytest.importorskip("azure.ai.ml")
    config = document()
    config["models"][0].update(
        environment="azureml:delta-runtime:7", evaluation_environment=environment,
        inference_environment=environment,
    )
    original = deepcopy(config)
    settings = LakeSettings.from_dict(config)
    plan = ESMLPipelineFactory(settings).create_batch_pipeline(kind, request(kind), output=workspace / "bundle")
    scoring_step = "evaluate" if kind.is_training else "inference"
    for name, node in plan.document["jobs"].items():
        if node["type"] == "command":
            expected = environment if name == scoring_step else "azureml:delta-runtime:7"
            assert node["component"]["environment"] == expected
    assert plan.manifest["environment_asset"] == "azureml:delta-runtime:7"
    assert plan.manifest["table_format"] == "delta"
    validation = plan.to_sdk()._validate()
    assert validation.passed, str(validation)
    assert config == original
    assert settings.model().options == original["models"][0]


@pytest.mark.parametrize("key", ["environment", "evaluation_environment", "inference_environment"])
def test_registry_environment_is_supported_for_each_model_environment(key):
    config = document()
    environment = "azureml://registries/azureml/environments/ai-ml-automl/versions/60"
    config["models"][0][key] = environment
    assert LakeSettings.from_dict(config).model().options[key] == environment


@pytest.mark.parametrize("key", ["environment", "evaluation_environment", "inference_environment"])
@pytest.mark.parametrize("environment", [
    None, "azureml:scoring:latest", "azureml:scoring:active",
    "azureml://registries/azureml/environments/ai-ml-automl/labels/latest",
    "azureml://registries/azureml/environments/ai-ml-automl/versions/latest",
    "azureml://registries/azureml/environments/ai-ml-automl/versions/active",
    "azureml://registries/azureml/environments/ai-ml-automl",
])
def test_model_scoring_environments_require_pinned_versions(workspace, key, environment):
    config = document()
    config["models"][0][key] = environment
    output = workspace / "invalid"
    with pytest.raises(ValueError, match="environment"):
        ESMLPipelineFactory(LakeSettings.from_dict(config)).create_batch_pipeline(
            PipelineType.IN_2_GOLD, request(PipelineType.IN_2_GOLD), output=output)
    assert not output.exists()
