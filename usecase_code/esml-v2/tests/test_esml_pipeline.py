"""Offline pipeline documents, lake bindings, and real Azure ML v2 schema checks."""

from copy import deepcopy
from io import StringIO
import base64
import json
from pathlib import Path
import re
import shlex
import shutil
import uuid

import pytest
import yaml

from azure_esml import DictionaryStepMap, LakeSettings, PipelineRequest, PipelineType, StepOverride, StepType
from azure_esml.domain_layer.pipeline import ESMLPipelineFactory
from ml_model_factory.tags import TAG_KEYS


@pytest.fixture
def workspace():
    path = Path(__file__).parent / ".pipeline-runs" / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def settings_document(count=2, *, bronze=False):
    return {
        "aifactory": "factory01", "project_number": 1, "active_model": 1,
        "storage": {"datastore": "lake", "prefix": "mlops/v1"},
        "runtime": {"tenant_id": "11111111-1111-1111-1111-111111111111",
                    "subscription_id": "22222222-2222-2222-2222-222222222222",
                    "resource_group": "rg-test", "workspace_name": "ws-test",
                    "environment_name": "dev", "compute": "cpu", "environment": "azureml:runtime:7"},
        "models": [{"model_number": 1, "model_folder_name": "m01", "model_short_alias": "M01",
                    "dataset_folder_names": [f"ds{index:02}" for index in range(count)],
                    "ml_type": "classification", "label": "target", "features": ["x", "y"],
                    "bronze": bronze, "table_format": "parquet", "aml_table_format": "parquet"}],
    }


def request(**kwargs):
    return PipelineRequest("2026-09-13", "run123", **kwargs)


def dbx_map():
    return DictionaryStepMap({step: StepOverride(f"azureml:bridge_{step.value.lower()}:3", engine="databricks")
                              for step in StepType})


def test_factory_accepts_project_and_inherits_dependencies(workspace):
    from azure_esml import ESMLProject

    document = settings_document(1)
    document["models"][0]["discover_datasets"] = True
    settings = LakeSettings.from_dict(document)
    catalog = Catalog(("ds00", "ds01"))
    mapping = DictionaryStepMap({StepType.IN_2_SILVER: StepOverride("azureml:ingest:1", compute="gpu")})
    project = ESMLProject(settings, folder_catalog=catalog, step_map=mapping)
    via_project = ESMLPipelineFactory(project).create_batch_pipeline(
        PipelineType.IN_2_GOLD, request(), output=workspace / "project")
    via_settings = ESMLPipelineFactory(settings, folder_catalog=catalog, step_map=mapping).create_batch_pipeline(
        PipelineType.IN_2_GOLD, request(), output=workspace / "settings")
    assert via_project.document["experiment_name"] == via_settings.document["experiment_name"]
    assert via_project.document["jobs"]["in2silver_ds01"]["compute"] == "azureml:gpu"
    assert via_project.manifest["datasets"] == ["ds00", "ds01"]
    explicit_map, explicit_catalog = DictionaryStepMap({}), Catalog(("ds00",))
    factory = ESMLPipelineFactory(project, step_map=explicit_map, folder_catalog=explicit_catalog)
    assert factory.step_map is explicit_map and factory.folder_catalog is explicit_catalog


