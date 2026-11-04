"""function_app.py stays a thin adapter: it registers the routes and forwards to the framework-neutral API."""

import importlib
import json

import azure.functions as func
import pytest


@pytest.fixture
def function_app(monkeypatch):
    for name in ("AIF_BACKEND", "AIF_EXECUTOR", "AIF_STORE", "AIF_EVENT_PROCESSING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AIF_SELF_PROJECT_ID", "spider-esml-project001-sdc-dev-001-rg")
    import function_app as module
    module = importlib.reload(module)
    module.runtime.cache_clear()
    return module


def bindings(function_app):
    found = {}
    for function in function_app.app.get_functions():
        trigger = function.get_trigger()
        found[function.get_function_name()] = (trigger.get_binding_name(), getattr(trigger, "route", None),
                                               str(getattr(trigger, "auth_level", "")))
    return found


def test_routes_and_triggers_are_registered(function_app):
    found = bindings(function_app)
    assert found["health"][1] == "v1/health"
    assert found["prepare"][1] == "v1/lifecycle/{scenario}/prepare"
    assert found["get_operation"][1] == "v1/operations/{operation_id}"
    assert found["confirm"][1] == "v1/operations/{operation_id}/confirm"
    assert found["list_operations"][1] == "v1/operations"
    assert found["github_events"][1] == "v1/github/events"
    assert found["runner_results"][1] == "v1/runner/results"
    assert found["refresh_catalog"][1] == "v1/catalog/refresh"
    assert found["reconcile"][0] == "timerTrigger"
    assert "process_event" not in found


def test_lifecycle_routes_need_a_function_key_and_events_are_anonymous_but_signed(function_app):
    found = bindings(function_app)
    for route in ("prepare", "confirm", "refresh_catalog"):
        assert "FUNCTION" in found[route][2].upper()
    for route in ("github_events", "runner_results", "health"):
        assert "ANONYMOUS" in found[route][2].upper()


def test_a_request_flows_through_to_the_api(function_app):
    request = func.HttpRequest(method="POST", url="http://localhost/api/v1/lifecycle/init-factory/prepare",
                               route_params={"scenario": "init-factory"}, headers={"x-correlation-id": "t-1"},
                               body=json.dumps({"factoryId": "aif-121-sdc-dev"}).encode())
    response = function_app.prepare(request)
    assert response.status_code == 202
    assert response.headers["Location"].startswith("/api/v1/operations/")
    assert response.headers["x-correlation-id"] == "t-1"
    assert json.loads(response.get_body())["status"] == "awaiting_confirmation"
