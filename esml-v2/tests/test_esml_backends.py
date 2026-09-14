"""Offline adapter contracts exercised with the installed Azure ML v2 schemas."""

from copy import deepcopy
from io import StringIO
import inspect
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import yaml
from marshmallow import ValidationError
from azure.ai.ml import Input, Output, load_component, load_data, load_datastore, load_job, load_model
from azure.ai.ml.entities import (
    AzureBlobDatastore, AzureDataLakeGen2Datastore, Data, Model, PipelineComponentBatchDeployment,
)
from azure.ai.ml.operations import BatchEndpointOperations
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from azure_esml.base_layer import (
    AzureMLCLIBackend, AzureMLSDKBackend, BlobFolderCatalog, LocalFolderCatalog, MLBackend, WorkspaceTarget,
)
from azure_esml.base_layer.azure_ml import _deployment_entity


TARGET = WorkspaceTarget(
    "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222", "rg-test", "workspace-test",
)
COMPONENT_ID = (
    f"/subscriptions/{TARGET.subscription_id}/resourceGroups/{TARGET.resource_group}"
    f"/providers/Microsoft.MachineLearningServices/workspaces/{TARGET.workspace_name}"
    "/components/transform/versions/1"
)
DATA = {
    "name": "records", "version": "1", "type": "uri_folder",
    "path": "azureml://datastores/inputstore/paths/records/", "tags": {"purpose": "test"},
}
JOB = {
    "name": "test-job", "status": "Completed", "type": "pipeline", "tags": {"purpose": "test"},
    "jobs": {"evaluate": {"type": "command", "command": "private command", "environment_variables": {"key": "secret"}}},
    "outputs": {"result": {"type": "uri_folder", "path": "azureml://datastores/outputstore/paths/result/"}},
}


@pytest.fixture
def workspace(monkeypatch):
    path = Path(__file__).resolve().parents[1] / f".backend-test-{uuid4().hex}"
    path.mkdir()
    monkeypatch.chdir(path)
    yield path
    monkeypatch.undo()
    shutil.rmtree(path)


@pytest.fixture
def documents(workspace):
    code = workspace / "source"
    code.mkdir()
    (code / "run.py").write_text("print('test')", encoding="utf-8")
    command = {
        "type": "command", "code": "./source",
        "inputs": {"source": {"type": "uri_folder"}},
        "outputs": {"result": {"type": "uri_folder"}},
        "environment": "azureml:test-environment:1",
        "command": "python run.py --source ${{inputs.source}} --result ${{outputs.result}}",
    }
    component = {
        "type": "pipeline", "name": "transform", "version": "1",
        "inputs": {"source": {"type": "uri_folder"}},
        "outputs": {"result": {"type": "uri_folder"}},
        "jobs": {"transform": {
            "type": "command", "component": command,
            "inputs": {"source": "${{parent.inputs.source}}"},
            "outputs": {"result": "${{parent.outputs.result}}"},
        }},
    }
    job = deepcopy(component)
    job.pop("version")
    job["settings"] = {"default_compute": "azureml:existing-compute"}
    job["inputs"] = {"source": {"type": "uri_folder", "path": DATA["path"]}}
    endpoint = {"name": "batch-endpoint", "tags": {"purpose": "test"}}
    deployment = {"name": "candidate", "settings": {"default_compute": "azureml:existing-compute"}}
    return SimpleNamespace(component=component, job=job, endpoint=endpoint, deployment=deployment)


