"""Mocked HTTP/frontend unit tests only: no Azure, Entra or Factory service calls."""

import base64
import hashlib
import inspect
import json
import re
import subprocess
import threading
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from azure.core.exceptions import HttpResponseError
from fastapi.testclient import TestClient

from aifactory_agent import security, web
from aifactory_agent.config import Settings
from aifactory_agent.knowledge import OwnershipError
from aifactory_agent.operations import BlobOperationBackend, MemoryOperationBackend, OperationError, OperationStore
from aifactory_agent.security import Principal

ROOT = Path(__file__).parents[1]
CLIENT_ID = "11111111-1111-4111-8111-111111111111"
OBJECT_ID = "22222222-2222-4222-8222-222222222222"
OPERATION_ID = "33333333-3333-4333-8333-333333333333"
HASH = "a" * 64


@pytest.fixture
def settings():
    config = json.loads((ROOT / "config.example.json").read_text("utf-8"))
    config["auth"].update(client_id=CLIENT_ID, audience="api://" + CLIENT_ID, grants=[{
        "object_id": OBJECT_ID, "scopes": ["project001-dev"],
        "permissions": ["knowledge.read", "factory.read", "config.write"],
    }])
    config["scopes"]["project002-dev"] = {**config["scopes"]["project001-dev"], "project": "002"}
    config["azure"]["application_insights_connection_string"] = "DO-NOT-EXPOSE-TELEMETRY"
    config["factory"]["api_key_secret_url"] = "https://example.vault.azure.net/secrets/DO-NOT-EXPOSE-SECRET"
    return Settings.model_validate(config)


@pytest.fixture
def principal(settings):
    return Principal(settings.tenant_id, OBJECT_ID, {"project001-dev"}, {"knowledge.read", "factory.read", "config.write"})


@pytest.fixture
def isolated(settings):
    app = web.create_app(settings)
    knowledge = Mock()
    knowledge.status.return_value = {
        "status": "ready", "stale": False, "indexed_document_count": 10, "reconciliation_pending": False,
    }
    store = Mock(spec=OperationStore)
    app.dependency_overrides[web.get_knowledge] = lambda: knowledge
    app.dependency_overrides[web.get_readiness_knowledge] = lambda: knowledge
    app.dependency_overrides[web.get_operation_store] = lambda: store
    return app, knowledge, store


@pytest.fixture
def authenticated(isolated, principal):
    app, knowledge, store = isolated
    app.dependency_overrides[web.get_principal] = lambda: principal
    return app, knowledge, store


@pytest.fixture
def proposal_enabled(authenticated):
    app, knowledge, store = authenticated
    factory = app.state.settings.factory.model_copy(update={
        "writes_enabled": True, "factory_id": UUID(CLIENT_ID),
        "scale_set_id": UUID(OBJECT_ID), "project_id": UUID(OPERATION_ID),
    })
    app.state.settings = app.state.settings.model_copy(update={"factory": factory})
    return app, knowledge, store


def test_liveness_and_public_config_do_not_expose_scopes_or_secrets(isolated, settings):
    app, knowledge, store = isolated
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "live"}
        response = client.get("/api/public-config")
        assert response.json() == {
            "tenant_id": settings.tenant_id, "client_id": CLIENT_ID,
            "audience": "api://" + CLIENT_ID, "required_scope": settings.auth.required_scope,
        }
        assert "project001" not in response.text and "DO-NOT-EXPOSE" not in response.text
    knowledge.status.assert_not_called()
    store.list.assert_not_called()


def test_default_configuration_is_fail_closed_without_azure_calls(monkeypatch):
    settings = Settings.model_validate(json.loads((ROOT / "config.example.json").read_text("utf-8")))
    assert settings.auth.client_id is None and settings.auth.audience is None
    construct = Mock(side_effect=AssertionError("A blocked registration must not construct Azure clients"))

    class NoCloudKnowledge(web.Knowledge):
        def __init__(self, *args, **kwargs):
            construct()

    class NoCloudStore(web.OperationStore):
        def __init__(self, *args, **kwargs):
            construct()

    monkeypatch.setattr(web, "Knowledge", NoCloudKnowledge)
    monkeypatch.setattr(web, "OperationStore", NoCloudStore)
    with TestClient(web.create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"] == {"authentication": "unconfigured", "knowledge": "not_checked"}
        for method, path, body in [
            ("GET", "/api/context", None),
            ("GET", "/api/skills?scope_key=project001-dev", None),
            ("GET", "/api/templates?scope_key=project001-dev", None),
            ("POST", "/api/chat", {"question": "Question", "audience": "platform", "scope_key": "project001-dev"}),
            ("POST", "/api/operations/propose", {"scope_key": "project001-dev", "settings": {
                "department_name": "Research", "department_id": None,
            }}),
            ("GET", "/api/operations", None),
            ("POST", "/api/operations/propose", {"scope_key": "project001-dev", "settings": {
                "department_name": "Research", "department_id": None,
            }}),
        ]:
            result = client.request(method, path, json=body)
            assert result.status_code == 503
            assert result.json()["error"]["code"] == "authentication_unavailable"
    construct.assert_not_called()


@pytest.mark.parametrize("status", [
    {"status": "not_initialized", "indexed_document_count": 0, "stale": True},
    {"status": "ready", "indexed_document_count": 10, "stale": True},
    {"status": "refresh_incomplete", "indexed_document_count": 10, "stale": False},
    {"status": "ready", "indexed_document_count": 0, "stale": False},
    {"status": "ready", "indexed_document_count": 10, "stale": False, "reconciliation_pending": True},
    {"status": "ready", "indexed_document_count": 10, "stale": False},
    {"status": "ready", "indexed_document_count": 10, "stale": False,
     "reconciliation_pending": False, "search_document_count": 9},
])
def test_readiness_does_not_claim_unavailable_knowledge_is_ready(isolated, status):
    app, knowledge, _ = isolated
    knowledge.status.return_value = status
    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["knowledge"] == "unavailable"


@pytest.mark.parametrize("error", [OwnershipError("SENSITIVE"), HttpResponseError("SENSITIVE")])
def test_readiness_handles_known_dependency_failures_without_details(isolated, error):
    app, knowledge, _ = isolated
    knowledge.status.side_effect = error
    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert "SENSITIVE" not in response.text


def test_mocked_readiness_explicitly_limits_its_claim(isolated):
    app, knowledge, _ = isolated
    knowledge.status.return_value["search_document_count"] = 10
    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert "not verified" in response.json()["coverage"]


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/context", None),
    ("GET", "/api/knowledge/status?scope_key=project001-dev", None),
    ("POST", "/api/chat", {"question": "Question", "audience": "project", "scope_key": "project001-dev"}),
    ("GET", "/api/operations", None),
    ("GET", f"/api/operations/{OPERATION_ID}", None),
    ("POST", f"/api/operations/{OPERATION_ID}/approve", {"plan_hash": HASH}),
    ("POST", f"/api/operations/{OPERATION_ID}/execute", None),
    ("POST", f"/api/operations/{OPERATION_ID}/cancel", None),
    ("POST", f"/api/operations/{OPERATION_ID}/continue", {"plan_hash": HASH, "observation_hash": HASH}),
    ("POST", "/api/skills/create-agent-oftype-for-project/propose", {"scope_key": "project001-dev", "arguments": {}}),
    ("POST", "/api/skills/create-ml-model-oftype-for-project/propose", {"scope_key": "project001-dev", "arguments": {}}),
])
def test_every_private_route_requires_a_bearer_token(isolated, method, path, body):
    app, knowledge, store = isolated
    with TestClient(app) as client:
        response = client.request(method, path, json=body)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
    knowledge.status.assert_not_called()
    assert not store.mock_calls


def test_http_auth_uses_real_security_verifier_interface(isolated, principal, settings, monkeypatch):
    app, _, _ = isolated
    verifier = Mock(return_value=principal)
    monkeypatch.setattr(security, "principal_from_token", verifier)
    with TestClient(app) as client:
        assert client.get("/api/context", headers={"Authorization": "Bearer unit-test-only-token"}).status_code == 200
    verifier.assert_called_once_with(settings, "unit-test-only-token")


@pytest.mark.parametrize("exception,status", [
    (security.AuthenticationError("SECRET-TOKEN"), 401),
    (security.AuthenticationUnavailable("SECRET-TOKEN"), 503),
])
def test_authentication_failures_are_json_without_token_details(isolated, monkeypatch, exception, status):
    app, _, _ = isolated
    monkeypatch.setattr(security, "principal_from_token", Mock(side_effect=exception))
    with TestClient(app) as client:
        response = client.get("/api/context", headers={"Authorization": "Bearer SECRET-TOKEN"})
        assert response.status_code == status and "SECRET-TOKEN" not in response.text
        assert "error" in response.json()


def test_context_exposes_only_current_per_scope_grants(authenticated):
    app, _, _ = authenticated
    with TestClient(app) as client:
        response = client.get("/api/context")
        assert response.status_code == 200
        context = response.json()
        assert [scope["key"] for scope in context["scopes"]] == ["project001-dev"]
        assert context["scopes"][0]["permissions"] == ["knowledge.read", "factory.read", "config.write"]
        assert context["capabilities"]["destructive_actions"] is False
        assert context["capabilities"]["model_read_only"] is True
        assert context["capabilities"]["proposal_creation"] is True
        assert context["capabilities"]["proposal_blockers"] == ["writes_disabled", "factory_target_unconfigured"]
        assert "DO-NOT-EXPOSE" not in response.text
        assert "project002" not in response.text
        assert "api_key_secret_url" not in response.text