@pytest.mark.parametrize("kind", list(PipelineType))
@pytest.mark.parametrize("count", [1, 2, 4])
@pytest.mark.parametrize("bronze", [False, True])
def test_six_dynamic_pipelines_validate_with_real_sdk(workspace, kind, count, bronze):
    pytest.importorskip("azure.ai.ml")
    settings = LakeSettings.from_dict(settings_document(count, bronze=bronze))
    factory = ESMLPipelineFactory(settings, step_map=dbx_map() if kind == PipelineType.IN_2_GOLD_INFERENCE_DBX else None)
    plan = factory.create_batch_pipeline(kind, request(model_version="9" if kind.is_inference else None),
                                         output=workspace / "bundle")
    document = plan.document
    assert yaml.safe_load(plan.yaml_path.read_text(encoding="utf-8")) == document
    assert json.loads((plan.base_path / "manifest.json").read_text()) == plan.manifest
    assert len(document["inputs"]) == (9 if kind == PipelineType.GOLD_INFERENCE else 7 + count + kind.is_inference)
    assert document["experiment_name"] == f"project001_m01_pipe_{kind.value}"
    assert len(document["jobs"]) == (
        1 if kind == PipelineType.GOLD_INFERENCE else count * (2 if bronze else 1) + 1
        + (3 if kind.is_training else int(kind.is_inference))
    )
    assert len(plan.manifest["datasets"]) == count
    assert document["tags"]["run_id"] == "run123"
    assert all(asset["output"] in document["outputs"] for asset in plan.manifest["data_assets"])
    if kind != PipelineType.GOLD_INFERENCE:
        assert {name for name in document["jobs"]["merge"]["inputs"] if not name.startswith("esml_")} == {
            f"ds{index:02}" for index in range(count)}
    if kind.is_inference:
        assert document["inputs"]["model"]["path"] == "azureml:m01:9"
        assert "/models/9/runs/run123/out/" in document["outputs"]["inference"]["path"]
    else:
        assert document["inputs"]["esml_model_version"] == "none"
        assert "/training/runs/run123/gold/" in document["outputs"]["gold"]["path"]
    if kind.is_training:
        assert document["tags"]["factory_quality_gate"] == "evaluate"
        config = json.loads((plan.base_path / "code" / "configs" / "evaluate.json").read_text())
        assert config["tags"] == {key: value for key, value in document["tags"].items() if key in TAG_KEYS}
        assert document["jobs"]["train"]["type"] == ("automl" if kind == PipelineType.IN_2_GOLD_TRAINING_AUTOML else "command")
    for job in document["jobs"].values():
        assert "is_deterministic" not in job
        if isinstance(job.get("component"), dict):
            assert job["component"]["is_deterministic"] is True
            for name in document["inputs"]:
                if name.startswith("esml_"):
                    assert job["inputs"][name] == "${{parent.inputs." + name + "}}"
                    assert job["component"]["inputs"][name] == {"type": "string"}
    for definition in document["outputs"].values():
        assert "/runs/run123/" in definition["path"]
        assert "/snapshots/" not in definition["path"]
    validation = plan.to_sdk()._validate()
    assert validation.passed, str(validation)


def test_pipeline_component_and_invocation_validate(workspace):
    ml = pytest.importorskip("azure.ai.ml")
    settings = LakeSettings.from_dict(settings_document())
    for kind in (PipelineType.IN_2_GOLD_TRAINING_MANUAL, PipelineType.IN_2_GOLD_TRAINING_AUTOML,
                 PipelineType.IN_2_GOLD_INFERENCE):
        plan = ESMLPipelineFactory(settings).create_batch_pipeline(
            kind, request(model_version="2" if kind.is_inference else None), output=workspace / kind.value)
        component = plan.as_component("published_pipeline", "5")
        assert not (set(component) & {"settings", "experiment_name", "tags"})
        assert component["inputs"]["esml_run_id"] == {"type": "string", "default": "run123"}
        assert all("path" not in value for value in component["inputs"].values())
        assert all("path" not in value for value in component["outputs"].values())
        loaded = ml.load_component(StringIO(yaml.safe_dump(component)), relative_origin=plan.base_path / "component.yml")
        validation = loaded._validate()
        assert validation.passed, str(validation)
        assert plan.invocation() == {"inputs": plan.document["inputs"], "outputs": plan.document["outputs"]}
        plan.invocation()["outputs"].clear()
        assert plan.document["outputs"]


