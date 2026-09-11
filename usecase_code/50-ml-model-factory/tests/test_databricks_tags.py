import ast
import copy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock

import mlflow
import pytest
import yaml

from ml_model_factory.lake import LakeLayout
from ml_model_factory.tags import build_tags, stamp_model


NOTEBOOKS = Path(__file__).resolve().parents[1] / "databricks"
SPEC = importlib.util.spec_from_file_location("databricks_model_tags", NOTEBOOKS / "model_tags.py")
model_tags = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_tags)
SCENARIO = {
    "name": "test-case", "task": "classification", "target": "label", "features": ["feature"],
    "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "example/example",
                "version": 1, "file": "train.csv"},
    "quality": {"min_accuracy": 0.0},
}
SCOPE = {"aifactory": "spider-001", "project": "001", "environment_name": "dev"}
LAKE = {
    "aifactory": "spider-001", "project": "001", "environment": "dev", "use_case": "test-case",
    "dataset": "stable-data", "data_version": "1", "snapshot_id": "snapshot-1", "run_id": "lake-run-1",
    "storage": {"account_url": "https://examplestorage.blob.core.windows.net",
                "container": "ml-model-factory"},
}
RUN_ID = "a" * 32
MODEL_URI = f"runs:/{RUN_ID}/model"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("as_file", [False, True])
def test_context_and_raw_lake_keep_factory_scope_and_shared_layout(tmp_path, as_file):
    context = {**SCOPE, "lake": {"dataset": "stable-data"}}
    context_value, lake_value = json.dumps(context), json.dumps(LAKE)
    if as_file:
        write_json(tmp_path / "context.json", context)
        write_json(tmp_path / "lake.json", LAKE)
        context_value, lake_value = str(tmp_path / "context.json"), str(tmp_path / "lake.json")
    merged = model_tags.load_model_context(context_value, lake_value)
    tags = build_tags(SCENARIO, merged, engine="databricks", require_scope=True)
    assert tags["aifactory"] == "spider-001"
    assert tags["project"] == "001"
    assert tags["environment"] == tags["training_environment"] == "dev"
    assert tags["run_id"] == "lake-run-1"
    assert tags["training_engine"] == "databricks"
    assert tags["dataset"] == "stable-data"
    layout = LakeLayout.from_config(merged["lake"], SCENARIO)
    assert layout.key("training_model") == (
        "mlops/v1/projects/project001/environments/dev/usecases/test-case/"
        "training/runs/lake-run-1/model"
    )
    assert context == {**SCOPE, "lake": {"dataset": "stable-data"}}


def test_raw_lake_alone_retains_explicit_aifactory():
    context = model_tags.load_model_context("", json.dumps(LAKE))
    assert build_tags(SCENARIO, context, engine="databricks", require_scope=True)["aifactory"] == "spider-001"


@pytest.mark.parametrize("key,value", [
    ("aifactory", "other-factory"), ("project", "002"), ("environment", "prod"),
    ("dataset", "other-data"), ("data_version", "2"), ("snapshot_id", "snapshot-2"),
    ("run_id", "lake-run-2"), ("use_case", "other-case"),
    ("storage", {"container": "other-container"}),
])
def test_conflicting_model_context_and_raw_lake_are_not_overwritten(key, value):
    with pytest.raises(ValueError, match="Conflicting"):
        model_tags.load_model_context({"lake": {key: value}}, LAKE)


@pytest.mark.parametrize("override", [
    {"aifactory": "other-factory"}, {"project": "002"}, {"environment_name": "prod"},
    {"project_number": "002"}, {"target_environment": "test"},
])
def test_top_level_scope_disagreement_with_raw_lake_is_rejected(override):
    with pytest.raises(ValueError, match="Conflicting"):
        model_tags.load_model_context({**SCOPE, **override}, LAKE)


def test_lake_use_case_must_match_selected_scenario():
    context = model_tags.load_model_context(SCOPE, {**LAKE, "use_case": "other-case"})
    with pytest.raises(ValueError, match="use.case"):
        build_tags(SCENARIO, context, engine="databricks")