@pytest.mark.parametrize("audience", ["platform", "project"])
def test_chat_is_sync_scoped_and_audience_never_grants_access(authenticated, principal, monkeypatch, audience):
    app, knowledge, _ = authenticated
    factory = Mock()
    factory.return_value.answer.return_value = {"answer": "Evidence-backed answer", "citations": []}
    monkeypatch.setattr(web, "Conversation", factory)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={
            "question": "Question", "audience": audience, "scope_key": "project001-dev",
        })
        assert response.status_code == 200
        factory.return_value.answer.assert_called_once_with("Question", audience, principal, "project001-dev")
        factory.assert_called_once()
        assert factory.call_args.args == (app.state.settings, knowledge)
        assert callable(factory.call_args.kwargs["tool_factory"])
        denied = client.post("/api/chat", json={
            "question": "Question", "audience": audience, "scope_key": "project002-dev",
        })
        assert denied.status_code == 403
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/chat")
    assert not inspect.iscoroutinefunction(route.endpoint)


def test_chat_blocking_work_runs_in_worker_thread(authenticated, monkeypatch):
    app, _, _ = authenticated
    main_thread = threading.get_ident()
    result_threads = []

    def answer(*args):
        result_threads.append((threading.get_ident(), threading.current_thread().name))
        return {"answer": "Mocked unit-test answer", "citations": []}

    monkeypatch.setattr(web, "Conversation", Mock(return_value=Mock(answer=answer)))
    with TestClient(app) as client:
        assert client.post("/api/chat", json={
            "question": "Q", "audience": "platform", "scope_key": "project001-dev",
        }).status_code == 200
    assert result_threads[0][0] != main_thread
    assert "worker" in result_threads[0][1].lower()


@pytest.mark.parametrize("body", [
    {"question": "", "audience": "project", "scope_key": "project001-dev"},
    {"question": "   ", "audience": "project", "scope_key": "project001-dev"},
    {"question": "SECRET" * 1400, "audience": "project", "scope_key": "project001-dev"},
    {"question": "Q", "audience": "administrator", "scope_key": "project001-dev"},
    {"question": "Q", "audience": "project", "scope_key": "../project002"},
    {"question": "Q", "audience": "project", "scope_key": "project001-dev", "token": "SECRET"},
])
def test_validation_rejects_bad_chat_and_does_not_echo_input(authenticated, monkeypatch, body):
    app, _, _ = authenticated
    answer = Mock()
    monkeypatch.setattr(web, "Conversation", answer)
    with TestClient(app) as client:
        response = client.post("/api/chat", json=body)
        assert response.status_code == 422
        assert "SECRET" not in response.text
        assert "input" not in response.text
    answer.assert_not_called()


def test_maximum_question_length_is_accepted(authenticated, monkeypatch):
    app, _, _ = authenticated
    monkeypatch.setattr(web, "Conversation", Mock(return_value=Mock(answer=Mock(return_value={"answer": "Mocked"}))))
    with TestClient(app) as client:
        assert client.post("/api/chat", json={
            "question": "Q" * 8000, "audience": "project", "scope_key": "project001-dev",
        }).status_code == 200


def test_status_requires_exact_scope_knowledge_permission(authenticated):
    app, knowledge, _ = authenticated
    with TestClient(app) as client:
        assert client.get("/api/knowledge/status?scope_key=project002-dev").status_code == 403
        knowledge.status.assert_not_called()
        response = client.get("/api/knowledge/status?scope_key=project001-dev")
        assert response.status_code == 200 and response.json()["scope_key"] == "project001-dev"
        for route in ("/api/knowledge/refresh", "/api/refresh"):
            assert client.post(route).status_code == 404


def test_permission_union_cannot_authorize_another_scope(settings, principal):
    config = settings.model_dump(mode="json")
    config["auth"]["grants"] = [
        {"object_id": OBJECT_ID, "scopes": ["project001-dev"], "permissions": ["factory.read"]},
        {"object_id": OBJECT_ID, "scopes": ["project002-dev"], "permissions": ["knowledge.read"]},
    ]
    app = web.create_app(Settings.model_validate(config))
    app.dependency_overrides[web.get_principal] = lambda: principal
    app.dependency_overrides[web.get_knowledge] = lambda: Mock()
    with TestClient(app) as client:
        context = client.get("/api/context").json()
        assert context["scopes"][0]["permissions"] == ["factory.read"]
        assert context["scopes"][1]["permissions"] == ["knowledge.read"]
        assert client.get("/api/knowledge/status?scope_key=project001-dev").status_code == 403


def test_operation_routes_use_caller_and_exact_hash_without_auto_execution(authenticated, principal):
    app, _, store = authenticated
    store.list.return_value = []
    store.read.return_value = {"id": OPERATION_ID, "status": "pending"}
    store.approve.return_value = {"id": OPERATION_ID, "status": "approved"}
    store.cancel.return_value = {"id": OPERATION_ID, "status": "cancelled"}
    with TestClient(app) as client:
        assert client.get("/api/operations").json() == {"operations": []}
        assert client.get(f"/api/operations/{OPERATION_ID}").json()["status"] == "pending"
        assert client.post(f"/api/operations/{OPERATION_ID}/approve", json={"plan_hash": HASH}).json()["status"] == "approved"
        store.execute.assert_not_called()
        assert client.post(f"/api/operations/{OPERATION_ID}/cancel").json()["status"] == "cancelled"
    store.list.assert_called_once_with(principal)
    store.read.assert_called_once_with(principal, OPERATION_ID)
    store.approve.assert_called_once_with(principal, OPERATION_ID, HASH)
    store.cancel.assert_called_once_with(principal, OPERATION_ID)


def test_no_generic_preparation_or_model_tool_route_is_exposed(authenticated):
    app, _, store = authenticated
    with TestClient(app) as client:
        for path in ("/api/operations/prepare", "/api/tools/prepare_settings"):
            assert client.post(path, json={"settings": {"department_name": "Research", "department_id": None}}).status_code in (404, 405)
    store.propose.assert_not_called()


def test_user_proposal_injects_same_store_and_never_approves_or_executes(proposal_enabled, principal, monkeypatch):
    app, _, store = proposal_enabled
    pending = {
        "id": OPERATION_ID, "scope_key": "project001-dev", "status": "pending", "plan_hash": HASH,
        "tenant_id": principal.tenant_id, "object_id": principal.object_id, "tool_name": web.CONFIGURE_TOOL,
    }
    tools = Mock(spec=web.FactoryTools)
    tools.prepare_settings.return_value = {"ok": True, "data": pending}
    factory = Mock(return_value=tools)
    monkeypatch.setattr(web, "FactoryTools", factory)
    with TestClient(app) as client:
        response = client.post("/api/operations/propose", json={"scope_key": "project001-dev", "settings": {
            "department_name": "Research", "department_id": None,
        }})
        assert response.status_code == 201 and response.json() == pending
    factory.assert_called_once()
    assert factory.call_args.args == (app.state.settings, principal, "project001-dev")
    assert factory.call_args.kwargs["operation_store"] is store
    assert callable(factory.call_args.kwargs["cost_factory"])
    tools.prepare_settings.assert_called_once_with({"settings": {"department_name": "Research", "department_id": None}})
    tools.execute.assert_not_called()
    tools.execute_operation.assert_not_called()
    store.approve.assert_not_called()
    store.execute.assert_not_called()
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/operations/propose")
    assert not inspect.iscoroutinefunction(route.endpoint)


@pytest.mark.parametrize("enabled,code", [(False, "writes_disabled"), (True, "factory_target_unconfigured")])
def test_user_proposal_blocks_missing_configuration_before_api_calls(authenticated, monkeypatch, enabled, code):
    app, _, store = authenticated
    app.state.settings = app.state.settings.model_copy(update={
        "factory": app.state.settings.factory.model_copy(update={"writes_enabled": enabled}),
    })
    factory = Mock()
    monkeypatch.setattr(web, "FactoryTools", factory)
    with TestClient(app) as client:
        response = client.post("/api/operations/propose", json={"scope_key": "project001-dev", "settings": {
            "department_name": "Research", "department_id": None,
        }})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == code
        assert "disabled" in response.text if not enabled else "identifiers" in response.text
    factory.assert_not_called()
    store.propose.assert_not_called()


def test_user_proposal_cannot_select_another_scope(proposal_enabled, monkeypatch):
    app, _, _ = proposal_enabled
    factory = Mock()
    monkeypatch.setattr(web, "FactoryTools", factory)
    with TestClient(app) as client:
        response = client.post("/api/operations/propose", json={"scope_key": "project002-dev", "settings": {
            "department_name": "Research", "department_id": None,
        }})
        assert response.status_code == 403
    factory.assert_not_called()


@pytest.mark.parametrize("retained_permission", ["config.write", "factory.read"])
def test_user_proposal_requires_both_current_scope_grants(proposal_enabled, monkeypatch, retained_permission):
    app, _, store = proposal_enabled
    current = app.state.settings
    grant = current.auth.grants[0].model_copy(update={"permissions": [retained_permission]})
    app.state.settings = current.model_copy(update={"auth": current.auth.model_copy(update={"grants": [grant]})})
    factory = Mock()
    monkeypatch.setattr(web, "FactoryTools", factory)
    with TestClient(app) as client:
        response = client.post("/api/operations/propose", json={"scope_key": "project001-dev", "settings": {
            "department_name": "Research", "department_id": None,
        }})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"
    factory.assert_not_called()
    store.approve.assert_not_called()
    store.execute.assert_not_called()