class CLIRunner:
    def __init__(self):
        self.calls = []
        self.documents = []
        self.resources = {}
        self.jobs = [deepcopy(JOB)]
        self.wire = None

    def __call__(self, argv):
        self.calls.append(argv)
        assert argv[0] == "az" and argv[-3:] == ["--output", "json", "--only-show-errors"]
        if argv[1:3] == ["extension", "show"]:
            return {"version": "2.35.0"}
        if argv[1:3] == ["account", "show"]:
            return {"tenantId": TARGET.tenant_id, "id": TARGET.subscription_id}
        if argv[1] == "rest":
            url = argv[argv.index("--url") + 1]
            name = url.split("/datastores/", 1)[1].split("?", 1)[0]
            value = self.resources["datastore", name, None]
            return {"credentials_type": value.get("credentials", {}).get("type", "None")}
        assert argv[1] == "ml"
        for flag, value in (
            ("--subscription", TARGET.subscription_id), ("--resource-group", TARGET.resource_group),
            ("--workspace-name", TARGET.workspace_name),
        ):
            assert argv[argv.index(flag) + 1] == value
        group, action = argv[2:4]
        name = argv[argv.index("--name") + 1] if "--name" in argv else None
        version = argv[argv.index("--version") + 1] if "--version" in argv else None
        if action == "show":
            if group == "job":
                return deepcopy(JOB)
            key = group, name, version
            if key not in self.resources:
                raise subprocess.CalledProcessError(3, argv, stderr="ERROR: (ResourceNotFound) Missing")
            return deepcopy(self.resources[key])
        if action == "list":
            assert group == "job"
            return self.jobs
        if action == "download":
            assert Path(argv[argv.index("--download-path") + 1]).is_dir()
            return {}
        path = Path(argv[argv.index("--file") + 1])
        assert path.is_file()
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.documents.append((group, path, doc))
        if action == "invoke":
            assert group == "batch-endpoint"
            schema = vars(inspect.getmodule(BatchEndpointOperations))["BatchJobSchema"]
            assert set(doc) == {"inputs", "outputs"}
            self.wire = schema(context={"base_path": path.parent}).load({
                "input_data": {key: Input(**value) for key, value in doc["inputs"].items()},
                "output_data": {key: Output(**value) for key, value in doc["outputs"].items()},
            })
            return deepcopy(JOB)
        assert action == "create"
        if group == "job":
            entity = load_job(path)
            assert Path(entity.base_path) == path.parent
            return deepcopy(JOB)
        if group == "component":
            entity = load_component(path)
            assert entity._validate().error_messages == {}
            return {**doc, "id": COMPONENT_ID}
        if group == "batch-deployment":
            assert isinstance(_deployment_entity(doc, path.parent), PipelineComponentBatchDeployment)
        if group == "data":
            load_data(path)
        if group == "datastore":
            load_datastore(path)
        if group == "model":
            load_model(path)
            return {**doc, "version": doc.get("version", "7")}
        return doc


@pytest.fixture(params=["sdk", "cli"])
def backend(request):
    if request.param == "cli":
        runner = CLIRunner()
        return AzureMLCLIBackend(TARGET, runner), runner
    client = Mock()
    client.jobs.create_or_update.return_value = deepcopy(JOB)
    client.jobs.get.return_value = deepcopy(JOB)
    client.jobs.list.return_value = iter([deepcopy(JOB), deepcopy(JOB)])
    client.batch_endpoints.invoke.return_value = deepcopy(JOB)
    return AzureMLSDKBackend(TARGET, client=client), client


def test_job_operations_and_relative_origin(backend, workspace, documents):
    adapter, transport = backend
    original = deepcopy(documents.job)
    assert isinstance(adapter, MLBackend)
    assert adapter.submit(documents.job, workspace)["name"] == "test-job"
    assert documents.job == original
    assert adapter.get_job("test-job")["status"] == "Completed"
    assert len(adapter.list_jobs(limit=1)) == 1
    destination = workspace / "download"
    adapter.download_job("test-job", destination, "result")
    with pytest.raises(FileExistsError):
        adapter.download_job("test-job", destination, "result")
    if isinstance(transport, CLIRunner):
        assert not any(path.exists() for _, path, _ in transport.documents)
        assert "--output-name" in transport.calls[-1]
        assert "--all" not in transport.calls[-1]
    else:
        entity = transport.jobs.create_or_update.call_args.args[0]
        assert Path(entity.base_path) == workspace
        assert Path(entity.jobs["transform"].component.base_path) == workspace
        transport.jobs.download.assert_called_once_with(
            name="test-job", download_path=str(destination), output_name="result",
        )


def existing(transport, group, value):
    if isinstance(transport, CLIRunner):
        transport.resources[group, value["name"], value.get("version")] = deepcopy(value)
    else:
        getattr(transport, {"data": "data", "model": "models", "datastore": "datastores",
                            "component": "components", "batch-endpoint": "batch_endpoints"}[group]).get.return_value = value


def missing(transport, group):
    if not isinstance(transport, CLIRunner):
        operations = getattr(transport, {"data": "data", "datastore": "datastores",
                                        "component": "components", "batch-endpoint": "batch_endpoints"}[group])
        operations.get.side_effect = ResourceNotFoundError("missing")
        operations.create_or_update.side_effect = lambda entity: entity