@pytest.mark.parametrize("value", [[], "[]", 1, {"lake": []}, {"lake": None}])
def test_context_requires_json_objects(value):
    with pytest.raises(ValueError, match="JSON object"):
        model_tags.load_model_context(value)


def test_empty_exploratory_runs_have_partial_tags_without_invented_scope():
    context = model_tags.load_model_context()
    tags = build_tags(SCENARIO, context, engine="databricks")
    assert context == {}
    assert not {"aifactory", "project", "environment", "training_environment"} & tags.keys()
    assert "unknown" not in tags.values()
    assert tags["training_engine"] == "databricks"
    assert tags["dataset"] == "kaggle:example/example"
    with pytest.raises(ValueError, match="requires explicit"):
        build_tags(SCENARIO, context, engine="databricks", require_scope=True)


def test_lake_storage_names_never_infer_factory_identity():
    lake = {key: value for key, value in LAKE.items() if key != "aifactory"}
    context = model_tags.load_model_context("", lake)
    assert "aifactory" not in build_tags(SCENARIO, context, engine="databricks")
    with pytest.raises(ValueError, match="requires explicit"):
        build_tags(SCENARIO, context, engine="databricks", require_scope=True)


@pytest.fixture
def registration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = {**SCOPE, "lake": copy.deepcopy(LAKE)}
    tags = build_tags(SCENARIO, context, engine="databricks", require_scope=True)
    source = tmp_path / "published"
    model = source / "model"
    model.mkdir(parents=True)
    (model / "MLmodel").write_text(yaml.safe_dump({"flavors": {"python_function": {}}}), encoding="utf-8")
    write_json(model / "factory.json", {"scenario": SCENARIO, "mode": "custom"})
    stamp_model(model, tags)
    write_json(source / "evaluation" / "quality-gate.json", {"passed": True})
    write_json(source / "model-tags.json", tags)
    client = MagicMock(spec=model_tags.MlflowClient)
    client.get_run.return_value = SimpleNamespace(
        info=SimpleNamespace(run_id=RUN_ID, status="FINISHED"),
        data=SimpleNamespace(tags={**tags, "mlflow.user": "service-user"}),
    )

    def download(run_id, name, dst_path):
        assert run_id == RUN_ID
        destination = Path(dst_path).joinpath(*name.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source.joinpath(*name.split("/")), destination)
        return str(destination)

    client.download_artifacts.side_effect = download
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(model_tags, "MlflowClient", constructor)
    register = MagicMock(return_value=SimpleNamespace(name="reviewed-model", version="1"))
    monkeypatch.setattr(mlflow, "register_model", register)
    return SimpleNamespace(
        source=source, tags=tags, context=context, client=client, register=register,
        constructor=constructor, root=tmp_path,
    )


@pytest.mark.parametrize("name", ["new-explicit-model", "catalog.schema.existing-model"])
def test_registers_only_explicit_evaluated_source_as_candidate_version(registration, name):
    fixture = registration
    before = {str(path): path.read_bytes() for path in fixture.source.rglob("*") if path.is_file()}
    result = model_tags.register_evaluated(MODEL_URI, name, SCENARIO, fixture.context)
    assert result.version == "1"
    fixture.register.assert_called_once_with(MODEL_URI, name, tags={
        **fixture.tags, "source_run_id": RUN_ID, "lifecycle_status": "candidate", "quality_gate": "passed",
    })
    assert fixture.tags["run_id"] != RUN_ID
    assert {call.args[1] for call in fixture.client.download_artifacts.call_args_list} == {
        "evaluation/quality-gate.json", "model/MLmodel", "model/factory.json", "model-tags.json",
    }
    assert {call[0] for call in fixture.client.mock_calls} == {"get_run", "download_artifacts"}
    assert before == {str(path): path.read_bytes() for path in fixture.source.rglob("*") if path.is_file()}
    assert not list(fixture.root.glob(".model-registration-*"))


