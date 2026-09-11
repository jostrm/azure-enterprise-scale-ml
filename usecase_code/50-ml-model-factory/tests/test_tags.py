"""Real metadata and v2 loader tests; registry/service writes are explicitly simulated."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mlflow.pyfunc
import pandas as pd
import pytest
import yaml
from azure.ai.ml import load_job, load_model

from ml_model_factory import azureml
from ml_model_factory.config import TASKS, load_json, write_json
from ml_model_factory.lake import LakeLayout
from ml_model_factory.lake_flow import train_in_lake, verified_manifest
from ml_model_factory.tags import (
    TAG_KEYS, assert_scope, build_tags, merge_registration_tags, scope_tags, stamp_model,
)


ROOT = Path(__file__).resolve().parents[1]
SCOPE = {"aifactory": "spider-001", "project": "001", "environment_name": "dev"}
RUNTIME = {
    **SCOPE, "subscription_id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
    "resource_group": "rg", "workspace_name": "ml", "compute": "cpu", "gpu_compute": "gpu",
    "input_data": "azureml://datastores/lake/paths/input.csv",
}
SCENARIO = {
    "name": "test-model", "task": "classification", "features": ["x"], "target": "y",
    "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/source", "file": "input.csv", "version": 1},
    "quality": {"min_accuracy": 0.0},
}
LAKE = {
    "aifactory": "spider-001", "project": "001", "environment": "dev",
    "use_case": "test-model", "dataset": "source", "data_version": "v1", "snapshot_id": "s1",
    "run_id": "r1", "model_version": "m1", "storage": {"datastore": "lake"},
}


@pytest.mark.parametrize("task", sorted(TASKS))
@pytest.mark.parametrize("mode", ("custom", "automl"))
def test_v2_jobs_and_model_tags_agree_with_lake_paths(task, mode, tmp_path):
    scenario = {**deepcopy(SCENARIO), "task": task, "forecast": {
        "time_column": "date", "frequency": "D", "horizon": 3, "series_columns": [],
    }}
    runtime = {**RUNTIME, "lake": deepcopy(LAKE)}
    tags = build_tags(scenario, runtime, mode, "azureml", require_scope=True)
    layout = LakeLayout.from_config(runtime["lake"], scenario)
    assert tags["project"] == layout.project and tags["environment"] == layout.environment
    assert tags["dataset"] == layout.dataset and tags["snapshot_id"] == layout.snapshot_id
    assert tags["run_id"] == layout.run_id and tags["use_case"] == layout.use_case
    assert tags["aifactory"] == "spider-001"
    paths = azureml.render(scenario, runtime, tmp_path / "bundle", ROOT, mode)
    job = load_job(paths["job"])
    assert all(job.tags[key] == value for key, value in tags.items())
    assert load_json(tmp_path / "bundle" / "code" / "model-tags.json") == tags
    if "pipeline" in paths:
        pipeline = load_job(paths["pipeline"])
        assert all(pipeline.tags[key] == value for key, value in tags.items())
        assert "--model-tags model-tags.json" in pipeline.jobs["evaluate"].command
    assert load_json(Path(paths["manifest"]))["model_tags"] == tags
    assert yaml.safe_load(Path(paths["online_endpoint"]).read_text())["tags"] == tags


@pytest.mark.parametrize("context", [
    {}, {"project": "001", "environment_name": "dev"},
    {"aifactory": "spider-001", "environment_name": "dev"},
    {"aifactory": "spider-001", "project": "001", "environment": "azureml:runtime:1"},
])
def test_registration_requires_complete_identity_before_any_cloud_calls(context):
    with patch("ml_model_factory.azureml._client") as client, pytest.raises(ValueError, match="requires explicit"):
        azureml.register("job", {**RUNTIME, **{key: None for key in SCOPE}, **context}, "model")
    client.assert_not_called()


@pytest.mark.parametrize("key,value", [("project", "002"), ("environment", "prod"), ("aifactory", "another")])
def test_conflicting_runtime_and_lake_identity_is_rejected(key, value):
    lake = {**LAKE, key: value}
    with pytest.raises(ValueError, match="Conflicting"):
        build_tags(SCENARIO, {**RUNTIME, "lake": lake})


def test_aml_environment_asset_is_not_deployment_environment():
    tags = build_tags(SCENARIO, {**RUNTIME, "environment": "azureml:training-runtime:3"})
    assert tags["environment"] == "dev"
    assert "training-runtime" not in str(tags)


def test_unknown_fields_and_credentials_do_not_become_tags():
    tags = build_tags(SCENARIO, {**RUNTIME, "password": "do-not-copy", "arbitrary": "ignore"})
    assert "password" not in tags and "arbitrary" not in tags


def test_job_cannot_be_submitted_to_a_different_factory(tmp_path):
    paths = azureml.render(SCENARIO, RUNTIME, tmp_path / "bundle", ROOT)
    with patch("ml_model_factory.azureml._client") as client, pytest.raises(ValueError, match="differs"):
        azureml.submit(Path(paths["pipeline"]), {**RUNTIME, "aifactory": "other-factory"})
    client.assert_not_called()


def service_fixture(tmp_path, tags=None, *, report_tags=None, passed=True):
    tags = tags or build_tags(SCENARIO, RUNTIME, engine="azureml", require_scope=True)
    client = MagicMock()
    client.jobs.get.return_value = SimpleNamespace(
        type="pipeline", status="Completed", jobs={"evaluate": {}}, outputs={"model": {}, "report": {}},
        tags={**tags, "factory_quality_gate": "evaluate", "factory_mode": "custom",
              "factory_task": "classification", "factory_scenario": SCENARIO["name"]},
    )

    def download(**kwargs):
        root = Path(kwargs["download_path"]) / "report"
        write_json(root / "quality-gate.json", {"passed": passed})
        write_json(root / "lineage.json", {
            "model_output": "model", "scenario": SCENARIO["name"], "task": "classification",
            "mode": "custom", "model_tags": tags if report_tags is None else report_tags,
        })

    client.jobs.download.side_effect = download
    client.models.create_or_update.return_value.id = "azureml:tagged:1"
    return client


def test_sdk_registration_copies_identity_and_origin_after_gate(tmp_path):
    client = service_fixture(tmp_path)
    with patch("ml_model_factory.azureml._client", return_value=client):
        result = azureml.register("train-job", RUNTIME, "tagged")
    assert result == "azureml:tagged:1"
    tags = client.models.create_or_update.call_args.args[0].tags
    assert {key: tags[key] for key in ("aifactory", "project", "environment")} == {
        "aifactory": "spider-001", "project": "001", "environment": "dev",
    }
    assert tags["training_environment"] == "dev"
    assert tags["source_run_id"] == "train-job"
    assert tags["source_resource_id"].endswith("/workspaces/ml")
    assert tags["lifecycle_status"] == "candidate"
    assert tags["quality_gate"] == "passed"


@pytest.mark.parametrize("failure", ("scope", "lineage", "gate"))
def test_mismatch_cannot_produce_registry_write(failure, tmp_path):
    tags = build_tags(SCENARIO, RUNTIME, engine="azureml", require_scope=True)
    client = service_fixture(tmp_path, tags, report_tags={**tags, "use_case": "other"} if failure == "lineage" else None,
                             passed=failure != "gate")
    context = {**RUNTIME, "aifactory": "other"} if failure == "scope" else RUNTIME
    with patch("ml_model_factory.azureml._client", return_value=client), pytest.raises(ValueError):
        azureml.register("job", context, "tagged")
    client.models.create_or_update.assert_not_called()


def test_cli_v2_model_definition_matches_sdk_tag_contract(tmp_path):
    spec = importlib.util.spec_from_file_location("tag_cli", ROOT / "scripts" / "azureml_cli.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    runtime = tmp_path / "runtime.json"
    write_json(runtime, RUNTIME)
    client = service_fixture(tmp_path)
    definitions = []

    def create(*arguments):
        assert arguments[:3] == ("ml", "model", "create")
        document = Path(arguments[arguments.index("--file") + 1])
        definitions.append(yaml.safe_load(document.read_text()))
        model = load_model(document)
        assert model.tags["aifactory"] == "spider-001"
        assert arguments[arguments.index("--subscription") + 1] == RUNTIME["subscription_id"]
        return {"id": "azureml:tagged:1"}

    with patch("ml_model_factory.azureml._client", return_value=client), patch("ml_model_factory.project.azure_cli", side_effect=create), patch.object(
        script.sys, "argv", ["azureml_cli.py", "--runtime", str(runtime), "--register-job", "job", "--model-name", "tagged"],
    ):
        script.main()
    assert definitions[0]["tags"]["environment"] == "dev"
    assert definitions[0]["tags"]["quality_gate"] == "passed"
    client.models.create_or_update.assert_not_called()


def test_tagged_local_model_remains_loadable_and_matches_committed_run(tmp_path):
    raw = tmp_path / "input.csv"
    pd.DataFrame({"x": [0.0, 1.0] * 30, "y": [0, 1] * 30}).to_csv(raw, index=False)
    root = tmp_path / "lake"
    output = train_in_lake(SCENARIO, LAKE, raw, root)
    model_path = Path(output["model"])
    manifest = verified_manifest(model_path.parent)
    metadata = yaml.safe_load((model_path / "MLmodel").read_text())["metadata"]["model_factory_tags"]
    assert manifest["model_tags"] == metadata == load_json(model_path / "factory.json")["model_tags"]
    assert metadata["aifactory"] == "spider-001"
    assert metadata["dataset"] == LAKE["dataset"]
    assert mlflow.pyfunc.load_model(str(model_path)).predict(pd.DataFrame({"x": [1.0]})).tolist() == [1]
    with pytest.raises(ValueError, match="already committed"):
        stamp_model(model_path, metadata)


def test_all_sources_reject_cross_factory_scope():
    with pytest.raises(ValueError, match="differs"):
        assert_scope({"aifactory": "yellow", "project": "001", "environment": "dev"}, RUNTIME)


def test_project_discovery_resolves_identity_without_guessing_resource_names(tmp_path):
    from ml_model_factory.project import discover
    variables = tmp_path / "variables.json"
    write_json(variables, {"dev": {
        "enableAzureMachineLearning": "true", "dev_sub_id": RUNTIME["subscription_id"],
        "tenantId": RUNTIME["tenant_id"], "project_number_000": "001",
    }})
    project = tmp_path / "project.json"
    write_json(project, {"variables_file": "variables.json", "environment": "dev",
                         "resource_group": "rg", "aifactory": "spider-001"})
    responses = [
        {"id": RUNTIME["subscription_id"], "tenantId": RUNTIME["tenant_id"]},
        [{"type": "Microsoft.MachineLearningServices/workspaces", "name": "actual-workspace"}],
        [{"type": "amlcompute", "name": "actual-cpu", "size": "Standard_D4s_v5"}],
    ]
    with patch("ml_model_factory.project.azure_cli", side_effect=responses):
        runtime = discover(project)
    assert runtime["aifactory"] == "spider-001"
    assert runtime["project"] == "001" and runtime["environment_name"] == "dev"
    assert runtime["workspace_name"] == "actual-workspace"
    assert runtime["compute"] == "actual-cpu"
    incomplete = load_json(project)
    incomplete.pop("aifactory")
    write_json(project, incomplete)
    with patch("ml_model_factory.project.azure_cli") as cli, pytest.raises(ValueError, match="requires explicit"):
        discover(project)
    cli.assert_not_called()


def test_scoped_model_tags_propagate_to_deployment_from_registered_origin(tmp_path):
    from ml_model_factory.serving import deploy

    paths = azureml.render(SCENARIO, RUNTIME, tmp_path / "bundle", ROOT, "custom")
    registered_tags = {
        **build_tags(SCENARIO, RUNTIME, engine="azureml", require_scope=True),
        "pipeline_job": "original-training", "factory_scenario": SCENARIO["name"],
        "factory_mode": "custom", "quality_gate": "passed", "source_run_id": "original-training",
    }
    client = MagicMock()
    client.models.get.return_value = SimpleNamespace(
        name=SCENARIO["name"], type="mlflow_model", id="azureml:test-model:1", tags=registered_tags,
    )
    with patch("ml_model_factory.azureml._client", return_value=client):
        deploy(RUNTIME, Path(paths["manifest"]).parent, "azureml:test-model:1")
    deployment = client.online_deployments.begin_create_or_update.call_args.args[0]
    assert deployment.tags["source_run_id"] == "original-training"
    assert deployment.tags["aifactory"] == "spider-001"
    with patch("ml_model_factory.azureml._client", return_value=client), pytest.raises(ValueError, match="differs"):
        deploy({**RUNTIME, "project": "002"}, Path(paths["manifest"]).parent, "azureml:test-model:1")


@pytest.mark.parametrize("task", sorted(TASKS))
def test_every_custom_task_publishes_real_model_with_scope_and_lake_tags(task, tmp_path):
    from test_lifecycle_e2e import generated_source, ingest_generated, lake_config

    scenario, raw = generated_source(tmp_path, task)
    selected = ingest_generated(scenario, raw, tmp_path / "download")
    config = lake_config(scenario, aifactory="spider-001")
    result = train_in_lake(scenario, config, selected, tmp_path / "lake")
    path = Path(result["model"])
    committed = verified_manifest(path.parent)
    loaded = mlflow.pyfunc.load_model(str(path))
    tags = loaded.metadata.metadata["model_factory_tags"]
    assert tags == committed["model_tags"] == load_json(path / "factory.json")["model_tags"]
    assert tags["task_type"] == task and tags["training_engine"] == "local"
    for key in ("aifactory", "project", "environment", "use_case", "dataset", "data_version", "snapshot_id", "run_id"):
        assert tags[key] == config[key]
    assert tags["quality_gate"] == "passed" and tags["lifecycle_status"] == "candidate"


def test_custom_cli_training_and_evaluation_keep_azure_engine_and_identity(tmp_path):
    from ml_model_factory.cli import main
    spec = importlib.util.spec_from_file_location("tags_evaluate", ROOT / "scripts" / "azureml_evaluate.py")
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    scenario = tmp_path / "scenario.json"
    tag_file = tmp_path / "model-tags.json"
    write_json(scenario, SCENARIO)
    tags = build_tags(SCENARIO, RUNTIME, engine="azureml", require_scope=True)
    write_json(tag_file, tags)
    raw = tmp_path / "input.csv"
    pd.DataFrame({"x": [0.0, 1.0] * 30, "y": [0, 1] * 30}).to_csv(raw, index=False)
    prepared, model, report = tmp_path / "prepared", tmp_path / "model", tmp_path / "report"
    assert main(["prepare", "--scenario", str(scenario), "--input", str(raw), "--output", str(prepared)]) == 0
    assert main(["train", "--scenario", str(scenario), "--prepared", str(prepared),
                 "--model-output", str(model), "--model-tags", str(tag_file)]) == 0
    assert mlflow.pyfunc.load_model(str(model)).metadata.metadata["model_factory_tags"] == tags
    args = ["azureml_evaluate.py", "--mode", "custom", "--scenario", str(scenario), "--prepared", str(prepared),
            "--model", str(model), "--output", str(report), "--model-tags", str(tag_file)]
    with patch.object(evaluator.sys, "argv", args):
        evaluator.main()
    assert load_json(report / "lineage.json")["model_tags"] == tags
    assert tags["training_engine"] == "azureml"


def test_instantiation_excludes_active_test_artifacts(tmp_path):
    from ml_model_factory.templates import instantiate
    source = tmp_path / "source"
    (source / "ml_model_factory").mkdir(parents=True)
    (source / "pyproject.toml").write_text("[project]")
    for name in (".test-artifacts", ".azureml-test-artifacts", ".orchestration-matrix-artifacts", ".fixture-validation-123"):
        (source / name).mkdir()
        (source / name / "model.bin").write_bytes(b"generated fixture")
    destination = tmp_path / "consumer"
    instantiate(source, destination)
    assert not list(destination.rglob("model.bin"))