@pytest.mark.parametrize("kind,location", [("azure_blob", "container_name"), ("azure_data_lake_gen2", "filesystem")])
def test_credentialless_datastore_create_and_reuse(backend, workspace, kind, location):
    adapter, transport = backend
    definition = {"name": "inputstore", "type": kind, "account_name": "storageaccount", location: "records"}
    missing(transport, "datastore")
    created = adapter.ensure_datastore(definition)
    assert created["type"] == kind
    assert "credentials" not in created
    if not isinstance(transport, CLIRunner):
        cls = AzureBlobDatastore if kind == "azure_blob" else AzureDataLakeGen2Datastore
        assert isinstance(transport.datastores.create_or_update.call_args.args[0], cls)
        transport.datastores.get.side_effect = None
        transport.datastores.create_or_update.reset_mock()
    existing(transport, "datastore", definition)
    assert adapter.ensure_datastore(definition)["name"] == "inputstore"
    for changed in (
        {location: "different"}, {"credentials": {"type": "account_key", "account_key": "never-return"}},
        {"endpoint": "another.example"}, {"protocol": "http"}, {"account_name": "otherstorage"},
    ):
        existing(transport, "datastore", {**definition, **changed})
        with pytest.raises(ValueError, match="differ"):
            adapter.ensure_datastore(definition)
    if not isinstance(transport, CLIRunner):
        transport.datastores.create_or_update.assert_not_called()


def test_data_register_read_immutable_and_model_read(backend, workspace):
    adapter, transport = backend
    missing(transport, "data")
    assert adapter.register_data(DATA)["version"] == "1"
    if not isinstance(transport, CLIRunner):
        assert isinstance(transport.data.create_or_update.call_args.args[0], Data)
        transport.data.get.side_effect = None
        transport.data.create_or_update.reset_mock()
    existing(transport, "data", DATA)
    existing(transport, "model", {**DATA, "type": "mlflow_model"})
    assert adapter.get_data("records", "1")["path"] == DATA["path"]
    assert adapter.get_model("records", "1")["type"] == "mlflow_model"
    assert adapter.register_data(DATA)["tags"] == DATA["tags"]
    for changed in ({"path": DATA["path"] + "other"}, {"tags": {}}, {"tags": {**DATA["tags"], "extra": "tag"}}):
        existing(transport, "data", {**DATA, **changed})
        with pytest.raises(ValueError, match="differ"):
            adapter.register_data(DATA)
    if not isinstance(transport, CLIRunner):
        transport.data.create_or_update.assert_not_called()


@pytest.mark.parametrize("model_type", ["custom_model", "mlflow_model", "triton_model"])
@pytest.mark.parametrize("version", [None, "3"])
def test_model_registration_uses_injected_backend_and_optional_version(backend, workspace, model_type, version):
    adapter, transport = backend
    definition = {
        "$schema": "https://azuremlschemas.azureedge.net/latest/model.schema.json",
        "name": "candidate-model", "type": model_type,
        "path": "azureml://datastores/models/paths/candidate/",
        "tags": {"purpose": "candidate"}, "description": "A generic model artifact",
    }
    if version is not None:
        definition["version"] = version
    original = deepcopy(definition)
    if not isinstance(transport, CLIRunner):
        transport.models.create_or_update.return_value = {
            **definition, "version": version or "7", "credentials": {"secret": "never-return"},
        }
    result = adapter.register_model(definition)
    assert definition == original
    assert result["name"] == "candidate-model"
    assert result["version"] == (version or "7")
    assert result["type"] == model_type
    assert "$schema" not in result and "credentials" not in result
    if isinstance(transport, CLIRunner):
        group, path, doc = transport.documents[-1]
        assert group == "model" and path.parent == workspace and not path.exists()
        assert "$schema" not in doc
        assert ("version" in doc) == (version is not None)
        assert transport.calls[-1][1:4] == ["ml", "model", "create"]
    else:
        entity = transport.models.create_or_update.call_args.args[0]
        assert isinstance(entity, Model)
        assert entity.version == version and entity.path == definition["path"]
        transport.models.create_or_update.assert_called_once()
        transport.models.get.assert_not_called()


