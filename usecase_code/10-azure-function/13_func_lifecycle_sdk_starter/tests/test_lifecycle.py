"""Scenario 3 on the mock, the error paths, the Function routes, and the same code on the real SDK."""

import importlib
import json
import os
import sys

import azure.functions as func
import pytest

from factory_client import MockFactoryClient, make_client
from lifecycle import Lifecycle, Problem

FOLDER = r"C:\repos\my-factory\azurefactory"
NEW = "aif-130-esml-project002-sdc-dev-001-rg"
EXISTING = "aif-130-esml-project001-sdc-dev-001-rg"


def confirm(api, operation):
    step = operation["steps"][operation["currentStep"]]
    return api.confirm(operation["operationId"], {"confirmationToken": step["preview"]["confirmationToken"]})


def run_to_end(api, operation):
    """Confirm each review once, read the operation while a step runs: what aif_func.py confirm/wait do."""
    for _ in range(10):
        if operation["status"] == "awaiting_confirmation":
            operation = confirm(api, operation)
        elif operation["status"] in ("running", "confirming", "preparing"):
            operation = api.get(operation["operationId"])
        else:
            return operation
    raise AssertionError(operation)


def test_a_new_number_adds_the_project_then_deploys_it():
    api = Lifecycle(MockFactoryClient(), FOLDER)
    operation = api.prepare("add-or-update-project", {"projectId": NEW})

    review = operation["steps"][0]["preview"]
    assert operation["status"] == "awaiting_confirmation"
    assert "configuration only" in review["plan"][0] and "Action: add-project" in review["plan"]
    assert review["affectedResourceGroups"] == [] and review["canExecute"] is True

    operation = confirm(api, operation)
    assert (operation["currentStep"], operation["status"]) == (1, "awaiting_confirmation")
    assert operation["steps"][1]["preview"]["affectedResourceGroups"] == [NEW]
    assert operation["steps"][0]["preview"]["confirmationToken"] is None

    assert run_to_end(api, operation)["status"] == "succeeded"
    assert api.list()["operations"][0]["status"] == "succeeded"


def test_an_existing_number_updates_its_settings():
    api = Lifecycle(MockFactoryClient(), FOLDER)
    operation = api.prepare("add-or-update-project", {"projectId": EXISTING, "settings": {"enableAISearch": True}})
    assert "Action: configure-settings" in operation["steps"][0]["preview"]["plan"]
    assert run_to_end(api, operation)["status"] == "succeeded"


def test_a_wrong_token_is_400_and_the_step_keeps_waiting():
    api = Lifecycle(MockFactoryClient(), FOLDER)
    operation = api.prepare("add-or-update-project", {"projectId": NEW})
    with pytest.raises(Problem) as refused:
        api.confirm(operation["operationId"], {"confirmationToken": "wrong"})
    assert (refused.value.status, refused.value.code) == (400, "confirmation-mismatch")
    assert api.get(operation["operationId"])["status"] == "awaiting_confirmation"


@pytest.mark.parametrize("scenario,body,status,code", [
    ("delete-factory", {"factoryId": "aif-130-sdc-dev"}, 400, "unsupported-scenario"),
    ("add-or-update-project", {"projectId": "not-a-group"}, 400, "invalid-id"),
    ("add-or-update-project", {"projectId": "other-esml-project002-sdc-dev-001-rg"}, 404, "unknown-id"),
])
def test_bad_requests_are_problems(scenario, body, status, code):
    with pytest.raises(Problem) as refused:
        Lifecycle(MockFactoryClient(), FOLDER).prepare(scenario, body)
    assert (refused.value.status, refused.value.code) == (status, code)


def test_an_expired_review_is_410():
    api = Lifecycle(MockFactoryClient(review_minutes=-1), FOLDER)
    operation = api.prepare("add-or-update-project", {"projectId": NEW})
    with pytest.raises(Problem) as refused:
        confirm(api, operation)
    assert refused.value.status == 410
    assert api.get(operation["operationId"])["status"] == "expired"


def test_the_function_routes_forward_to_the_core(monkeypatch):
    monkeypatch.setenv("AIF_BACKEND", "mock")
    import function_app
    module = importlib.reload(function_app)
    module.lifecycle.cache_clear()
    routes = {f.get_function_name(): (f.get_trigger().route, str(f.get_trigger().auth_level).split(".")[-1])
              for f in module.app.get_functions()}
    assert routes["health"] == ("v1/health", "ANONYMOUS")
    assert routes["prepare"] == ("v1/lifecycle/{scenario}/prepare", "FUNCTION")

    response = module.prepare(func.HttpRequest(method="POST", url="http://localhost/api/v1/lifecycle/x/prepare",
                                               route_params={"scenario": "add-or-update-project"},
                                               body=json.dumps({"projectId": NEW}).encode()))
    assert response.status_code == 202 and response.headers["Location"].startswith("/api/v1/operations/")
    bad = module.prepare(func.HttpRequest(method="POST", url="http://localhost/api/v1/lifecycle/x/prepare",
                                          route_params={"scenario": "add-or-update-project"}, body=b"{"))
    assert bad.status_code == 400 and json.loads(bad.get_body())["code"] == "invalid-json"


@pytest.fixture
def fake_factory_api():
    """The reference Function's loopback fake of the real Factory API (pink's catalog semantics), from the sibling
    folder 12_func_aifactory_lifecycle/tests (or AIF_REFERENCE_TESTS). Needs the SDK (requirements.txt)."""
    sibling = os.path.join(os.path.dirname(__file__), "..", "..", "12_func_aifactory_lifecycle", "tests")
    folder = os.environ.get("AIF_REFERENCE_TESTS") or sibling
    if not os.path.isfile(os.path.join(folder, "fake_factory_api.py")):
        pytest.skip("the reference Function's fake Factory API is not next to this folder")
    pytest.importorskip("azurefactory")
    sys.path.insert(0, os.path.abspath(folder))
    from fake_factory_api import FakeFactoryApi
    with FakeFactoryApi(api_key="test-key", stateful=True, coordination="blob") as api:
        yield api


def test_the_same_code_runs_on_the_real_sdk(fake_factory_api):
    client = make_client({"AIF_BACKEND": "sdk", "AIF_FACTORY_API_URL": fake_factory_api.url,
                          "AIF_FACTORY_API_KEY": "test-key"})
    assert type(client).__name__ == "AzureFactoryClient"
    api = Lifecycle(client, FOLDER)

    operation = api.prepare("add-or-update-project", {"projectId": "aif-121-esml-project002-sdc-dev-001-rg"})
    assert operation["status"] == "awaiting_confirmation", operation
    assert run_to_end(api, operation)["status"] == "succeeded"

    calls = [(c["method"], c["path"]) for c in fake_factory_api.calls if c["path"] != "/openapi.json"]
    assert ("POST", "/api/v1/factory-catalog/prepare") in calls
    assert calls.count(("POST", "/api/v1/factory-catalog/confirm")) == 2
    assert any(path.startswith("/api/v1/factory-catalog/jobs/") for _, path in calls)
    assert all(c["key"] for c in fake_factory_api.calls if c["path"] != "/api/v1/health")