@pytest.mark.parametrize("settings_patch", [
    {"department_name": None, "department_id": None},
    {"department_name": "Research"},
    {"department_name": "Research", "department_id": None, "arbitrary_setting": "SECRET"},
    {"department_name": "SECRET" * 40, "department_id": None},
    {"department_name": "Research", "department_id": "X" * 129},
    {"department_name": "$(SECRET)", "department_id": None},
    {"department_name": "Research\nSECRET", "department_id": None},
    {"department_name": 123, "department_id": None},
])
def test_user_proposal_closed_settings_schema_and_no_input_echo(proposal_enabled, monkeypatch, settings_patch):
    app, _, _ = proposal_enabled
    factory = Mock()
    monkeypatch.setattr(web, "FactoryTools", factory)
    with TestClient(app) as client:
        response = client.post("/api/operations/propose", json={"scope_key": "project001-dev", "settings": settings_patch})
        assert response.status_code == 422
        assert "SECRET" not in response.text
    factory.assert_not_called()


def test_user_proposal_forbids_caller_targets_or_approval_fields(proposal_enabled):
    app, _, _ = proposal_enabled
    with TestClient(app) as client:
        response = client.post("/api/operations/propose", json={
            "scope_key": "project001-dev", "settings": {"department_name": "Research", "department_id": None},
            "factory_id": OPERATION_ID, "approved": True,
        })
        assert response.status_code == 422


@pytest.mark.parametrize("code,status", [
    ("forbidden", 403), ("revision_changed", 409), ("factory_timeout", 503), ("factory_api_error", 503),
])
def test_user_proposal_envelope_failures_are_http_errors_without_details(proposal_enabled, monkeypatch, code, status):
    app, _, _ = proposal_enabled
    tools = Mock(spec=web.FactoryTools)
    tools.prepare_settings.return_value = {
        "ok": False, "error": {"code": code, "message": "SECRET-FACTORY-RESPONSE", "status_code": status},
    }
    monkeypatch.setattr(web, "FactoryTools", Mock(return_value=tools))
    with TestClient(app) as client:
        response = client.post("/api/operations/propose", json={"scope_key": "project001-dev", "settings": {
            "department_name": "Research", "department_id": None,
        }})
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert "SECRET" not in response.text


def test_user_proposal_does_not_invent_success_for_started_or_invalid_result(proposal_enabled, monkeypatch):
    app, _, _ = proposal_enabled
    tools = Mock(spec=web.FactoryTools)
    tools.prepare_settings.return_value = {"ok": True, "data": {"status": "started"}}
    monkeypatch.setattr(web, "FactoryTools", Mock(return_value=tools))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/operations/propose", json={"scope_key": "project001-dev", "settings": {
            "department_name": "Research", "department_id": None,
        }})
        assert response.status_code == 500 and response.text == "Internal Server Error"


def test_execute_uses_persisted_scope_and_real_tools_interface(authenticated, principal, monkeypatch):
    app, _, store = authenticated
    record = {"id": OPERATION_ID, "status": "executing", "scope_key": "project001-dev"}
    tools = Mock()
    tools.execute_operation.return_value = {"ok": True}
    factory = Mock(return_value=tools)
    monkeypatch.setattr(web, "FactoryTools", factory)

    def execute(caller, operation_id, callback):
        assert caller is principal and operation_id == OPERATION_ID
        assert callback(record) == {"ok": True}
        return {**record, "status": "succeeded"}

    store.execute.side_effect = execute
    with TestClient(app) as client:
        response = client.post(f"/api/operations/{OPERATION_ID}/execute")
        assert response.status_code == 200 and response.json()["status"] == "succeeded"
    factory.assert_called_once()
    assert factory.call_args.args == (app.state.settings, principal, "project001-dev")
    assert factory.call_args.kwargs["operation_store"] is store
    assert callable(factory.call_args.kwargs["cost_factory"])
    tools.execute_operation.assert_called_once_with(record)
    store.approve.assert_not_called()


@pytest.mark.parametrize("code,status", [("forbidden", 403), ("plan_changed", 409), ("store_unavailable", 503)])
def test_known_operation_failures_are_not_success_or_sensitive(authenticated, code, status):
    app, _, store = authenticated
    store.approve.side_effect = OperationError(code, "DO-NOT-EXPOSE-SECRET", status)
    with TestClient(app) as client:
        response = client.post(f"/api/operations/{OPERATION_ID}/approve", json={"plan_hash": HASH})
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert "DO-NOT-EXPOSE" not in response.text


@pytest.mark.parametrize("status,code", [("failed", 403), ("failed", 409), ("uncertain", 503)])
def test_execution_failure_returns_error_status_and_persisted_record(authenticated, status, code):
    app, _, store = authenticated
    store.execute.return_value = {"id": OPERATION_ID, "status": status,
                                  "outcome": {"ok": False, "error": {"status_code": code}}}
    with TestClient(app) as client:
        response = client.post(f"/api/operations/{OPERATION_ID}/execute")
        assert response.status_code == code
        assert response.json()["operation"]["status"] == status
        assert response.json()["error"]["code"] == "operation_" + status


def test_production_store_is_blob_not_memory(settings):
    store = OperationStore(settings, cred=Mock())
    assert isinstance(store.backend, BlobOperationBackend)
    assert not isinstance(store.backend, MemoryOperationBackend)


def test_unexpected_error_is_generic_500_without_exception_body(authenticated, monkeypatch):
    app, _, _ = authenticated
    monkeypatch.setattr(web, "Conversation", Mock(return_value=Mock(answer=Mock(side_effect=RuntimeError("SECRET")))))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/chat", json={"question": "Q", "audience": "project", "scope_key": "project001-dev"})
        assert response.status_code == 500
        assert "SECRET" not in response.text
        assert response.text == "Internal Server Error"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"


def test_security_headers_csp_and_frontend_assets(isolated):
    app, _, _ = isolated
    with TestClient(app) as client:
        for path in ("/", "/api/public-config", "/api/context", "/static/app.js", "/static/theme.css",
                     "/static/markdown.js", "/static/vendor/markdown-it.min.js"):
            response = client.get(path)
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert response.headers["cache-control"] == "no-store"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
            assert "'unsafe-inline'" not in response.headers["content-security-policy"]
        html = client.get("/")
        script = re.search(r"<script>(.*?)</script>", html.text, re.S).group(1)
        digest = base64.b64encode(hashlib.sha256(script.replace("\r\n", "\n").encode()).digest()).decode()
        assert f"'sha256-{digest}'" in html.headers["content-security-policy"]
        assert "scoutTheme" in script and "prefers-color-scheme" in script
        assert "https://cdn" not in html.text
        assert html.text.index("/static/vendor/markdown-it.min.js") < html.text.index("/static/markdown.js") < html.text.index("/static/app.js")
        assert client.get("/docs").status_code == 404
        assert client.get("/static/../config.example.json").status_code == 404
    js = (web.STATIC / "app.js").read_text("utf-8")
    assert "innerHTML" not in js and "localStorage" not in js
    assert "client_secret" not in js and "offline_access" not in js
    css = (web.STATIC / "theme.css").read_text("utf-8")
    components = css[css.index("* {"):]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", components)
    assert '--cp-bg: #F7F6FA;' in css and '--cp-accent: #6750A4;' in css and '"Segoe UI"' in css