@pytest.mark.parametrize("change", [
    {"name": "--debug"}, {"type": "uri_folder"}, {"path": ""}, {"path": None},
    {"version": "latest"}, {"version": None}, {"tags": {"purpose": 1}},
    {"credentials": {"account_key": "secret"}},
])
def test_invalid_model_registration_fails_before_transport(backend, change):
    adapter, transport = backend
    definition = {"name": "candidate", "type": "custom_model", "path": "./model"}
    with pytest.raises(ValueError):
        adapter.register_model({**definition, **change})
    assert not transport.calls if isinstance(transport, CLIRunner) else not transport.mock_calls


def test_job_metadata_contains_only_child_types_for_external_registration_gate(backend):
    result = backend[0].get_job("test-job")
    assert result["type"] == "pipeline"
    assert result["jobs"] == {"evaluate": {"type": "command"}}
    assert result["outputs"] == {key: {**value, "mode": None} for key, value in JOB["outputs"].items()}
    assert "secret" not in json.dumps(result) and "private command" not in json.dumps(result)


def test_sdk_job_metadata_handles_real_pipeline_children(documents, workspace):
    entity = load_job(StringIO(yaml.safe_dump(documents.job)), relative_origin=str(workspace / "job.yaml"))
    client = Mock()
    client.jobs.get.return_value = entity
    result = AzureMLSDKBackend(TARGET, client=client).get_job("transform")
    assert result["type"] == "pipeline"
    assert result["jobs"] == {"transform": {"type": "command"}}
    assert set(result["outputs"]) == {"result"}


def test_publish_genuine_pipeline_schema_and_explicit_reuse(backend, workspace, documents):
    adapter, transport = backend
    missing(transport, "component")
    missing(transport, "batch-endpoint")
    if not isinstance(transport, CLIRunner):
        transport.components.create_or_update.side_effect = None
        transport.components.create_or_update.return_value = {"id": COMPONENT_ID}
        transport.batch_endpoints.begin_create_or_update.return_value.result.return_value = documents.endpoint
    result = adapter.publish(documents.component, documents.endpoint, documents.deployment, workspace)
    assert result["component_id"] == COMPONENT_ID
    assert result["deployment_name"] == "candidate"
    if not isinstance(transport, CLIRunner):
        deployment = transport.batch_deployments.begin_create_or_update.call_args.args[0]
        assert isinstance(deployment, PipelineComponentBatchDeployment)
        assert deployment.component == COMPONENT_ID
        assert deployment.settings["default_compute"] == "azureml:existing-compute"
        transport.components.get.side_effect = None
        transport.batch_endpoints.get.side_effect = None
        transport.components.create_or_update.reset_mock()
        transport.batch_endpoints.begin_create_or_update.reset_mock()
    existing(transport, "component", {"name": "transform", "version": "1", "id": COMPONENT_ID})
    existing(transport, "batch-endpoint", {**documents.endpoint, "defaults": {"deployment_name": "production"}})
    with pytest.raises(ValueError, match="already exists"):
        adapter.publish(documents.component, documents.endpoint, documents.deployment, workspace)
    adapter.publish(documents.component, documents.endpoint, documents.deployment, workspace, reuse_component=True)
    if isinstance(transport, CLIRunner):
        assert not any("--set-default" in argv or "update" in argv for argv in transport.calls)
        assert not any(path.exists() for _, path, _ in transport.documents)
    else:
        transport.components.create_or_update.assert_not_called()
        transport.batch_endpoints.begin_create_or_update.assert_not_called()
        transport.compute.assert_not_called()


def test_invoke_named_data_outputs_and_literals_wire_compatibility(backend, workspace):
    adapter, transport = backend
    inputs = {
        "source": {"type": "uri_folder", "path": DATA["path"]},
        "count": 3, "threshold": 0.5, "enabled": False, "text": "spaces & quotes ' \"",
    }
    outputs = {"result": {"type": "uri_folder", "path": DATA["path"] + "result/", "mode": "upload"}}
    assert adapter.invoke("batch-endpoint", "candidate", inputs, outputs)["name"] == "test-job"
    if isinstance(transport, CLIRunner):
        wire = transport.wire
        assert "--deployment-name" in transport.calls[-1]
        assert not transport.documents[-1][1].exists()
    else:
        arguments = transport.batch_endpoints.invoke.call_args.kwargs
        assert arguments["deployment_name"] == "candidate"
        assert all(isinstance(value, Input) for value in arguments["inputs"].values())
        assert isinstance(arguments["outputs"]["result"], Output)
        schema = vars(inspect.getmodule(BatchEndpointOperations))["BatchJobSchema"]
        wire = schema(context={"base_path": workspace}).load({
            "input_data": arguments["inputs"], "output_data": arguments["outputs"],
        })
    assert wire["inputData"]["count"] == {"jobInputType": "Literal", "value": 3}
    assert wire["inputData"]["enabled"] == {"jobInputType": "Literal", "value": False}
    assert wire["inputData"]["source"] == {"jobInputType": "UriFolder", "uri": DATA["path"]}
    assert wire["outputData"]["result"]["uri"] == outputs["result"]["path"]
    assert inputs["count"] == 3