@pytest.mark.parametrize("task", ["regression", "forecasting"])
def test_native_automl_task_settings_are_reused(workspace, task):
    pytest.importorskip("azure.ai.ml")
    document = settings_document(1)
    document["models"][0].update(ml_type=task, automl={"limits": {"max_trials": 2}})
    if task == "forecasting":
        document["models"][0]["forecast"] = {"time_column": "date", "horizon": 7, "frequency": "D"}
    plan = ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
        PipelineType.IN_2_GOLD_TRAINING_AUTOML, request(), output=workspace / "bundle")
    train = plan.document["jobs"]["train"]
    assert train["type"] == "automl" and train["task"] == task
    assert train["limits"]["max_trials"] == 2
    assert train["training_data"] == "${{parent.jobs.split.outputs.train}}"
    if task == "forecasting":
        assert train["forecasting"]["forecast_horizon"] == 7
    validation = plan.to_sdk()._validate()
    assert validation.passed, str(validation)


def test_reuse_compute_mapping_and_dataset_specific_priority(workspace):
    mapping = DictionaryStepMap({
        StepType.IN_2_SILVER: StepOverride("azureml:standard:1", compute="cpu2"),
        (StepType.IN_2_SILVER, "ds01"): StepOverride("azureml:accelerated:2", compute="gpu"),
    })
    factory = ESMLPipelineFactory(LakeSettings.from_dict(settings_document()), step_map=mapping)
    plan = factory.create_batch_pipeline(PipelineType.IN_2_GOLD, request(allow_reuse=False), output=workspace / "bundle")
    assert plan.document["jobs"]["in2silver_ds00"]["compute"] == "azureml:cpu2"
    assert plan.document["jobs"]["in2silver_ds01"]["compute"] == "azureml:gpu"
    assert plan.document["settings"]["force_rerun"] is True
    assert plan.document["jobs"]["merge"]["component"]["is_deterministic"] is False


def test_sources_are_explicit_and_outputs_are_run_scoped(workspace):
    document = settings_document()
    document["models"][0]["datasets"] = {
        "ds00": {"input_path": "projects/{project_folder}/legacy/{dataset}/{date_folder}/", "format": "csv"}}
    factory = ESMLPipelineFactory(LakeSettings.from_dict(document))
    first = factory.create_batch_pipeline(PipelineType.IN_2_GOLD, request(), output=workspace / "one")
    second = factory.create_batch_pipeline(PipelineType.IN_2_GOLD, PipelineRequest("2026-09-14", "run124"),
                                           output=workspace / "two")
    assert "/projects/project001/legacy/ds00/2026/09/13/" in first.document["inputs"]["raw_ds00"]["path"]
    assert "/datasets/ds01/versions/2026-09-13/landing/" in first.document["inputs"]["raw_ds01"]["path"]
    assert first.document["name"] != second.document["name"]
    assert set(first.manifest["paths"]["outputs"].values()).isdisjoint(second.manifest["paths"]["outputs"].values())
    assert first.manifest["data_assets"][0]["name"] == "M01_ds00_training_SILVER_dev"
    assert all(asset["version"] == "run123" for asset in first.manifest["data_assets"])
    assert (first.base_path / "code" / "ml_model_factory" / "azureml.py").is_file()
    assert (first.base_path / "code" / "azure_esml" / "domain_layer" / "runtime.py").is_file()
    assert not any(path.suffix != ".py" for path in (first.base_path / "code" / "ml_model_factory").rglob("*") if path.is_file())
    with pytest.raises(ValueError, match="empty"):
        factory.create_batch_pipeline(PipelineType.IN_2_GOLD, request(), output=first.base_path)


class Catalog:
    def __init__(self, names):
        self.names, self.calls = names, []

    def list_folders(self, prefix):
        self.calls.append(prefix)
        return self.names