def test_frontend_javascript_syntax():
    result = subprocess.run(["node", "--check", str(web.STATIC / "app.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_frontend_confirmation_and_shortcuts_accessibility():
    html = (web.STATIC / "index.html").read_text("utf-8")
    assert 'id="question-examples"' in html and 'id="action-tiles"' in html
    assert re.search(r'<dialog[^>]+id="confirmation-dialog"[^>]+aria-labelledby="confirmation-heading"', html)
    assert 'aria-describedby="confirmation-action confirmation-description"' in html
    assert re.search(r'<button[^>]+id="confirmation-cancel"[^>]+autofocus', html)
    assert "Are you sure?" in html


@pytest.mark.parametrize("mode", [
    "blocked", "pkce", "bad-state", "authenticated", "approval", "cancel-disabled",
    "discard", "out-of-sync", "reindex", "user-proposal", "proposal-blocked", "proposal-api-unavailable",
    "skill-cost", "skill-action", "skill-delete",
    "markdown-answer",
    "question-tiles", "question-tiles-denied", "action-tiles", "action-tiles-denied",
    *[f"confirm-{action}-{scenario}" for action in (
        "prepare", "propose", "approve", "execute", "continue", "cancel", "delete",
    ) for scenario in ("consent", "scope", "signout")],
    "confirm-approve-changed", "confirm-continue-changed", "confirm-prepare-permission",
    "confirm-continue-expired", "confirm-continue-refresh",
])
def test_mocked_browser_pkce_safe_rendering_and_separate_approval(mode):
    # Node's built-in VM/crypto exercise the shipped script; all HTTP/DOM objects are unit-test mocks.
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const {webcrypto, createHash} = require("node:crypto");
const mode = process.argv[3];
const confirmationAction = mode.startsWith("confirm-") ? mode.split("-")[1] : null;
const confirmationScenario = mode.startsWith("confirm-") ? mode.split("-")[2] : null;
const clientId = "11111111-1111-4111-8111-111111111111";
const config = {
  tenant_id: "44444444-4444-4444-8444-444444444444",
  client_id: mode === "blocked" ? null : clientId,
  audience: mode === "blocked" ? null : "api://" + clientId,
  required_scope: "access_as_user",
};
const elements = new Map();
class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.handlers = {};
    this._text = "";
    this.value = "";
    this.disabled = false;
    this.dataset = {};
    this.checked = false;
    this.open = false;
    this.isConnected = true;
    this.showCount = 0;
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  set id(value) { this._id = value; elements.set(value, this); }
  get id() { return this._id; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this._text = ""; this.children = items; }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
  focus() { sandbox.document.activeElement = this; }
  scrollIntoView() {}
  showModal() { assert.equal(this.open, false); this.open = true; this.showCount++; }
  close() { this.open = false; this.handlers.close?.({}); }
}
class TextNode {
  constructor(value) { this.tagName = "#text"; this.children = []; this.textContent = String(value); }
}
function ui(id) {
  if (!elements.has(id)) { const element = new Element("div"); element.id = id; }
  return elements.get(id);
}
ui("sign-in").disabled = true;
const callbackMode = !["blocked", "pkce"].includes(mode);
let current = new URL("https://factory.example/" + (callbackMode
  ? "?code=UNIT_TEST_CODE&state=" + (mode === "bad-state" ? "invalid" : "expected")
  : mode === "pkce" ? "#scope=project001-dev&view=platform" : ""));
let assigned;
const historyCalls = [];
const location = {
  get origin() { return current.origin; }, get pathname() { return current.pathname; },
  get search() { return current.search; }, get hash() { return current.hash; },
  assign(url) { assigned = url; },
};
const storage = new Map(callbackMode
  ? [["aifactory.oauth.state", "expected"], ["aifactory.oauth.verifier", "v".repeat(43)]] : []);
const calls = [];
let operationStatus = confirmationAction === "execute" ? "approved"
  : confirmationAction === "continue" ? "awaiting_continuation" : "pending";
let operationUpdatedAt = "2026-10-03T18:00:00Z";
let proposalCreated = false;
let resolveLate;
const hash = "a".repeat(64);
const operationId = "33333333-3333-4333-8333-333333333333";
const operation = () => ({
  id: operationId, correlation_id: operationId, tool_name: mode === "skill-delete" || confirmationAction === "delete" ? "delete-aifactory"
    : confirmationAction === "continue" ? "create-private-aifactory-full-bootstrap-private-with-own-hub-vpn-and-default-proj"
    : mode === "skill-action" ? "add-project-to-aifactory" : "factory_prepare_settings",
  scope_key: "project001-dev", scope: {factory: "factory", project: "001", environment: "dev"},
  factory_api_url: "https://factory-api.example",
  request: {settings: {department_name: "Research"}},
  preview: {can_execute: true, effects: "<img src=x onerror=steal()>",
    ...(mode === "skill-delete" || confirmationAction === "delete" ? {confirmation_phrase: "DELETE factory-ai"} : {})},
  affected_resources: ["exact-resource-id"], created_at: "2026-10-03",
  expires_at: confirmationScenario === "expired" ? "2026-10-03" : "2099-10-04",
  updated_at: operationUpdatedAt, signature: operationUpdatedAt,
  status: operationStatus, plan_hash: hash, progress: {phase: operationStatus,
    continuation_allowed: true, observation_hash: "b".repeat(64)},
});
const context = {
  scopes: [{key: "project001-dev", label: "factory / 001 / dev",
    scope: {factory: "factory", project: "001", environment: "dev", tenant_id: config.tenant_id,
      subscription_id: clientId, resource_group: "project-rg"},
    permissions: ["knowledge.read", "factory.read", "config.write", "project.add", "factory.delete", "cost.read",
      "factory.create", "agent.create", "model.create"].filter(permission =>
        !(mode === "question-tiles-denied" && permission === "knowledge.read")
        && !(mode === "action-tiles-denied" && permission === "model.create"))}],
  settings: {writes_enabled: !["cancel-disabled", "proposal-blocked"].includes(mode)},
  capabilities: {
    model_read_only: true, proposal_creation: true,
    skills_supported: mode.startsWith("skill-") || mode.startsWith("action-tiles") || confirmationAction === "prepare",
    proposal_blockers: mode === "proposal-blocked" ? ["writes_disabled", "factory_target_unconfigured"] : [],
  },
};
context.scopes.push({...context.scopes[0], key: "project002-dev", label: "factory / 002 / dev",
  scope: {...context.scopes[0].scope, project: "002", resource_group: "other-rg"}});
const skill = {
  name: mode === "skill-cost" ? "get-aifactory-common-estimated-azure-idle-running-cost" : "add-project-to-aifactory",
  command: "/skill", label: "Factory skill",
  kind: mode === "skill-cost" ? "monitoring" : "action", available: true, blockers: [],
  permission: mode === "skill-cost" ? "cost.read" : "project.add",
  arguments_schema: {type: "object", additionalProperties: false,
    properties: mode === "skill-cost" ? {resource_group: {type: "string", title: "Resource group"}}
      : {project_number: {type: "string"}, display_name: {type: "string"}},
    required: mode === "skill-cost" ? ["resource_group"] : ["project_number", "display_name"]},
};
const tileSkills = [
  ["create-private-aifactory-full-bootstrap-private-with-own-hub-vpn-and-default-proj", "factory.create"],
  ["add-project-to-aifactory", "project.add"], ["delete-aifactory", "factory.delete"],
  ["create-agent-oftype-for-project", "agent.create"], ["create-ml-model-oftype-for-project", "model.create"],
].map(([name, permission]) => ({...skill, name, permission, label: name,
  available: !(mode === "action-tiles-denied" && name === "delete-aifactory"),
  blockers: name === "delete-aifactory" ? ["skill_disabled"] : []}));
const answer = {
  answer: mode === "markdown-answer"
    ? '## Heading\n\n**Bold** and *emphasis*. [S1]\n\n- Item\n\n1. First\n\n```python\nprint("<img src=x onerror=steal()>")\n```\n\n| A | B |\n| --- | --- |\n| One | Two |'
    : '<img src=x onerror="steal()"> [S1]', scope_key: "project001-dev", audience: "project",
  correlation_id: operationId, tool_activity: [],
  citations: [{citation_id: "S1", heading: "<script>bad</script>", is_history: true,
    source_type: "release_note", source_url: "javascript:steal()", version: "1.2"}],
};
const response = (data) => ({ok: true, status: 200, json: async () => data});
const sandbox = {
  document: {getElementById: ui, createElement: (tag) => new Element(tag), createTextNode: (text) => new TextNode(text)},
  location, history: {replaceState(_, __, url) { historyCalls.push(url); current = new URL(url, current); }},
  crypto: webcrypto, isSecureContext: true, URL, URLSearchParams, TextEncoder, TextDecoder,
  sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key)},
  btoa: value => Buffer.from(value, "binary").toString("base64"),
  atob: value => Buffer.from(value, "base64").toString("binary"),
  setInterval: () => 1,
  fetch: async (url, options = {}) => {
    calls.push({url, options, body: options.body ? String(options.body) : null, location: current.href});
    if (url === "/api/public-config") return response(config);
    if (url.endsWith("/oauth2/v2.0/token")) return response({
      token_type: "Bearer", access_token: "UNIT_TEST_ACCESS_TOKEN", expires_in: 3600,
    });
    if (url === "/api/context") return response(context);
    if (url.startsWith("/api/skills?")) return response({scope_key: "project001-dev",
      skills: mode.startsWith("action-tiles") ? tileSkills : [skill]});
    if (url.startsWith("/api/skills/") && url.endsWith("/run")) {
      return response({ok: true, data: {basis: "actual", source: "Cost Analysis", coverage: "partial"}});
    }
    if (url.startsWith("/api/skills/") && url.endsWith("/propose")) {
      proposalCreated = true;
      return response(operation());
    }
    if (url.startsWith("/api/knowledge/status")) return response({
      status: {
        status: mode === "out-of-sync" ? "index_out_of_sync" : mode === "reindex" ? "reindex_required" : "ready",
        stale: false, indexed_document_count: 10, reconciliation_pending: false,
        search_document_count: mode === "out-of-sync" ? 9 : 10,
      },
    });
    if (url === "/api/operations") return response({
      operations: ["approval", "cancel-disabled", "skill-delete"].includes(mode) || proposalCreated
        || confirmationAction && !["prepare", "propose"].includes(confirmationAction) ? [operation()] : [],
    });
    if (url === "/api/operations/propose") {
      if (mode === "proposal-api-unavailable") return {ok: false, status: 503, json: async () => ({
        error: {code: "factory_api_error", message: "SECRET-FACTORY-RESPONSE"},
      })};
      proposalCreated = true;
      operationStatus = "pending";
      return response(operation());
    }
    if (url === "/api/chat") {
      if (mode === "discard") return new Promise(resolve => { resolveLate = () => resolve(response(answer)); });
      return response(answer);
    }
    if (url.endsWith("/approve")) { operationStatus = "approved"; return response(operation()); }
    if (url.endsWith("/execute")) { operationStatus = "executing"; return response(operation()); }
    if (url.endsWith("/cancel")) { operationStatus = "cancelled"; return response(operation()); }
    if (url.endsWith("/continue")) { operationStatus = "continuing"; return response(operation()); }
    if (url.endsWith("/status")) return response(operation());
    throw new Error("Unexpected mock request: " + url);
  },
};
sandbox.window = sandbox;
const browserContext = vm.createContext(sandbox);
const path = require("node:path");
const assets = path.dirname(process.argv[2]);
for (const asset of ["vendor/markdown-it.min.js", "markdown.js", "app.js"]) {
  vm.runInContext(fs.readFileSync(path.join(assets, asset), "utf8"), browserContext);
}
async function waitFor(predicate) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw new Error("Mock browser condition did not complete");
}
async function dispatch(element, name, extra = {}) {
  await element.handlers[name]({preventDefault() {}, ...extra});
}
function descendants(element) {
  return element.children.flatMap(child => [child, ...descendants(child)]);
}
const writes = () => calls.filter(call => call.options.method === "POST" && call.url !== "/api/chat"
  && !call.url.endsWith("/oauth2/v2.0/token"));