@pytest.mark.parametrize("version", ["latest", "active", "0", "", None, "1 --debug"])
def test_pinned_versions_required(backend, version):
    adapter, _ = backend
    for operation in (adapter.get_data, adapter.get_model):
        with pytest.raises(ValueError):
            operation("asset", version)
    with pytest.raises(ValueError):
        adapter.register_data({**DATA, "version": version})


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 1.0])
def test_job_list_limit_validation(backend, limit):
    with pytest.raises(ValueError):
        backend[0].list_jobs(limit)


@pytest.mark.parametrize("inputs,outputs", [
    ({"bad name": 1}, {}), ({"a": float("nan")}, {}), ({"a": None}, {}),
    ({"a": {"type": "integer", "default": True}}, {}),
    ({"a": {"type": "uri_folder"}}, {}), ({}, {"a": "path"}),
    ({}, {"a": {"type": "uri_folder", "path": "x", "credentials": "bad"}}),
])
def test_invalid_invocation_fails_before_transport(backend, inputs, outputs):
    adapter, transport = backend
    with pytest.raises(ValueError):
        adapter.invoke("endpoint", "deployment", inputs, outputs)
    if isinstance(transport, CLIRunner):
        assert not transport.calls
    else:
        assert not transport.mock_calls


def test_records_do_not_return_credentials_or_signed_urls(backend):
    adapter, transport = backend
    value = {
        **DATA, "credentials": {"password": "secret"},
        "path": "https://user:password@example.test/records?sig=secret#secret",
        "tags": {"purpose": "test", "access_token": "secret"},
    }
    existing(transport, "data", value)
    result = adapter.get_data("records", "1")
    assert "secret" not in json.dumps(result)
    assert result["path"] == "https://example.test/records"
    assert result["tags"] == {"purpose": "test"}


def test_explicit_identity_factories(monkeypatch):
    import azure.ai.ml
    import azure.identity
    cli, managed, client = Mock(), Mock(), Mock()
    monkeypatch.setattr(azure.identity, "AzureCliCredential", cli)
    monkeypatch.setattr(azure.identity, "ManagedIdentityCredential", managed)
    monkeypatch.setattr(azure.ai.ml, "MLClient", client)
    AzureMLSDKBackend.from_cli(TARGET)
    cli.assert_called_once_with(tenant_id=TARGET.tenant_id, process_timeout=60)
    AzureMLSDKBackend.from_managed_identity(TARGET, client_id="explicit-client")
    managed.assert_called_once_with(client_id="explicit-client")
    assert client.call_args.kwargs["workspace_name"] == TARGET.workspace_name
    with pytest.raises(ValueError, match="explicit credential"):
        AzureMLSDKBackend(TARGET)


@pytest.mark.parametrize("failure", [
    subprocess.CalledProcessError(1, ["az"], stderr="ERROR: (AuthorizationFailed) denied"),
    subprocess.CalledProcessError(1, ["az"], stderr="ERROR: resource missing or permission denied"),
])
def test_cli_does_not_create_on_ambiguous_show_errors(failure, workspace):
    runner = CLIRunner()
    def run(argv):
        if argv[1] == "ml":
            raise failure
        return runner(argv)
    with pytest.raises(subprocess.CalledProcessError):
        AzureMLCLIBackend(TARGET, run).register_data(DATA)
    assert not runner.documents


def test_sdk_does_not_create_on_authorization_error():
    client = Mock()
    client.data.get.side_effect = HttpResponseError("denied")
    with pytest.raises(HttpResponseError):
        AzureMLSDKBackend(TARGET, client=client).register_data(DATA)
    client.data.create_or_update.assert_not_called()