def test_discovery_is_explicit_sorted_and_fail_closed(workspace):
    document = settings_document(1)
    catalog = Catalog(("ds02", "ds00", "ds01"))
    settings = LakeSettings.from_dict(document)
    ESMLPipelineFactory(settings, folder_catalog=catalog).create_batch_pipeline(
        PipelineType.IN_2_GOLD, request(), output=workspace / "configured")
    assert not catalog.calls
    document["models"][0]["discover_datasets"] = True
    settings = LakeSettings.from_dict(document)
    with pytest.raises(ValueError, match="folder_catalog"):
        ESMLPipelineFactory(settings).create_batch_pipeline(PipelineType.IN_2_GOLD, request(), output=workspace / "missing")
    plan = ESMLPipelineFactory(settings, folder_catalog=catalog).create_batch_pipeline(
        PipelineType.IN_2_GOLD, request(), output=workspace / "discovered")
    assert plan.manifest["datasets"] == ["ds00", "ds01", "ds02"]
    assert catalog.calls == ["mlops/v1/projects/project001/environments/dev/datasets"]
    for names in ((), ("ds01",), ("ds00", "../escape"), ("ds00", "ds00")):
        with pytest.raises(ValueError):
            ESMLPipelineFactory(settings, folder_catalog=Catalog(names)).create_batch_pipeline(
                PipelineType.IN_2_GOLD, request(), output=workspace / "invalid")
    assert not (workspace / "invalid").exists()


@pytest.mark.parametrize("names", [["A-b", "a_b"], [f"ds{i}" for i in range(257)]])
def test_dataset_limits_and_normalized_collision(workspace, names):
    document = settings_document()
    document["models"][0]["dataset_folder_names"] = names
    with pytest.raises(ValueError, match="collide|256"):
        ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
            PipelineType.IN_2_GOLD, request(), output=workspace / "invalid")


def test_dataset_names_cannot_replace_request_context(workspace):
    document = settings_document(1)
    document["models"][0]["dataset_folder_names"] = ["esml_run_id"]
    with pytest.raises(ValueError, match="reserved ESML request context"):
        ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
            PipelineType.IN_2_GOLD, request(), output=workspace / "invalid")


def test_plan_identity_includes_compiled_configuration_and_code(workspace):
    document = settings_document(1)
    first = ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
        PipelineType.IN_2_GOLD_INFERENCE, request(model_version="2"), output=workspace / "first")
    document["models"][0]["features"].reverse()
    second = ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
        PipelineType.IN_2_GOLD_INFERENCE, request(model_version="2"), output=workspace / "second")
    assert first.document["name"] == second.document["name"]
    assert first.document["tags"]["esml_config_sha256"] != second.document["tags"]["esml_config_sha256"]
    assert first.document["tags"]["esml_request_sha256"] != second.document["tags"]["esml_request_sha256"]
    assert len(first.document["tags"]["esml_code_sha256"]) == 64


def test_semantic_request_hash_is_independent_of_bundle_directory(workspace):
    factory = ESMLPipelineFactory(LakeSettings.from_dict(settings_document(1)))
    plans = [factory.create_batch_pipeline(PipelineType.IN_2_GOLD, request(), output=workspace / name)
             for name in ("first", "retry")]
    assert plans[0].document == plans[1].document
    assert len(plans[0].document["tags"]["esml_request_sha256"]) == 64


def test_features_and_model_version_are_required_only_when_consumed(workspace):
    document = settings_document()
    document["models"][0]["features"] = []
    factory = ESMLPipelineFactory(LakeSettings.from_dict(document))
    factory.create_batch_pipeline(PipelineType.IN_2_GOLD, request(), output=workspace / "gold")
    with pytest.raises(ValueError, match="features"):
        factory.create_batch_pipeline(PipelineType.IN_2_GOLD_TRAINING_MANUAL, request(), output=workspace / "training")
    with pytest.raises(ValueError, match="model_version"):
        factory.create_batch_pipeline(PipelineType.GOLD_INFERENCE, request(), output=workspace / "inference")


def test_dbx_requires_every_required_step_to_be_a_real_provider(workspace):
    settings = LakeSettings.from_dict(settings_document())
    partial = DictionaryStepMap({StepType.IN_2_SILVER: StepOverride("azureml:bridge:1", engine="databricks")})
    with pytest.raises(ValueError, match="Databricks"):
        ESMLPipelineFactory(settings, step_map=partial).create_batch_pipeline(
            PipelineType.IN_2_GOLD_INFERENCE_DBX, request(model_version="1"), output=workspace / "invalid")
    assert not (workspace / "invalid").exists()