@pytest.mark.parametrize("uri", [
    None, "", "models:/name/1", "models:/name@champion", "runs:/run/model/child",
    f"{MODEL_URI}?sig=secret", f"{MODEL_URI}#fragment", "runs:/../model", "runs:/%2e/model",
    "runs://run/model", "runs:/run/other", r"runs:/run\other/model",
])
def test_registration_rejects_nonimmutable_sources_before_service_calls(registration, uri):
    with pytest.raises(ValueError, match="immutable"):
        model_tags.register_evaluated(uri, "model", SCENARIO, registration.context)
    registration.constructor.assert_not_called()
    registration.register.assert_not_called()


@pytest.mark.parametrize("name", [None, "", " ", " model", "model ", "models:/name", "model@alias", "model\nname"])
def test_registration_requires_explicit_name_without_guessing_registry(registration, name):
    with pytest.raises(ValueError, match="explicit registered model name"):
        model_tags.register_evaluated(MODEL_URI, name, SCENARIO, registration.context)
    registration.constructor.assert_not_called()
    registration.register.assert_not_called()


@pytest.mark.parametrize("context", [{}, {"project": "001"}, {"lake": {**LAKE, "aifactory": None}}])
def test_unscoped_registration_never_contacts_registry(registration, context):
    with pytest.raises(ValueError, match="requires explicit"):
        model_tags.register_evaluated(MODEL_URI, "model", SCENARIO, context)
    registration.constructor.assert_not_called()
    registration.register.assert_not_called()


@pytest.mark.parametrize("status", ["RUNNING", "FAILED", "KILLED", "SCHEDULED"])
def test_registration_requires_finished_run(registration, status):
    registration.client.get_run.return_value.info.status = status
    with pytest.raises(ValueError, match="FINISHED"):
        model_tags.register_evaluated(MODEL_URI, "model", SCENARIO, registration.context)
    registration.client.download_artifacts.assert_not_called()
    registration.register.assert_not_called()


def test_registration_rejects_different_returned_run(registration):
    registration.client.get_run.return_value.info.run_id = "b" * 32
    with pytest.raises(ValueError, match="selected MLflow run"):
        model_tags.register_evaluated(MODEL_URI, "model", SCENARIO, registration.context)
    registration.register.assert_not_called()


@pytest.mark.parametrize("key,value", [
    ("aifactory", "other-factory"), ("project", "002"), ("environment", "test"),
    ("training_environment", "prod"), ("training_engine", "local"), ("training_mode", "automl"),
    ("use_case", "other-case"), ("task_type", "regression"), ("dataset", "other-data"),
    ("data_version", "2"), ("snapshot_id", "snapshot-2"), ("run_id", "other-run"),
    ("tag_schema", "different-schema"), ("aifactory", None),
])
def test_source_run_tags_must_match_complete_scoped_contract(registration, key, value):
    tags = registration.client.get_run.return_value.data.tags
    if value is None:
        tags.pop(key)
    else:
        tags[key] = value
    with pytest.raises(ValueError):
        model_tags.register_evaluated(MODEL_URI, "model", SCENARIO, registration.context)
    registration.client.download_artifacts.assert_not_called()
    registration.register.assert_not_called()


@pytest.mark.parametrize("gate", [{"passed": False}, {"passed": "true"}, {"passed": 1}, {}, []])
def test_registration_requires_explicit_boolean_quality_gate(registration, gate):
    write_json(registration.source / "evaluation" / "quality-gate.json", gate)
    with pytest.raises(ValueError, match="passed evaluation quality gate|expected a JSON object"):
        model_tags.register_evaluated(MODEL_URI, "model", SCENARIO, registration.context)
    registration.register.assert_not_called()
    assert not list(registration.root.glob(".model-registration-*"))