@pytest.mark.parametrize("entity", [
    AzureBlobDatastore(name="store", account_name="storageaccount", container_name="records"),
    AzureDataLakeGen2Datastore(name="store", account_name="storageaccount", filesystem="records"),
])
def test_sdk_reuses_real_credentialless_entities(entity):
    client = Mock()
    client.datastores.get.return_value = entity
    result = AzureMLSDKBackend(TARGET, client=client).ensure_datastore(entity._to_dict())
    assert result["type"] in {"azure_blob", "azure_data_lake_gen2"}
    client.datastores.create_or_update.assert_not_called()


@pytest.mark.parametrize("change", [
    {"credentials": {"type": "account_key", "account_key": "secret"}},
    {"credentials": {"account_key": None}}, {"type": "azure_file"}, {"protocol": "http"},
    {"endpoint": "https://storage.test/records"}, {"account_name": "--debug"},
])
def test_invalid_datastore_fails_before_transport(backend, change):
    adapter, transport = backend
    doc = {"type": "azure_blob", "name": "store", "account_name": "storageaccount", "container_name": "records"}
    with pytest.raises(ValueError):
        adapter.ensure_datastore({**doc, **change})
    assert not transport.calls if isinstance(transport, CLIRunner) else not transport.mock_calls


def test_invalid_publication_is_validated_before_any_remote_operation(backend, documents, workspace):
    adapter, transport = backend
    invalid = deepcopy(documents.component)
    invalid["outputs"]["result"] = {"type": "not-a-valid-type"}
    with pytest.raises(ValidationError):
        adapter.publish(invalid, documents.endpoint, documents.deployment, workspace)
    assert not transport.calls if isinstance(transport, CLIRunner) else not transport.mock_calls
    with pytest.raises(ValueError, match="Unsupported publication"):
        adapter.publish(documents.component, {**documents.endpoint, "defaults": {"deployment_name": "candidate"}},
                        documents.deployment, workspace)


def test_publication_rejects_foreign_component_id_before_endpoint_mutation(backend, documents, workspace):
    adapter, transport = backend
    existing(transport, "component", {"name": "transform", "version": "1", "id": COMPONENT_ID.replace("workspace-test", "other")})
    with pytest.raises(ValueError, match="does not match"):
        adapter.publish(documents.component, documents.endpoint, documents.deployment, workspace, reuse_component=True)
    if isinstance(transport, CLIRunner):
        assert not transport.documents
    else:
        transport.batch_endpoints.get.assert_not_called()
        transport.batch_endpoints.begin_create_or_update.assert_not_called()


def test_unknown_cli_json_shape_is_not_absence(workspace):
    runner = CLIRunner()
    def run(argv):
        if argv[1] == "ml":
            return {}
        return runner(argv)
    with pytest.raises(TypeError, match="named object"):
        AzureMLCLIBackend(TARGET, run).register_data(DATA)
    assert not runner.documents


@pytest.mark.parametrize("response", [
    {"version": "1.99.0"}, {"version": "garbage"},
    {"tenantId": "33333333-3333-3333-3333-333333333333", "id": TARGET.subscription_id},
    {"tenantId": TARGET.tenant_id, "id": "33333333-3333-3333-3333-333333333333"},
])
def test_cli_version_and_tenant_preflight(response):
    runner = CLIRunner()
    def run(argv):
        if "version" in response and argv[1] == "extension" or "tenantId" in response and argv[1] == "account":
            return response
        return runner(argv)
    with pytest.raises(ValueError):
        AzureMLCLIBackend(TARGET, run).get_job("test-job")
    assert not any(argv[1] == "ml" for argv in runner.calls)


def test_subprocess_argv_json_and_no_dynamic_install(monkeypatch):
    run = Mock(return_value=SimpleNamespace(stdout='{"name":"job"}'))
    monkeypatch.setattr(shutil, "which", lambda _: "az.exe")
    monkeypatch.setattr(subprocess, "run", run)
    assert AzureMLCLIBackend._run(["az", "ml", "job", "show", "--name", "job"]) == {"name": "job"}
    assert run.call_args.args[0] == ["az.exe", "ml", "job", "show", "--name", "job"]
    assert run.call_args.kwargs["shell"] is False
    assert run.call_args.kwargs["env"]["AZURE_EXTENSION_USE_DYNAMIC_INSTALL"] == "no"