async function consent() {
  await waitFor(() => ui("confirmation-dialog").open);
  await dispatch(ui("confirmation-accept"), "click");
}
(async () => {
  await waitFor(() => calls.length && (ui("sign-in").disabled === false || mode === "blocked"
    || ui("error-message").textContent.includes("state verification")));
  if (mode === "blocked") {
    assert.equal(ui("sign-in").disabled, true);
    assert.equal(ui("propose").disabled, true);
    await waitFor(() => ui("setup-message").textContent.includes("tokens cannot be pasted"));
    assert.equal(calls.length, 1);
  } else if (mode === "pkce") {
    await dispatch(ui("sign-in"), "click");
    await waitFor(() => assigned);
    const url = new URL(assigned);
    assert.equal(url.hostname, "login.microsoftonline.com");
    assert.equal(url.searchParams.get("redirect_uri"), "https://factory.example/");
    assert.equal(url.searchParams.get("scope"), "api://" + clientId + "/access_as_user");
    assert.equal(url.searchParams.get("response_type"), "code");
    assert.equal(url.searchParams.get("code_challenge_method"), "S256");
    assert.equal(url.searchParams.get("state"), storage.get("aifactory.oauth.state"));
    assert.equal(url.searchParams.get("state").split(".").slice(1).join("."), "platform.project001-dev");
    assert.equal(url.searchParams.get("code_challenge"), createHash("sha256")
      .update(storage.get("aifactory.oauth.verifier")).digest("base64url"));
    assert.deepEqual([...storage.keys()].sort(), ["aifactory.oauth.state", "aifactory.oauth.verifier"]);
    assert.equal(url.searchParams.has("client_secret"), false);
  } else if (mode === "bad-state") {
    assert.equal(calls.length, 1);
    assert.equal(storage.size, 0);
    assert(!current.search.includes("code"));
    assert(!calls[0].location.includes("code"));
  } else {
    await waitFor(() => calls.some(call => call.url === "/api/operations") && !ui("scope-selector").disabled);
    assert.equal(storage.size, 0);
    assert(!current.search.includes("code"));
    assert(!calls[0].location.includes("code"));
    const exchange = calls.find(call => call.url.endsWith("/oauth2/v2.0/token"));
    const exchangeBody = new URLSearchParams(exchange.body);
    assert.equal(exchangeBody.get("code"), "UNIT_TEST_CODE");
    assert.equal(exchangeBody.get("code_verifier"), "v".repeat(43));
    assert.equal(exchangeBody.get("redirect_uri"), "https://factory.example/");
    assert.equal(exchangeBody.has("client_secret"), false);
    assert(calls.filter(call => call.url.startsWith("/api/") && call.url !== "/api/public-config")
      .every(call => call.options.headers.Authorization === "Bearer UNIT_TEST_ACCESS_TOKEN"));
    if (mode.startsWith("question-tiles")) {
      const tiles = descendants(ui("question-examples")).filter(child => child.tagName === "button");
      assert.equal(tiles.length, 6);
      const labels = tiles.map(tile => tile.textContent).join(" ");
      for (const topic of ["Private", "Onboarding", "Project team", "Updates", "idle", "ML template"])
        assert(labels.includes(topic), topic);
      const before = calls.length;
      for (const tile of tiles) {
        assert.equal(tile.disabled, mode === "question-tiles-denied");
        await dispatch(tile, "click");
        if (tile.disabled) { assert.equal(ui("question").value, ""); continue; }
        assert(ui("question").value.includes("active scope"));
        assert.equal(ui("question-count").textContent, ui("question").value.length + " / 8000 characters");
        assert.equal(sandbox.document.activeElement, ui("question"));
        assert.equal(ui("ask").disabled, false);
      }
      assert.equal(calls.length, before, "example questions must never submit automatically");
      assert.equal(ui("confirmation-dialog").open, false);
    } else if (mode.startsWith("action-tiles")) {
      await waitFor(() => calls.some(call => call.url.startsWith("/api/skills?")));
      const tiles = descendants(ui("action-tiles")).filter(child => child.tagName === "button");
      const actionTiles = tiles.filter(tile => tile.dataset.skill && tileSkills.some(skill => skill.name === tile.dataset.skill));
      assert.equal(actionTiles.length, 5);
      const before = calls.length;
      for (const tile of actionTiles) {
        const blocked = mode === "action-tiles-denied"
          && ["delete-aifactory", "create-ml-model-oftype-for-project"].includes(tile.dataset.skill);
        assert.equal(tile.disabled, blocked);
        const previous = ui("skill-selector").value;
        tile.focus();
        await dispatch(tile, "click");
        if (blocked) { assert.equal(ui("confirmation-dialog").open, false); continue; }
        assert.equal(ui("confirmation-dialog").open, true);
        assert.equal(ui("skill-selector").value, previous, "selection waits for explicit consent");
        assert(ui("confirmation-description").textContent.includes("no request"));
        await dispatch(ui("confirmation-cancel"), "click");
        assert.equal(ui("skill-selector").value, previous);
        assert.equal(sandbox.document.activeElement, tile);
        await dispatch(tile, "click");
        await consent();
        await waitFor(() => ui("skill-selector").value === tile.dataset.skill);
        assert.equal(sandbox.document.activeElement, ui("skill-selector"));
        assert.equal(ui("run-skill").disabled, false);
      }
      assert.equal(calls.length, before, "action tiles only select the existing preparation form");
      for (const tile of tiles.filter(tile => !tileSkills.some(skill => skill.name === tile.dataset.skill)))
        assert.equal(tile.disabled, true, "missing registry skills stay disabled");
    } else if (confirmationAction) {
      await waitFor(() => !ui("refresh-status").disabled);
      let launch, trigger, expectedPath, actionLabel;
      if (confirmationAction === "prepare") {
        ui("skill-selector").value = skill.name;
        await dispatch(ui("skill-selector"), "change");
        ui("skill-arg-project_number").value = "002";
        ui("skill-arg-display_name").value = "<img src=x onerror=steal()>";
        trigger = ui("run-skill");
        launch = () => dispatch(ui("skill-form"), "submit");
        expectedPath = "/api/skills/" + skill.name + "/propose";
        actionLabel = "Prepare plan · do not execute";
      } else if (confirmationAction === "propose") {
        ui("department-name").value = "<img src=x onerror=steal()>";
        await dispatch(ui("department-name"), "input");
        trigger = ui("propose");
        launch = () => dispatch(ui("proposal-form"), "submit");
        expectedPath = "/api/operations/propose";
        actionLabel = "Propose metadata plan · do not execute";
      } else {
        const container = confirmationAction === "continue" ? ui("operation-history") : ui("proposed-plans");
        if (["approve", "delete"].includes(confirmationAction)) {
          const form = descendants(container).find(child => child.tagName === "form");
          ui("hash-" + operationId).value = hash;
          await dispatch(ui("hash-" + operationId), "input");
          if (confirmationAction === "delete") {
            assert.equal(descendants(form).find(child => child.tagName === "button").disabled, true);
            ui("phrase-" + operationId).value = "DELETE factory-ai";
            await dispatch(ui("phrase-" + operationId), "input");
          }
          trigger = descendants(form).find(child => child.tagName === "button");
          launch = () => dispatch(form, "submit");
          actionLabel = "Approve this exact plan";
        } else {
          const starts = {execute: "Execute approved", continue: "Continue this", cancel: "Cancel unexecuted"};
          trigger = descendants(container).find(child => child.tagName === "button"
            && child.textContent.startsWith(starts[confirmationAction]));
          launch = () => dispatch(trigger, "click");
          actionLabel = trigger.textContent;
        }
        expectedPath = "/api/operations/" + operationId + "/" + (confirmationAction === "delete" ? "approve" : confirmationAction);
      }
      const initialWrites = writes().length;
      trigger.focus();
      await launch();
      assert.equal(ui("confirmation-dialog").open, true);
      assert.equal(writes().length, initialWrites, "no write before consent");
      assert.equal(sandbox.document.activeElement, ui("confirmation-cancel"), "Cancel is the default focus");
      assert.equal(ui("confirmation-action").textContent, actionLabel);
      const review = ui("confirmation-details").textContent;
      assert(review.includes("project001-dev") && review.includes("project-rg"));
      assert(review.includes(expectedPath), "exact request endpoint is reviewed");
      if (["approve", "execute", "continue", "cancel", "delete"].includes(confirmationAction)) {
        for (const exact of [hash, "https://factory-api.example", "Research", operation().expires_at, "exact-resource-id", operationId])
          assert(review.includes(exact), exact);
      }
      assert.equal(descendants(ui("confirmation-details")).some(child => ["img", "script"].includes(child.tagName)), false);
      const shows = ui("confirmation-dialog").showCount;
      await launch();
      assert.equal(ui("confirmation-dialog").showCount, shows, "only one confirmation can be pending");
      await dispatch(ui("confirmation-cancel"), "click");
      assert.equal(writes().length, initialWrites);
      assert.equal(sandbox.document.activeElement, trigger);
      assert.equal(trigger.disabled, false);
      await launch();
      await dispatch(ui("confirmation-dialog"), "cancel");
      assert.equal(ui("confirmation-dialog").open, false, "Escape dismisses without consenting");
      assert.equal(writes().length, initialWrites);
      await launch();
      if (confirmationScenario === "scope") {
        ui("scope-selector").value = "project002-dev";
        await dispatch(ui("scope-selector"), "change");
        ui("scope-selector").value = "project001-dev";
        await dispatch(ui("scope-selector"), "change");
        assert.equal(ui("confirmation-dialog").open, false, "even switching away and back invalidates consent");
        await dispatch(ui("confirmation-accept"), "click");
      } else if (confirmationScenario === "signout") {
        await dispatch(ui("sign-out"), "click");
        assert.equal(ui("confirmation-dialog").open, false);
        await dispatch(ui("confirmation-accept"), "click");
      } else if (confirmationScenario === "changed") {
        operationStatus = "cancelled";
        await dispatch(ui("refresh-status"), "click");
        await waitFor(() => ui("operation-history").textContent.includes("Cancelled plan"));
        await consent();
      } else if (confirmationScenario === "permission") {
        context.scopes[0].permissions = context.scopes[0].permissions.filter(permission => permission !== "project.add");
        await consent();
      } else {
        if (confirmationScenario === "refresh") {
          operationUpdatedAt = "2026-10-03T18:00:10Z";
          await dispatch(ui("refresh-status"), "click");
          await waitFor(() => ui("confirmation-accept").disabled === false);
          await new Promise(resolve => setTimeout(resolve, 20));
        }
        await consent();
        await waitFor(() => writes().length === initialWrites + 1);
        const submitted = writes().at(-1);
        assert.equal(submitted.url, expectedPath);
        if (confirmationAction === "delete") assert.deepEqual(JSON.parse(submitted.body),
          {plan_hash: hash, confirmation_phrase: "DELETE factory-ai"});
        if (confirmationAction === "continue") assert.deepEqual(JSON.parse(submitted.body),
          {plan_hash: hash, observation_hash: "b".repeat(64)});
        if (confirmationAction === "prepare") assert.deepEqual(JSON.parse(submitted.body).arguments,
          {project_number: "002", display_name: "<img src=x onerror=steal()>"});
        if (["prepare", "propose"].includes(confirmationAction)) {
          assert.equal(JSON.parse(submitted.body).scope_key, "project001-dev");
          assert(!writes().some(call => call.url.endsWith("/execute") || call.url.endsWith("/approve")));
        }
        await dispatch(ui("confirmation-accept"), "click");
        assert.equal(writes().length, initialWrites + 1, "double consent never replays a write");
      }
      if (!["consent", "expired", "refresh"].includes(confirmationScenario)) {
        await new Promise(resolve => setTimeout(resolve, 20));
        assert.equal(writes().length, initialWrites, "stale session, scope, plan or permission must fail closed");
      }
    } else if (["skill-cost", "skill-action"].includes(mode)) {
      await waitFor(() => calls.some(call => call.url.startsWith("/api/skills?")));
      ui("skill-selector").value = skill.name;
      await dispatch(ui("skill-selector"), "change");
      if (mode === "skill-cost") ui("skill-arg-resource_group").value = "common-rg";
      else {
        ui("skill-arg-project_number").value = "002";
        ui("skill-arg-display_name").value = "Research";
      }
      await dispatch(ui("skill-form"), "submit");
      if (mode === "skill-action") await consent();
      await waitFor(() => calls.some(call => call.url.startsWith("/api/skills/") && call.options.method === "POST"));
      const submitted = calls.find(call => call.url.startsWith("/api/skills/") && call.options.method === "POST");
      assert(submitted.url.endsWith(mode === "skill-cost" ? "/run" : "/propose"));
      assert.equal(JSON.parse(submitted.body).scope_key, "project001-dev");
      if (mode === "skill-cost") await waitFor(() => ui("skill-result").textContent.includes("Cost Analysis"));
      else await waitFor(() => ui("proposed-plans").textContent.includes("Pending review"));
      assert(!calls.some(call => call.url.endsWith("/approve") || call.url.endsWith("/execute")));
    } else if (mode === "skill-delete") {
      await waitFor(() => ui("proposed-plans").textContent.includes("DELETE factory-ai"));
      const form = descendants(ui("proposed-plans")).find(child => child.tagName === "form");
      const hashInput = ui("hash-" + operationId);
      const phraseInput = ui("phrase-" + operationId);
      const approve = descendants(form).find(child => child.tagName === "button");
      hashInput.value = hash;
      await dispatch(hashInput, "input");
      assert.equal(approve.disabled, true);
      phraseInput.value = "WRONG";
      await dispatch(phraseInput, "input");
      assert.equal(approve.disabled, true);
      phraseInput.value = "DELETE factory-ai";
      await dispatch(phraseInput, "input");
      assert.equal(approve.disabled, false);
      await dispatch(form, "submit");
      await consent();
      await waitFor(() => calls.some(call => call.url.endsWith("/approve")));
      assert.deepEqual(JSON.parse(calls.find(call => call.url.endsWith("/approve")).body),
        {plan_hash: hash, confirmation_phrase: "DELETE factory-ai"});
      assert(!calls.some(call => call.url.endsWith("/execute")));
    } else if (mode === "proposal-blocked") {
      assert.equal(ui("propose").disabled, true);
      assert.equal(ui("department-name").disabled, true);
      assert(ui("proposal-status").textContent.includes("configuration writes are disabled"));
      assert(ui("proposal-status").textContent.includes("identifiers are not configured"));
      await dispatch(ui("proposal-form"), "submit");
      assert(!calls.some(call => call.url === "/api/operations/propose"));
    } else if (["user-proposal", "proposal-api-unavailable"].includes(mode)) {
      ui("department-name").value = "Research";
      ui("department-id").value = "R001";
      await dispatch(ui("department-name"), "input");
      assert.equal(ui("propose").disabled, false);
      await dispatch(ui("proposal-form"), "submit");
      await consent();
      if (mode === "proposal-api-unavailable") {
        await waitFor(() => ui("error-message").textContent.includes("existing Factory API request failed"));
        assert(!ui("error-message").textContent.includes("SECRET"));
        assert(ui("proposal-status").textContent.includes("No new pending plan confirmed"));
      } else {
        await waitFor(() => ui("proposal-status").textContent.includes("Pending plan created"));
        assert(ui("proposed-plans").textContent.includes("Pending review"));
        assert(ui("proposal-status").textContent.includes("not approved or executed"));
        const request = calls.find(call => call.url === "/api/operations/propose");
        assert.deepEqual(JSON.parse(request.body), {scope_key: "project001-dev", settings: {
          department_name: "Research", department_id: "R001",
        }});
      }
      assert.equal(calls.filter(call => call.url === "/api/operations/propose").length, 1);
      assert(!calls.some(call => call.url.endsWith("/approve") || call.url.endsWith("/execute")));
    } else if (["out-of-sync", "reindex"].includes(mode)) {
      const expected = mode === "out-of-sync" ? "Search differs from manifest" : "Index changed";
      await waitFor(() => ui("knowledge-status").textContent.includes(expected));
      assert(!ui("knowledge-status").textContent.includes("Knowledge ready"));
      assert(ui("knowledge-status").textContent.includes("approved operator"));
      if (mode === "out-of-sync") assert(ui("knowledge-status").textContent.includes("Search confirms: 9"));
    } else if (mode === "cancel-disabled") {
      await waitFor(() => ui("proposed-plans").textContent.includes("Configuration writes are disabled"));
      assert(!ui("proposed-plans").textContent.includes("Approve this exact"));
      assert(!ui("proposed-plans").textContent.includes("Execute approved"));
      const cancel = descendants(ui("proposed-plans")).find(child =>
        child.tagName === "button" && child.textContent.includes("Cancel unexecuted"));
      await dispatch(cancel, "click");
      await consent();
      await waitFor(() => ui("operation-history").textContent.includes("Cancelled plan"));
      assert(!calls.some(call => call.url.endsWith("/execute") || call.url.endsWith("/approve")));
    } else if (mode === "approval") {
      await waitFor(() => descendants(ui("proposed-plans")).some(child => child.tagName === "form"));
      assert(ui("proposed-plans").textContent.includes("https://factory-api.example"));
      const form = descendants(ui("proposed-plans")).find(child => child.tagName === "form");
      const input = descendants(form).find(child => child.tagName === "input");
      const approve = descendants(form).find(child => child.tagName === "button");
      assert.equal(approve.disabled, true);
      input.value = hash;
      await dispatch(input, "input");
      assert.equal(approve.disabled, false);
      await dispatch(form, "submit");
      await consent();
      await waitFor(() => ui("proposed-plans").textContent.includes("Execute approved metadata"));
      const approval = calls.find(call => call.url.endsWith("/approve"));
      assert.deepEqual(JSON.parse(approval.body), {plan_hash: hash});
      assert(!calls.some(call => call.url.endsWith("/execute")));
      const execute = descendants(ui("proposed-plans")).find(child =>
        child.tagName === "button" && child.textContent.includes("Execute approved"));
      await dispatch(execute, "click");
      await consent();
      await waitFor(() => ui("operation-history").textContent.includes("Executing — completion not confirmed"));
      assert(!ui("operation-history").textContent.includes("Succeeded"));
    } else {
      ui("question").value = "A scoped question";
      await dispatch(ui("question"), "input");
      await dispatch(ui("question-form"), "submit");
      if (mode === "discard") {
        await waitFor(() => resolveLate);
        await dispatch(ui("sign-out"), "click");
        resolveLate();
        await waitFor(() => ui("error-message").textContent.includes("response was discarded"));
        assert(!ui("answer").textContent.includes("steal"));
        assert.equal(ui("question").value, "");
      } else {
        await waitFor(() => ui("answer").textContent.includes("steal"));
        assert(ui("answer").children.length > 0, "answer must be rendered into Markdown elements");
        assert(!descendants(ui("answer")).some(child => ["img", "script", "iframe"].includes(child.tagName)));
        assert(descendants(ui("answer")).some(child => child.tagName === "a" && child.href === "#source-S1"));
        if (mode === "markdown-answer") {
          for (const tag of ["h2", "strong", "em", "ul", "ol", "pre", "code", "table", "th", "td"]) {
            assert(descendants(ui("answer")).some(child => child.tagName === tag), "missing Markdown element: " + tag);
          }
          assert(!ui("answer").textContent.includes("## Heading") && !ui("answer").textContent.includes("**Bold**"));
        } else assert.equal(ui("answer").textContent, answer.answer);
        assert(ui("citations").textContent.includes("HISTORICAL RELEASE NOTE"));
        assert(!descendants(ui("citations")).some(child => child.tagName === "a"));
        assert.equal(ui("source-S1").tagName, "li");
      }
    }
    assert(![...elements.values()].some(element => element.textContent.includes("UNIT_TEST_ACCESS_TOKEN")));
  }
  console.log("Mocked browser behavior passed: " + mode);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        ["node", "-", str(web.STATIC / "app.js"), mode], input=script,
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr


EMBEDDED_HOST_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const assert = require("node:assert/strict");
const {webcrypto} = require("node:crypto");
const mode = process.argv[3];
const tenant = "44444444-4444-4444-8444-444444444444";
const clientId = "11111111-1111-4111-8111-111111111111";
const userA = "22222222-2222-4222-8222-222222222222";
const userB = "33333333-3333-4333-8333-333333333333";
const jwt = (name) => "eyJhbGciOiJSUzI1NiJ9." + Buffer.from(JSON.stringify({sub: name})).toString("base64url") + ".c2lnbmF0dXJl";
const TOKEN_A = jwt("first"), TOKEN_B = jwt("renewed");
const renewModes = ["host-renew-same", "host-renew-switch", "host-renew-transient", "host-renew-invalid", "host-renew-401"];
const issuance = (number) => "IssuanceIdentifier_" + String(number).padStart(4, "0");
const elements = new Map();
class Element {
  constructor(tag) { Object.assign(this, {tagName: tag, children: [], handlers: {}, _text: "", value: "",
    disabled: false, hidden: false, dataset: {}, open: false, isConnected: true}); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  set id(value) { this._id = value; elements.set(value, this); }
  get id() { return this._id; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this._text = ""; this.children = items; }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
  focus() {}
  scrollIntoView() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
}
class TextNode { constructor(value) { this.tagName = "#text"; this.children = []; this.textContent = String(value); } }
function ui(id) {
  if (!elements.has(id)) { const element = new Element("div"); element.id = id; }
  return elements.get(id);
}
ui("sign-in").textContent = "Sign in with Microsoft";
ui("sign-in").disabled = true;
const current = new URL("https://factory.example/?host=esaif-maui&scoutTheme=dark");
let assigned = null;
const storageWrites = [];
const requests = [];
const statuses = [];
const calls = [];
let listener = null;
let issued = 0;
let contexts = 0;
let offset = 0;
let releaseChat = null;
const rejections = [];
class FakeDate extends Date { static now() { return Date.now() + offset; } }
const now = () => Math.floor(Date.now() / 1000);
function hostReply(request) {
  issued += 1;
  if (mode === "host-error" && issued === 1)
    return {type: "esaif.agentChat.tokenError", version: 1, requestId: request.requestId, code: "signin_required",
      message: "Use Login to Azure in the app for tenant " + tenant + "."};
  if (mode === "host-foreign" && issued === 1)
    return {type: "esaif.agentChat.token", version: 1, requestId: request.requestId, accessToken: "not a jwt", expiresOn: now() + 3600};
  const renew = request.reason === "renew";
  const short = renewModes.includes(mode) && !renew;
  return {type: "esaif.agentChat.token", version: 1, requestId: request.requestId,
    accessToken: renew ? TOKEN_B : TOKEN_A, expiresOn: now() + (short ? 180 : 3600), account: "user@contoso.example",
    issuanceId: issuance(issued)};
}
const channel = {
  addEventListener(name, callback) { assert.equal(name, "message"); listener = callback; },
  postMessage(message) {
    const copy = JSON.parse(JSON.stringify(message));
    if (copy.type === "esaif.agentChat.status") { statuses.push(copy); return; }
    if (copy.type === "esaif.agentChat.tokenRejected") {
      assert.equal(Object.keys(copy).sort().join(), "issuanceId,type,version");
      rejections.push(copy.issuanceId);
      return;
    }
    requests.push(copy);
    setTimeout(() => {
      if (mode === "host-foreign") listener({data: {type: "esaif.agentChat.token", version: 1, requestId: "other-request-0000000000",
        accessToken: jwt("foreign"), expiresOn: now() + 3600}});
      listener({data: hostReply(message)});
    }, 1);
  },
};
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const context = (token) => ({
  principal: {tenant_id: tenant, object_id: mode === "host-renew-switch" && token === TOKEN_B ? userB : userA},
  scopes: [{key: "project001-dev", label: "factory / 001 / dev",
    scope: {factory: "factory", project: "001", environment: "dev", tenant_id: tenant,
      subscription_id: clientId, resource_group: "project-rg"},
    permissions: ["knowledge.read", "factory.read"]}],
  settings: {writes_enabled: false}, capabilities: {model_read_only: true, proposal_creation: true,
    proposal_blockers: ["writes_disabled"], skills_supported: false},
});
const sandbox = {
  document: {getElementById: ui, createElement: (tag) => new Element(tag), createTextNode: (text) => new TextNode(text),
    documentElement: new Element("html")},
  location: {get origin() { return current.origin; }, get pathname() { return current.pathname; },
    get search() { return current.search; }, get hash() { return current.hash; }, assign(url) { assigned = url; }},
  history: {replaceState(_, __, url) { Object.assign(current, {hash: new URL(url, current).hash}); }},
  crypto: webcrypto, isSecureContext: true, URL, URLSearchParams, TextEncoder, TextDecoder,
  sessionStorage: {getItem: () => null, setItem: (key) => storageWrites.push(key), removeItem: () => {}},
  btoa: value => Buffer.from(value, "binary").toString("base64"),
  atob: value => Buffer.from(value, "base64").toString("binary"),
  setInterval: () => 1, setTimeout, clearTimeout, Date: FakeDate,
  fetch: async (url, options = {}) => {
    const authorization = options.headers?.Authorization || null;
    calls.push({url, method: options.method || "GET", authorization});
    if (url === "/api/public-config") return response({tenant_id: tenant, client_id: clientId,
      audience: clientId, required_scope: "access_as_user"});
    if (url.includes("login.microsoftonline.com")) throw new Error("Embedded mode must not call Microsoft sign-in");
    if (url === "/api/context") {
      contexts += 1;
      if (mode === "host-bad-context" && contexts === 1) return response({});
      if (mode === "host-initial-401" && contexts === 1) return response({error: {code: "authentication_required"}}, 401);
      if (authorization === "Bearer " + TOKEN_B && mode === "host-renew-invalid") return response({principal: context(TOKEN_B).principal});
      if (authorization === "Bearer " + TOKEN_B && mode === "host-renew-transient") return response({error: {code: "dependency_unavailable"}}, 503);
      if (authorization === "Bearer " + TOKEN_B && mode === "host-renew-401") return response({error: {code: "authentication_required"}}, 401);
      return response(context(authorization?.slice(7)));
    }
    if (url === "/api/operations") return response({operations: []});
    if (url.startsWith("/api/knowledge/status")) return response({status: {status: "ready", stale: false,
      indexed_document_count: 3, reconciliation_pending: false, search_document_count: 3}});
    if (url === "/api/chat") {
      if (mode === "host-401") return response({error: {code: "authentication_required"}}, 401);
      if (mode === "host-401-text") return {ok: false, status: 401, json: async () => { throw new SyntaxError("Unauthorized"); }};
      if (mode === "host-stale-401") return new Promise(resolve => {
        releaseChat = () => resolve(response({error: {code: "authentication_required"}}, 401));
      });
      return response({answer: "Embedded answer", scope_key: "project001-dev", audience: "project",
        correlation_id: "c", tool_activity: [], citations: []});
    }
    throw new Error("Unexpected mock request: " + url);
  },
};
if (mode !== "host-absent") sandbox.chrome = {webview: channel};
sandbox.window = sandbox;
const browserContext = vm.createContext(sandbox);
const assets = path.dirname(process.argv[2]);
for (const asset of ["vendor/markdown-it.min.js", "markdown.js", "app.js"]) {
  vm.runInContext(fs.readFileSync(path.join(assets, asset), "utf8"), browserContext);
}
async function waitFor(predicate, label) {
  for (let attempt = 0; attempt < 200; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw new Error("Condition did not complete: " + label);
}
const apiCalls = () => calls.filter(call => call.url.startsWith("/api/") && call.url !== "/api/public-config");
const states = () => statuses.map(status => status.state);
async function ask() {
  ui("question").value = "A scoped question";
  await ui("question").handlers.input({});
  await ui("question-form").handlers.submit({preventDefault() {}});
}
(async () => {
  if (mode === "host-absent") {
    await waitFor(() => ui("sign-in").disabled === false, "browser sign-in enabled");
    assert.equal(ui("sign-in").textContent, "Sign in with Microsoft");
    await ui("sign-in").handlers.click({});
    await waitFor(() => assigned, "PKCE redirect");
    assert.equal(new URL(assigned).hostname, "login.microsoftonline.com");
    console.log("Embedded host behavior passed: " + mode);
    return;
  }
  if (["host-error", "host-foreign", "host-bad-context", "host-initial-401"].includes(mode)) {
    await waitFor(() => ui("error-message").textContent.length > 0, "host error shown");
    const expectedError = {"host-error": "Login to Azure", "host-foreign": "unusable", "host-bad-context": "incomplete",
      "host-initial-401": "rejected"}[mode];
    assert(ui("error-message").textContent.includes(expectedError), ui("error-message").textContent);
    if (mode === "host-initial-401") {
      assert.deepEqual(statuses, [{type: "esaif.agentChat.status", version: 1, state: "rejected", issuanceId: issuance(1)}],
        "a token the Agent rejects is reported with its exact issuance");
      statuses.length = 0;
    }
    assert.equal(ui("sign-in").disabled, false);
    assert.equal(ui("sign-in").hidden, false);
    assert.equal(apiCalls().filter(call => call.url !== "/api/context").length, 0, "no Agent data call without a confirmed session");
    assert.deepEqual(statuses, [], "nothing is acknowledged before the Agent confirms a session");
    await ui("sign-in").handlers.click({});
  }
  const failedRenewal = ["host-renew-switch", "host-renew-401"].includes(mode);
  await waitFor(() => !ui("scope-selector").disabled && calls.some(call => call.url === "/api/operations")
    || failedRenewal && ui("error-message").textContent.length > 0, "session started");
  assert.equal(assigned, null, "embedded mode never navigates to Microsoft sign-in");
  assert.deepEqual(storageWrites, [], "embedded mode stores no sign-in transaction");
  assert(!calls.some(call => call.url.includes("oauth2")));
  assert.equal(requests[0].type, "esaif.agentChat.tokenRequest");
  assert.equal(requests[0].version, 1);
  assert.match(requests[0].requestId, /^[A-Za-z0-9_-]{16,64}$/);
  assert.equal(requests[0].reason, "connect");
  if (mode === "host-initial-401") assert.equal(requests[1].reason, "rejected");
  assert(requests.every(request => Object.keys(request).sort().join() === "reason,requestId,type,version"));
  assert(statuses.every(status => status.version === 1 && Object.keys(status).sort().join()
    === (status.state === "rejected" ? "issuanceId,state,type,version" : "state,type,version")));
  assert(new Set(requests.map(request => request.requestId)).size === requests.length, "request IDs are unique");
  assert.equal(ui("sign-in").textContent, "Connect with app sign-in");
  assert.equal(states()[0], "connected", "the app is told only after the Agent confirmed /api/context");
  const noTokenInDom = () => assert(![...elements.values()].some(element =>
    element.textContent.includes(TOKEN_A) || element.textContent.includes(TOKEN_B)));
  if (failedRenewal) {
    await waitFor(() => ui("error-message").textContent.includes(mode === "host-renew-switch" ? "different" : "rejected"), "renewal failure");
    assert.deepEqual(requests.map(request => request.reason), ["connect", "renew"]);
    assert(calls.some(call => call.url === "/api/context" && call.authorization === "Bearer " + TOKEN_B));
    assert(!calls.some(call => ["/api/operations", "/api/chat"].includes(call.url)), "nothing is read or sent with an unconfirmed token");
    assert(ui("scope-selector").disabled);
    assert.equal(ui("sign-in").hidden, false);
    assert.equal(states().at(-1), mode === "host-renew-401" ? "rejected" : "disconnected");
    if (mode === "host-renew-401") assert.equal(statuses.at(-1).issuanceId, issuance(2), "the renewed token, not the confirmed one, was rejected");
    if (mode === "host-renew-401") {
      await ui("sign-in").handlers.click({});
      await waitFor(() => requests.length === 3, "reconnect request");
      assert.equal(requests[2].reason, "rejected");
    }
    noTokenInDom();
    console.log("Embedded host behavior passed: " + mode);
    return;
  }
  assert(ui("auth-status").textContent.includes("app sign-in"));
  assert(ui("auth-status").textContent.includes("user@contoso.example"));
  const expected = mode === "host-renew-same" ? TOKEN_B : TOKEN_A;
  if (mode === "host-renew-same") {
    assert.deepEqual(requests.map(request => request.reason), ["connect", "renew"], "parallel calls share one renewal");
    assert.deepEqual(calls.filter(call => call.url === "/api/context").map(call => call.authorization),
      ["Bearer " + TOKEN_A, "Bearer " + TOKEN_B], "renewal is confirmed by the server before use");
    assert(apiCalls().filter(call => call.url !== "/api/context").every(call => call.authorization === "Bearer " + TOKEN_B));
  } else if (mode === "host-renew-transient" || mode === "host-renew-invalid") {
    assert.deepEqual(requests.map(request => request.reason), ["connect", "renew"]);
    assert(apiCalls().filter(call => call.authorization === "Bearer " + TOKEN_B).every(call => call.url === "/api/context"));
    assert(apiCalls().filter(call => call.url !== "/api/context").every(call => call.authorization === "Bearer " + TOKEN_A),
      "a transient renewal failure keeps the still-valid session");
    assert.equal(ui("error-message").textContent, "");
  } else {
    assert(apiCalls().every(call => call.authorization === "Bearer " + TOKEN_A), "host token authorizes Agent API calls");
  }
  if (mode === "host-foreign") assert(!calls.some(call => call.authorization === "Bearer " + jwt("foreign")), "foreign request IDs are ignored");
  if (mode === "host-stale-401") {
    await waitFor(() => ui("refresh-status").disabled === false, "initial refresh finished");
    await ask();
    await waitFor(() => releaseChat, "question in flight with the first token");
    offset = 3400 * 1000;
    await ui("refresh-status").handlers.click({});
    await waitFor(() => requests.length === 2 && calls.some(call => call.url === "/api/operations"
      && call.authorization === "Bearer " + TOKEN_B), "renewed while the question is in flight");
    releaseChat();
    await waitFor(() => rejections.length === 1, "stale token reported");
    assert.deepEqual(rejections, [issuance(1)], "only the older token is quarantined");
    assert.deepEqual(states(), ["connected"], "the renewed session is neither rejected nor cleared");
    await waitFor(() => ui("error-message").textContent.includes("older"), "stale rejection explained");
    assert(!ui("scope-selector").disabled && ui("sign-in").hidden);
    noTokenInDom();
    console.log("Embedded host behavior passed: " + mode);
    return;
  }
  if (mode === "host-theme") {
    listener({data: {type: "esaif.agentChat.theme", version: 1, theme: "dark"}});
    assert.equal(sandbox.document.documentElement["data-theme"], "dark");
    listener({data: {type: "esaif.agentChat.theme", version: 1, theme: "<script>"}});
    assert.equal(sandbox.document.documentElement["data-theme"], "dark");
  }
  await ask();
  if (mode === "host-401" || mode === "host-401-text") {
    await waitFor(() => ui("sign-in").hidden === false, "session cleared after 401");
    assert.equal(states().at(-1), "rejected");
    assert.equal(statuses.at(-1).issuanceId, issuance(1));
    await ui("sign-in").handlers.click({});
    await waitFor(() => requests.length === 2, "reconnect request");
    assert.equal(requests[1].reason, "rejected");
  } else {
    await waitFor(() => ui("answer").textContent.includes("Embedded answer"), "answer");
    assert.equal(calls.find(call => call.url === "/api/chat").authorization, "Bearer " + expected);
    assert.equal(ui("error-message").textContent, "");
    if (mode === "host-connect") {
      await ui("sign-out").handlers.click({});
      assert.equal(states().at(-1), "disconnected");
    }
  }
  noTokenInDom();
  console.log("Embedded host behavior passed: " + mode);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


@pytest.mark.parametrize("mode", [
    "host-connect", "host-error", "host-foreign", "host-theme", "host-renew-same", "host-renew-switch",
    "host-renew-transient", "host-renew-invalid", "host-renew-401", "host-401", "host-401-text", "host-bad-context",
    "host-initial-401", "host-stale-401", "host-absent",
])
def test_embedded_app_host_bridge_reuses_app_sign_in_without_browser_redirects(mode):
    # The MAUI WebView2 host answers token requests; the page never performs PKCE or stores tokens.
    result = subprocess.run(
        ["node", "-", str(web.STATIC / "app.js"), mode], input=EMBEDDED_HOST_HARNESS,
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 0, result.stderr + result.stdout