@pytest.mark.parametrize("engine", ["azureml", "databricks"])
def test_override_receives_compiled_context_and_preserves_non_determinism(workspace, engine):
    component = {
        "type": "command", "environment": "azureml:runtime:7", "is_deterministic": False,
        "command": "echo ${{inputs.esml_context_b64}}",
        "inputs": {"data": {"type": "uri_folder"}, "esml_context_b64": {"type": "string"}},
        "outputs": {"output": {"type": "uri_folder"}},
    }
    mapping = DictionaryStepMap({StepType.IN_2_SILVER: StepOverride(component, engine=engine)})
    plan = ESMLPipelineFactory(LakeSettings.from_dict(settings_document(1)), step_map=mapping).create_batch_pipeline(
        PipelineType.IN_2_GOLD, request(), output=workspace / "valid")
    job = plan.document["jobs"]["in2silver_ds00"]
    context = json.loads(base64.b64decode(job["inputs"]["esml_context_b64"]))
    assert context["request"]["run_id"] == "run123"
    assert context["request"]["scope"]["project"] == "001"
    assert context["dataset"]["format"] == "parquet"
    assert job["component"]["is_deterministic"] is False
    assert plan.document["settings"]["force_rerun"] is (engine == "databricks")
    with pytest.raises(ValueError, match="reserved"):
        ESMLPipelineFactory(LakeSettings.from_dict(settings_document(1)), step_map=DictionaryStepMap({
            StepType.IN_2_SILVER: StepOverride(component, inputs={"esml_context_b64": "forged"})
        })).create_batch_pipeline(PipelineType.IN_2_GOLD, request(), output=workspace / "invalid")


@pytest.mark.parametrize("kind", [PipelineType.IN_2_GOLD_INFERENCE_DBX, PipelineType.IN_2_GOLD_TRAINING_AUTOML])
def test_component_builder_receives_discovered_ports_and_per_step_context(workspace, kind):
    class DynamicMap:
        def __init__(self):
            self.calls = {}

        def resolve(self, step, dataset=None):
            raise AssertionError("The dynamic builder takes precedence")

        def create_component(self, step, input_names, output_names, context, *, dataset=None):
            self.calls[(step, dataset)] = (input_names, output_names, context)
            return StepOverride({
                "type": "command", "environment": "azureml:runtime:7",
                "command": "echo ${{inputs.esml_context_b64}}",
                "inputs": {**{name: {"type": value} for name, value in input_names.items()},
                           "esml_context_b64": {"type": "string"}},
                "outputs": {name: {"type": value} for name, value in output_names.items()},
            }, engine="databricks")

    document = settings_document(0)
    document["models"][0]["discover_datasets"] = True
    mapping = DynamicMap()
    plan = ESMLPipelineFactory(LakeSettings.from_dict(document), step_map=mapping,
                               folder_catalog=Catalog(("Customer-A", "Customer-B"))).create_batch_pipeline(
                                   kind, request(model_version="2" if kind.is_inference else None), output=workspace / "bundle")
    merge = mapping.calls[(StepType.SILVER_MERGED_2_GOLD, None)]
    assert merge[0] == {"customer_a": "uri_folder", "customer_b": "uri_folder"}
    assert merge[2]["merge"] == {"mode": "concat"}
    assert merge[2]["input_labels"] == {"customer_a": "Customer-A", "customer_b": "Customer-B"}
    assert merge[2]["step"] == StepType.SILVER_MERGED_2_GOLD.value
    assert mapping.calls[(StepType.IN_2_SILVER, "Customer-A")][2]["dataset"]["format"] == "parquet"
    if kind.is_training:
        train = mapping.calls[(StepType.TRAINING_AUTOML, None)]
        assert train[:2] == ({"train": "mltable", "validation": "mltable"}, {"best_model": "mlflow_model"})
        assert plan.document["jobs"]["train"]["type"] == "command"
    assert plan.document["settings"]["force_rerun"] is True