def test_windows_cli_shim_uses_python_not_command_shell(monkeypatch, workspace):
    (workspace / "python.exe").touch()
    shim = workspace / "wbin" / "az.cmd"
    monkeypatch.setattr(shutil, "which", lambda _: str(shim))
    run = Mock(return_value=SimpleNamespace(stdout="{}"))
    monkeypatch.setattr(subprocess, "run", run)
    AzureMLCLIBackend._run(["az", "ml", "job", "download", "--download-path", 'a & echo "bad"'])
    assert run.call_args.args[0][:4] == [str(workspace / "python.exe"), "-I", "-m", "azure.cli"]
    assert run.call_args.args[0][-1] == 'a & echo "bad"'


def test_missing_cli_and_unsafe_shim_fail_without_installing(monkeypatch, workspace):
    run = Mock()
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError):
        AzureMLCLIBackend._run(["az", "version"])
    monkeypatch.setattr(shutil, "which", lambda _: str(workspace / "az.cmd"))
    with pytest.raises(RuntimeError, match="safely"):
        AzureMLCLIBackend._run(["az", "version"])
    run.assert_not_called()


def test_cli_file_collision_never_deletes_or_overwrites_existing(monkeypatch, workspace):
    import azure_esml.base_layer.azure_ml as module
    monkeypatch.setattr(module, "uuid4", lambda: SimpleNamespace(hex="collision"))
    path = workspace / ".azure-esml-collision.yaml"
    path.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        AzureMLCLIBackend(TARGET, CLIRunner()).submit({"type": "pipeline", "jobs": {}}, workspace)
    assert path.read_text(encoding="utf-8") == "keep"


def test_cli_document_is_cleaned_when_runner_fails(workspace):
    runner = CLIRunner()
    def run(argv):
        if "--file" in argv:
            assert Path(argv[argv.index("--file") + 1]).is_file()
            raise RuntimeError("failed")
        return runner(argv)
    with pytest.raises(RuntimeError, match="failed"):
        AzureMLCLIBackend(TARGET, run).submit({"type": "pipeline", "jobs": {}}, workspace)
    assert not list(workspace.glob(".azure-esml-*.yaml"))


def test_local_and_blob_folders_are_direct_sorted_and_injected(workspace):
    from azure.storage.blob import BlobPrefix, BlobProperties
    for name in ("zeta", "alpha", ".hidden"):
        (workspace / name).mkdir()
    (workspace / "alpha" / "nested").mkdir()
    (workspace / "plain.txt").write_text("not a folder", encoding="utf-8")
    local = LocalFolderCatalog(workspace)
    assert local.list_folders("") == (".hidden", "alpha", "zeta")
    assert local.list_folders("alpha/") == ("nested",)
    container = Mock()
    container.walk_blobs.return_value = [
        BlobPrefix(prefix="prefix/zeta/"), BlobPrefix(prefix="prefix/alpha/"),
        BlobPrefix(prefix="prefix/alpha/"), BlobProperties(name="prefix/file.txt"),
        BlobPrefix(prefix="prefix/deep/child/"), BlobPrefix(prefix="outside/"),
    ]
    assert BlobFolderCatalog(container).list_folders("prefix") == ("alpha", "zeta")
    container.walk_blobs.assert_called_once_with(name_starts_with="prefix/", delimiter="/")
    for prefix in ("../outside", "/absolute", "C:\\root", "a\\b", "a//b", "a/./b", "a//"):
        with pytest.raises(ValueError):
            local.list_folders(prefix)
        with pytest.raises(ValueError):
            BlobFolderCatalog(container).list_folders(prefix)


def test_local_catalog_rejects_linked_folders(monkeypatch, workspace):
    import azure_esml.base_layer.folders as module
    (workspace / "linked").mkdir()
    original = module._is_link
    monkeypatch.setattr(module, "_is_link", lambda path: path.name == "linked" or original(path))
    local = LocalFolderCatalog(workspace)
    with pytest.raises(ValueError, match="symlinks"):
        local.list_folders("")
    with pytest.raises(ValueError, match="symlinks"):
        local.list_folders("linked")
    with pytest.raises(ValueError, match="symlinks"):
        LocalFolderCatalog(workspace / "linked")


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant"), ("subscription_id", "--debug"), ("workspace_name", "workspace;echo bad"),
    ("resource_group", " "), ("workspace_name", ""), ("resource_group", "bad."),
])
def test_workspace_target_rejects_unsafe_values(field, value):
    values = vars(TARGET).copy()
    values[field] = value
    with pytest.raises(ValueError):
        WorkspaceTarget(**values)