@pytest.mark.parametrize("artifact", ["model/MLmodel", "model/factory.json", "model-tags.json"])
def test_registration_rejects_inconsistent_model_metadata(registration, artifact):
    path = registration.source.joinpath(*artifact.split("/"))
    mismatched = {**registration.tags, "environment": "prod"}
    if artifact.endswith("MLmodel"):
        path.write_text(yaml.safe_dump({"metadata": {"model_factory_tags": mismatched}}), encoding="utf-8")
    elif artifact.endswith("factory.json"):
        write_json(path, {"model_tags": mismatched})
    else:
        write_json(path, mismatched)
    with pytest.raises(ValueError, match="must match the source run"):
        model_tags.register_evaluated(MODEL_URI, "model", SCENARIO, registration.context)
    registration.register.assert_not_called()
    assert not list(registration.root.glob(".model-registration-*"))


@pytest.mark.parametrize("artifact", [
    "evaluation/quality-gate.json", "model/MLmodel", "model/factory.json", "model-tags.json",
])
def test_missing_evidence_never_registers_and_cleans_review_downloads(registration, artifact):
    registration.source.joinpath(*artifact.split("/")).unlink()
    with pytest.raises(FileNotFoundError):
        model_tags.register_evaluated(MODEL_URI, "model", SCENARIO, registration.context)
    registration.register.assert_not_called()
    assert not list(registration.root.glob(".model-registration-*"))


def test_registry_failures_are_not_retried_or_retagged(registration):
    registration.register.side_effect = mlflow.exceptions.MlflowException("Registry permission denied")
    with pytest.raises(mlflow.exceptions.MlflowException, match="permission denied"):
        model_tags.register_evaluated(MODEL_URI, "model", SCENARIO, registration.context)
    registration.register.assert_called_once()
    assert {call[0] for call in registration.client.mock_calls} == {"get_run", "download_artifacts"}
    assert not list(registration.root.glob(".model-registration-*"))


def test_real_local_training_and_evaluation_can_be_registered_with_scoped_tags(registration):
    import pandas as pd
    from ml_model_factory.data import prepare
    from ml_model_factory.evaluation import evaluate
    from ml_model_factory.training import train

    source = registration.root / "input.csv"
    pd.DataFrame({"feature": [0, 1] * 40, "label": [0, 1] * 40}).to_csv(source, index=False)
    prepared = registration.root / "prepared"
    model = registration.source / "model"
    shutil.rmtree(model)
    prepare(SCENARIO, source, prepared)
    train(SCENARIO, prepared, model)
    stamp_model(model, registration.tags)
    evaluate(SCENARIO, prepared, model, registration.source / "evaluation")
    result = model_tags.register_evaluated(MODEL_URI, "evaluated-model", SCENARIO, registration.context)
    assert result.version == "1"
    assert registration.register.call_args.kwargs["tags"]["quality_gate"] == "passed"


def test_notebook_and_job_wire_optional_context_without_automatic_registration():
    source = (NOTEBOOKS / "train.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert 'dbutils.widgets.text("model_context", "")' in source
    assert 'load_model_context(dbutils.widgets.get("model_context"), lake_value)' in source
    assert 'build_tags(scenario, context, engine="databricks")' in source
    assert 'mlflow.set_tags(model_tags)' in source
    assert 'mlflow.log_dict(model_tags, "model-tags.json")' in source
    assert source.index("train(scenario, prepared, model)") < source.index("stamp_model(model, model_tags)")
    assert source.index("stamp_model(model, model_tags)") < source.index("mlflow.log_artifacts(str(model)")
    assert 'model_uri = f"runs:/{run.info.run_id}/model"' in source
    assert not any(
        (isinstance(call.func, ast.Name) and call.func.id == "register_evaluated")
        or (isinstance(call.func, ast.Attribute) and call.func.attr in {"register_model", "create_model_version"})
        for call in calls
    )
    job = json.loads((NOTEBOOKS / "job-template.json").read_text(encoding="utf-8"))
    assert next(value for value in job["parameters"] if value["name"] == "model_context")["default"] == ""
    assert job["tasks"][0]["notebook_task"]["base_parameters"]["model_context"] == "{{job.parameters.model_context}}"