def test_inline_override_ports_extra_parameters_and_determinism(workspace):
    component = {"type": "command", "environment": "azureml:runtime:7", "command": "echo ${{inputs.threshold}}",
                 "inputs": {"data": {"type": "uri_folder"}, "threshold": {"type": "number"}},
                 "outputs": {"output": {"type": "uri_folder"}}, "is_deterministic": True}
    settings = LakeSettings.from_dict(settings_document(1))
    mapping = DictionaryStepMap({StepType.IN_2_SILVER: StepOverride(component, inputs={"threshold": 0.4})})
    plan = ESMLPipelineFactory(settings, step_map=mapping).create_batch_pipeline(
        PipelineType.IN_2_GOLD, request(allow_reuse=False), output=workspace / "valid")
    assert plan.document["jobs"]["in2silver_ds00"]["inputs"]["threshold"] == 0.4
    assert plan.document["jobs"]["in2silver_ds00"]["component"]["is_deterministic"] is False
    assert component["is_deterministic"] is True
    for replacement in (StepOverride(component, inputs={"data": "evil"}),
                        StepOverride({**deepcopy(component), "outputs": {"wrong": {"type": "uri_folder"}}})):
        with pytest.raises(ValueError, match="ports|immutable"):
            ESMLPipelineFactory(settings, step_map=DictionaryStepMap({StepType.IN_2_SILVER: replacement})).create_batch_pipeline(
                PipelineType.IN_2_GOLD, request(), output=workspace / "invalid")
    with pytest.raises(ValueError, match="pin|immutable"):
        ESMLPipelineFactory(settings, step_map=DictionaryStepMap({
            StepType.IN_2_SILVER: StepOverride("azureml:component:latest")})).create_batch_pipeline(
                PipelineType.IN_2_GOLD, request(), output=workspace / "invalid")


@pytest.mark.parametrize("merge", [{"mode": "join"}, {"mode": "join", "on": []},
                                 {"mode": "join", "on": ["id"], "how": "cross"},
                                 {"mode": "join", "on": ["id"], "how": "left"},
                                 {"mode": "join", "on": ["id", "id"], "validate": "one_to_one"},
                                 {"mode": "invented"}, {"mode": "concat", "mystery": True}])
def test_merge_configuration_rejects_unimplemented_semantics(workspace, merge):
    document = settings_document()
    document["models"][0]["merge"] = merge
    with pytest.raises(ValueError, match="merge|Join"):
        ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
            PipelineType.IN_2_GOLD, request(), output=workspace / "invalid")


def test_join_preserves_explicit_cardinality_validation(workspace):
    document = settings_document()
    document["models"][0]["merge"] = {"mode": "join", "on": ["id"], "how": "left", "validate": "many_to_one"}
    plan = ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
        PipelineType.IN_2_GOLD, request(), output=workspace / "bundle")
    config = json.loads((plan.base_path / "code" / "configs" / "merge.json").read_text())
    assert config["merge"] == document["models"][0]["merge"]


@pytest.mark.parametrize("kind", [PipelineType.GOLD_INFERENCE, PipelineType.IN_2_GOLD_INFERENCE])
def test_automl_forecasting_has_explicit_observed_history_input(workspace, kind):
    pytest.importorskip("azure.ai.ml")
    document = settings_document(1)
    document["models"][0].update(
        ml_type="forecasting", forecast={"time_column": "date", "horizon": 7},
        inference_mode="automl")
    with pytest.raises(ValueError, match="inference_history_path"):
        ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
            kind, request(model_version="2"), output=workspace / "missing")
    document["models"][0]["inference_history_path"] = (
        "mlops/v1/projects/{project_folder}/observed/{data_version}/history")
    plan = ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
        kind, request(model_version="2"), output=workspace / "bundle")
    assert plan.document["inputs"]["history"]["path"].endswith("/project001/observed/2026-09-13/history/")
    job = plan.document["jobs"]["inference"]
    assert job["inputs"]["history"] == "${{parent.inputs.history}}"
    assert '--input history "${{inputs.history}}"' in job["component"]["command"]
    assert json.loads((plan.base_path / "code" / "configs" / "inference.json").read_text())["mode"] == "automl"
    assert plan.to_sdk()._validate().passed


