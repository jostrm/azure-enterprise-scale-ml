"""Offline ADF contract tests; generated bundles stay under the project."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from azure_esml.domain_layer.contracts import PipelineType
from azure_esml.domain_layer.dataops import DataOpsAdapter, adf_pipeline
from azure_esml.domain_layer.project import ESMLProject
from azure_esml.domain_layer.settings import LakeSettings


ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = {
    "esml_data_date_utc": "2026-09-13",
    "esml_model_version": "7",
    "esml_run_id": "adf-run-123",
}


def settings_document(count=1):
    return {
        "aifactory": "factory-test", "project_number": 1, "active_model": 1,
        "storage": {"datastore": "lake", "prefix": "mlops/v1"},
        "runtime": {
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "subscription_id": "00000000-0000-0000-0000-000000000002",
            "resource_group": "rg-test", "workspace_name": "ml-test",
            "environment_name": "dev", "compute": "cpu", "environment": "azureml:runtime:1",
        },
        "models": [{
            "model_number": 1, "model_folder_name": "customer-churn",
            "dataset_folder_names": [f"source-{index}" for index in range(count)],
            "ml_type": "classification", "label": "label", "features": ["age"],
        }],
    }


class RecordingBackend:
    def __init__(self, scope):
        self.scope = scope
        self.documents = []
        self.paths = []
        self.jobs = {}
        self.model_reads = []
        self.job_reads = []

    def get_model(self, name, version):
        self.model_reads.append((name, version))
        return {"tags": {**self.scope, "use_case": name, "task_type": "classification"}}

    def submit(self, document, base_path):
        assert base_path.is_dir()
        assert base_path.name == "pipeline"
        assert any(base_path.iterdir())
        self.documents.append(deepcopy(document))
        self.paths.append(base_path)
        job = {
            "name": document["name"], "id": f"/jobs/{document['name']}", "status": "Running",
            "tags": deepcopy(document["tags"]), "experiment_name": document["experiment_name"],
        }
        return self.jobs.setdefault(job["name"], job)

    def get_job(self, name):
        self.job_reads.append(name)
        if name not in self.jobs:
            from azure.core.exceptions import ResourceNotFoundError
            raise ResourceNotFoundError("Job does not exist")
        return self.jobs[name]


@pytest.fixture
def workspace(monkeypatch):
    with TemporaryDirectory(prefix=".dataops-tests-", dir=ROOT) as directory:
        path = Path(directory)
        monkeypatch.chdir(path)
        monkeypatch.setattr("tempfile.tempdir", directory)
        yield path
        monkeypatch.chdir(ROOT)


def make_adapter(count=1):
    settings = LakeSettings.from_dict(settings_document(count))
    backend = RecordingBackend(settings.scope)
    project = ESMLProject(settings, backend=backend)
    project.wait_for_completion = Mock(side_effect=AssertionError("HTTP must not wait"))
    return DataOpsAdapter(project), backend


@pytest.mark.parametrize("count", [1, 4, 12])
def test_same_three_parameters_expand_configured_datasets_and_cleanup(workspace, count):
    adapter, backend = make_adapter(count)
    before = deepcopy(PARAMETERS)
    result = adapter.submit(PARAMETERS)
    assert PARAMETERS == before
    assert set(result) == {"name", "id", "status"}
    assert result["status"] == "Running"
    assert backend.model_reads == [("customer-churn", "7")]
    assert len([key for key in backend.documents[0]["inputs"] if key.startswith("raw_")]) == count
    assert backend.documents[0]["inputs"]["esml_data_date_utc"] == "2026-09-13"
    assert backend.documents[0]["inputs"]["esml_run_id"] == "adf-run-123"
    assert all(not path.parent.exists() for path in backend.paths)
    assert not list(workspace.iterdir())
    adapter.project.wait_for_completion.assert_not_called()


def test_optional_values_are_normalized_without_changing_server_scope(workspace):
    adapter, backend = make_adapter()
    adapter.submit({
        **PARAMETERS, "esml_data_date_utc": "2026-09-13T23:59:59Z", "esml_model_version": 7,
        "esml_data_version": "snapshot-42", "esml_project_name": "project001",
        "esml_environment": "dev", "esml_allow_reuse": False,
    })
    document = backend.documents[0]
    assert document["inputs"]["esml_model_version"] == "7"
    assert document["inputs"]["esml_data_date_utc"] == "2026-09-13"
    assert document["inputs"]["esml_data_version"] == "snapshot-42"
    assert document["settings"]["force_rerun"] is True
    assert adapter.project.settings.project == "001"
    assert adapter.project.target.workspace_name == "ml-test"


def test_render_bundle_uses_host_temp_storage_not_deployment_directory(workspace, monkeypatch):
    deployment = workspace / "deployment"
    deployment.mkdir()
    monkeypatch.chdir(deployment)
    adapter, backend = make_adapter()
    adapter.submit(PARAMETERS)
    assert backend.paths[0].parent.parent == workspace
    assert not list(deployment.iterdir())
    assert not backend.paths[0].parent.exists()


@pytest.mark.parametrize("key", list(PARAMETERS))
def test_required_values_cannot_default_to_clock_or_champion(workspace, key):
    adapter, backend = make_adapter()
    parameters = {name: value for name, value in PARAMETERS.items() if name != key}
    with pytest.raises(ValueError, match="Missing required"):
        adapter.submit(parameters)
    assert not backend.documents
    assert not list(workspace.iterdir())


@pytest.mark.parametrize("key,value", [
    ("esml_model_version", None), ("esml_model_version", ""), ("esml_model_version", 0),
    ("esml_model_version", "00"), ("esml_model_version", True), ("esml_model_version", 1.5),
    ("esml_model_version", "latest"), ("esml_model_version", "ACTIVE"),
    ("esml_model_version", "champion"), ("esml_model_version", "production"),
    ("esml_model_version", "../7"), ("esml_model_version", "azureml:model:7"),
    ("esml_run_id", None), ("esml_run_id", ""), ("esml_run_id", 123),
    ("esml_run_id", "run/123"), ("esml_run_id", ".."),
    ("esml_data_date_utc", None), ("esml_data_date_utc", "2026-02-30"),
    ("esml_data_date_utc", "2026-09-13T10:00:00"),
    ("esml_data_date_utc", "2026-09-13T10:00:00+02:00"),
    ("esml_allow_reuse", "false"), ("esml_allow_reuse", 0), ("esml_allow_reuse", None),
    ("esml_data_version", None), ("esml_data_version", ""), ("esml_data_version", "latest"),
    ("esml_project_name", "project002"), ("esml_project_name", "001"),
    ("esml_environment", "prod"), ("esml_environment", None),
])
def test_invalid_parameters_fail_before_planning_or_backend(workspace, key, value):
    adapter, backend = make_adapter()
    with pytest.raises(ValueError):
        adapter.submit({**PARAMETERS, key: value})
    assert not backend.model_reads
    assert not backend.documents
    assert not list(workspace.iterdir())


@pytest.mark.parametrize("key", [
    "workspace_name", "tenant_id", "subscription_id", "resource_group",
    "esml_workspace_name", "esml_model_number", "input_path", "output",
    "datasets", "parameters", "esml_snapshot_id",
])
def test_unknown_or_destination_overrides_are_rejected(workspace, key):
    adapter, backend = make_adapter()
    with pytest.raises(ValueError, match="Unsupported"):
        adapter.submit({**PARAMETERS, key: "other"})
    assert not backend.documents


@pytest.mark.parametrize("parameters", [None, [], "{}", 1])
def test_request_must_be_an_object(workspace, parameters):
    adapter, _ = make_adapter()
    with pytest.raises(ValueError, match="JSON object"):
        adapter.submit(parameters)


@pytest.mark.parametrize("kind", [
    PipelineType.IN_2_GOLD, PipelineType.IN_2_GOLD_TRAINING_AUTOML,
    PipelineType.IN_2_GOLD_TRAINING_MANUAL, "IN_2_GOLD_INFERENCE", None,
])
def test_only_explicit_inference_types_are_allowed(kind):
    with pytest.raises(ValueError, match="inference"):
        DataOpsAdapter(None, kind)


def test_retries_keep_job_identity_despite_different_render_directories(workspace):
    adapter, backend = make_adapter()
    first = adapter.submit(PARAMETERS)
    second = adapter.submit(dict(PARAMETERS))
    assert first == second
    assert len(backend.paths) == len(backend.documents) == 1
    with pytest.raises(ValueError, match="different request"):
        adapter.submit({**PARAMETERS, "esml_model_version": "8"})
    third = adapter.submit({**PARAMETERS, "esml_run_id": "adf-new-attempt"})
    assert third["name"] != first["name"]


@pytest.mark.parametrize("phase", ["planning", "submission"])
def test_bundle_cleanup_on_errors(workspace, phase):
    adapter, backend = make_adapter()
    method = "create_pipeline" if phase == "planning" else "execute_pipeline"
    setattr(adapter.project, method, Mock(side_effect=RuntimeError("backend failed")))
    with pytest.raises(RuntimeError, match="backend failed"):
        adapter.submit(PARAMETERS)
    assert not list(workspace.iterdir())


@pytest.mark.parametrize("status", ["Running", "Completed", "Succeeded", "Failed", "Canceled", "Cancelled",
                                  "NotResponding"])
def test_poll_reads_once_and_preserves_real_status(workspace, status):
    adapter, backend = make_adapter()
    job = adapter.submit(PARAMETERS)
    backend.job_reads.clear()
    backend.jobs[job["name"]]["status"] = status
    result = adapter.status(job["name"])
    assert result == {**job, "status": status}
    assert backend.job_reads == [job["name"]]
    assert len(backend.documents) == 1
    adapter.project.wait_for_completion.assert_not_called()


def test_unknown_backend_status_fails_closed_on_submit_and_poll(workspace):
    adapter, backend = make_adapter()
    job = adapter.submit(PARAMETERS)
    backend.jobs[job["name"]]["status"] = "FutureState"
    with pytest.raises(RuntimeError, match="unknown"):
        adapter.status(job["name"])
    with pytest.raises(RuntimeError, match="unknown"):
        adapter.submit(PARAMETERS)


@pytest.mark.parametrize("field,value", [
    ("project", "002"), ("aifactory", "other-factory"), ("environment", "prod"),
    ("esml_pipeline_type", "IN_2_GOLD_TRAINING_MANUAL"),
])
def test_poll_rejects_wrong_scope_before_exposing_job(workspace, field, value):
    adapter, backend = make_adapter()
    job = adapter.submit(PARAMETERS)
    backend.jobs[job["name"]]["tags"][field] = value
    with pytest.raises(ValueError):
        adapter.status(job["name"])


def test_poll_rejects_other_model_and_missing_tags(workspace):
    adapter, backend = make_adapter()
    job = adapter.submit(PARAMETERS)
    backend.jobs[job["name"]]["experiment_name"] = "other-model"
    with pytest.raises(ValueError, match="model"):
        adapter.status(job["name"])
    backend.jobs[job["name"]]["tags"] = {}
    with pytest.raises(ValueError):
        adapter.status(job["name"])


@pytest.mark.parametrize("name", ["../job", "https://other/job", "/subscriptions/other", None, 123])
def test_poll_rejects_paths_before_backend_read(name):
    adapter, backend = make_adapter()
    with pytest.raises(ValueError):
        adapter.status(name)
    assert not backend.job_reads


def test_backend_failures_are_not_reported_as_success(workspace):
    adapter, backend = make_adapter()
    backend.submit = Mock(return_value={"name": "job", "id": "/jobs/job"})
    with pytest.raises(RuntimeError, match="name, id and status"):
        adapter.submit(PARAMETERS)
    assert not list(workspace.iterdir())


def load_example():
    spec = importlib.util.spec_from_file_location("dataops_example", ROOT / "examples" / "app_layer" / "dataops_adapter.py")
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    return example


@pytest.mark.parametrize("entra_protected", [False, True])
def test_function_example_has_authenticated_async_routes(workspace, monkeypatch, entra_protected):
    routes = {}

    class FunctionApp:
        def __init__(self, **kwargs):
            assert kwargs["http_auth_level"] == ("anonymous" if entra_protected else "function")

        def route(self, **kwargs):
            def decorate(handler):
                routes[(kwargs["route"], kwargs["methods"][0])] = handler
                return handler
            return decorate

    functions = SimpleNamespace(
        FunctionApp=FunctionApp, AuthLevel=SimpleNamespace(FUNCTION="function", ANONYMOUS="anonymous"),
        HttpResponse=lambda body, **kwargs: SimpleNamespace(body=json.loads(body), **kwargs),
    )
    monkeypatch.setitem(sys.modules, "azure.functions", functions)
    example = load_example()
    path = workspace / "settings.json"
    path.write_text(json.dumps(settings_document(3)), encoding="utf-8")
    backend = RecordingBackend(LakeSettings.load(path).scope)
    options = {"entra_protected": True} if entra_protected else {}
    assert example.create_app(path, backend=backend, **options)
    post = routes[("esml/inference", "POST")]
    response = post(SimpleNamespace(get_json=lambda: dict(PARAMETERS)))
    assert response.status_code == 202
    assert response.body["status"] == "Running"
    get = routes[("esml/inference/{job_name}", "GET")]
    result = get(SimpleNamespace(route_params={"job_name": response.body["name"]}))
    assert result.status_code == 200
    assert result.body == response.body
    assert len(backend.documents) == 1
    invalid = post(SimpleNamespace(get_json=lambda: {**PARAMETERS, "workspace_name": "other"}))
    assert invalid.status_code == 400
    malformed = post(SimpleNamespace(get_json=Mock(side_effect=ValueError("bad JSON"))))
    assert malformed.status_code == 400


@pytest.mark.parametrize("flag", ["true", "false", None, 0, 1])
def test_function_auth_opt_in_requires_a_real_boolean(flag):
    example = load_example()
    with pytest.raises(ValueError, match="explicit boolean"):
        example.create_app("not-read.json", backend=None, entra_protected=flag)


def test_function_example_documents_mandatory_host_auth_for_msi():
    documentation = load_example().__doc__
    for requirement in ("EasyAuth", "require authentication", "audience", "restrict",
                        "ADF managed identity", "neither", "ANONYMOUS"):
        assert requirement in documentation


ADAPTER_URL = "https://esml-adapter.azurewebsites.net/api/esml/inference"
ADAPTER_RESOURCE = "api://00000000-0000-0000-0000-000000000003"


def test_adf_pipeline_binds_same_request_and_app_audience_to_async_routes():
    pipeline = adf_pipeline(ADAPTER_URL + "/", ADAPTER_RESOURCE)
    assert pipeline["name"] == "esml-inference"
    assert json.loads(json.dumps(pipeline)) == pipeline
    assert pipeline["properties"]["parameters"] == {"esml_request": {"type": "Object"}}
    submit, until, completed = pipeline["properties"]["activities"]
    assert submit["name"] == "Submit"
    assert submit["type"] == "WebActivity"
    assert submit["typeProperties"]["url"] == ADAPTER_URL
    assert submit["typeProperties"]["method"] == "POST"
    assert submit["typeProperties"]["body"] == {
        "value": "@string(pipeline().parameters.esml_request)", "type": "Expression",
    }
    assert "defaultValue" not in pipeline["properties"]["parameters"]["esml_request"]
    assert until["type"] == "Until"
    assert until["dependsOn"] == [{"activity": "Submit", "dependencyConditions": ["Succeeded"]}]
    assert until["typeProperties"]["timeout"] == "0.02:00:00"
    poll, remember, failed, delay = until["typeProperties"]["activities"]
    assert poll["type"] == "WebActivity"
    assert poll["typeProperties"]["method"] == "GET"
    assert poll["typeProperties"]["url"] == {
        "type": "Expression", "value": f"@concat('{ADAPTER_URL}/', activity('Submit').output.name)",
    }
    for activity in (submit, poll):
        assert activity["typeProperties"]["authentication"] == {
            "type": "MSI", "resource": ADAPTER_RESOURCE,
        }
        assert activity["typeProperties"]["turnOffAsync"] is True
    assert remember["typeProperties"]["value"]["value"] == "@activity('GetStatus').output.status"
    assert failed["dependsOn"] == [{"activity": "GetStatus", "dependencyConditions": ["Failed"]}]
    assert failed["typeProperties"]["value"] == "AdapterError"
    assert delay["type"] == "Wait"
    assert delay["dependsOn"] == [{"activity": "GetStatus", "dependencyConditions": ["Completed"]}]
    assert delay["typeProperties"]["waitTimeInSeconds"] == 30
    assert completed["type"] == "IfCondition"
    assert completed["dependsOn"] == [{"activity": "WaitForInference", "dependencyConditions": ["Succeeded"]}]
    assert completed["typeProperties"]["ifFalseActivities"][0]["type"] == "Fail"
    assert completed["typeProperties"]["ifTrueActivities"] == []


def test_adf_waits_only_for_known_active_states_and_success_is_explicit():
    pipeline = adf_pipeline(ADAPTER_URL, ADAPTER_RESOURCE, name="my-inference")
    assert pipeline["name"] == "my-inference"
    _, until, completed = pipeline["properties"]["activities"]
    active_expression = until["typeProperties"]["expression"]["value"]
    success_expression = completed["typeProperties"]["expression"]["value"]
    assert active_expression.startswith("@not(contains(createArray(")
    assert success_expression.startswith("@contains(createArray(")
    active = set(re.findall(r"'([^']+)'", active_expression)) - {"esml_job_status"}
    successes = set(re.findall(r"'([^']+)'", success_expression)) - {"esml_job_status"}
    assert active == {
        "NotStarted", "Starting", "Provisioning", "Preparing", "Queued", "Running",
        "Finalizing", "CancelRequested", "Paused", "Scheduled",
    }
    assert successes == {"Completed", "Succeeded"}
    for status in ("Failed", "Canceled", "Cancelled", "NotResponding", "FutureState", "AdapterError", ""):
        assert status not in active
        assert status not in successes


@pytest.mark.parametrize("url", [
    None, "", "http://adapter.example/api", "/relative", "https:///api",
    "https://user:password@adapter.example/api", "https://adapter.example/api?code=secret",
    "https://adapter.example/api?", "https://adapter.example/api#secret",
    "https://adapter.example/api#",
    "https://adapter.example/api/'expression", "https://adapter.example/api\n",
    "https://adapter.example/api\\path", "https://adapter.example:invalid/api",
])
def test_adf_rejects_unsafe_or_non_https_routes(url):
    with pytest.raises(ValueError, match="adapter_url"):
        adf_pipeline(url, ADAPTER_RESOURCE)


@pytest.mark.parametrize("resource", [
    None, "", "not-an-application-uri", "http://adapter.example",
    "https://management.azure.com/", "https://management.core.windows.net/",
    "https://ml.azure.com", "https://api.azureml.ms/",
    "https://management.usgovcloudapi.net/", "https://ml.azure.cn/",
    "api://adapter/.default", "api://adapter?token=secret", "api://user:secret@adapter",
])
def test_adf_requires_adapter_entra_audience_not_azure_ml_or_arm(resource):
    with pytest.raises(ValueError, match="adapter_resource"):
        adf_pipeline(ADAPTER_URL, resource)


def test_adf_supports_https_application_id_uri_and_rejects_unsafe_pipeline_name():
    resource = "https://apps.example.com/esml-adapter"
    pipeline = adf_pipeline(ADAPTER_URL, resource)
    assert pipeline["properties"]["activities"][0]["typeProperties"]["authentication"]["resource"] == resource
    with pytest.raises(ValueError):
        adf_pipeline(ADAPTER_URL, resource, name="../../pipeline")