def test_generated_commands_match_runtime_cli(workspace, monkeypatch):
    from azure_esml.domain_layer import runtime
    calls = []
    monkeypatch.setattr(runtime, "run_operation", lambda *args, **kwargs: calls.append((args, kwargs)))
    settings = LakeSettings.from_dict(settings_document())
    for kind in (PipelineType.IN_2_GOLD_TRAINING_MANUAL, PipelineType.IN_2_GOLD_INFERENCE):
        plan = ESMLPipelineFactory(settings).create_batch_pipeline(
            kind, request(model_version="2" if kind.is_inference else None), output=workspace / kind.value)
        with monkeypatch.context() as patch:
            patch.chdir(plan.base_path / "code")
            for job in plan.document["jobs"].values():
                command = job["component"]["command"]
                command = re.sub(r"\$\{\{(?:inputs|outputs)\.([a-z0-9_]+)\}\}",
                                 lambda match: plan.document["inputs"][match[1]]
                                 if match[1].startswith("esml_") else "./bound_" + match[1], command)
                runtime.main(shlex.split(command)[3:])
    operations = {args[0]: (args, kwargs) for args, kwargs in calls}
    assert operations["training_manual"][1]["prepared"] == Path("bound_prepared")
    assert operations["training_manual"][0][2] == Path("bound_model")
    assert operations["evaluate"][1]["model"] == Path("bound_model")
    assert operations["inference"][1]["model"] == Path("bound_model")
    assert operations["split"][0][2] == Path("bound_prepared")
    assert operations["split"][1]["train"] == Path("bound_train")


def test_generated_csv_bronze_pipeline_executes_through_split(workspace, monkeypatch):
    import pandas as pd
    from azure_esml.domain_layer import runtime

    document = settings_document(1, bronze=True)
    document["models"][0]["input_format"] = "csv"
    plan = ESMLPipelineFactory(LakeSettings.from_dict(document)).create_batch_pipeline(
        PipelineType.IN_2_GOLD_TRAINING_MANUAL, request(), output=workspace / "bundle")
    raw = workspace / "raw"
    raw.mkdir()
    records = pd.DataFrame({"x": range(100), "y": range(100), "target": [0, 1] * 50})
    records.to_csv(raw / "records.csv", index=False)
    parent = {"inputs.raw_ds00": raw, **{"inputs." + name: value for name, value in plan.document["inputs"].items()
                                       if name.startswith("esml_")}}
    for name in plan.document["outputs"]:
        parent["outputs." + name] = workspace / ("result_" + name)
    with monkeypatch.context() as patch:
        patch.chdir(plan.base_path / "code")
        for key, job in plan.document["jobs"].items():
            if key == "train":
                break
            bindings = {}
            for direction in ("inputs", "outputs"):
                for port, reference in job[direction].items():
                    bindings[f"{direction}.{port}"] = parent[reference[len("${{parent."):-2]]
            command = re.sub(r"\$\{\{((?:inputs|outputs)\.[a-z0-9_]+)\}\}",
                             lambda match: str(bindings[match[1]]), job["component"]["command"])
            runtime.main(shlex.split(command)[3:])
            for port in job["outputs"]:
                parent[f"jobs.{key}.outputs.{port}"] = bindings[f"outputs.{port}"]
    pd.testing.assert_frame_equal(pd.read_parquet(parent["outputs.gold"] / "data.parquet"), records)
    assert (parent["outputs.prepared"] / "manifest.json").is_file()
    assert all((parent["outputs." + split] / "MLTable").is_file() for split in ("train", "validation", "test"))
