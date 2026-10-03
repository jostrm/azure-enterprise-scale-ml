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
        factory.assert_called_once_with(app.state.settings, knowledge)
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
    factory.assert_called_once_with(app.state.settings, principal, "project001-dev", operation_store=store)
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
    factory.assert_called_once_with(app.state.settings, principal, "project001-dev", operation_store=store)
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
        for path in ("/", "/api/public-config", "/api/context", "/static/app.js", "/static/theme.css"):
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
        assert client.get("/docs").status_code == 404
        assert client.get("/static/../config.example.json").status_code == 404
    js = (web.STATIC / "app.js").read_text("utf-8")
    assert "innerHTML" not in js and "localStorage" not in js
    assert "client_secret" not in js and "offline_access" not in js
    css = (web.STATIC / "theme.css").read_text("utf-8")
    components = css[css.index("* {"):]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", components)
    assert '--cp-bg: #f7f4ef;' in css and '"Segoe UI"' in css


def test_frontend_javascript_syntax():
    result = subprocess.run(["node", "--check", str(web.STATIC / "app.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", [
    "blocked", "pkce", "bad-state", "authenticated", "approval", "cancel-disabled",
    "discard", "out-of-sync", "reindex", "user-proposal", "proposal-blocked", "proposal-api-unavailable",
])
def test_mocked_browser_pkce_safe_rendering_and_separate_approval(mode):
    # Node's built-in VM/crypto exercise the shipped script; all HTTP/DOM objects are unit-test mocks.
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const {webcrypto, createHash} = require("node:crypto");
const mode = process.argv[3];
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
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  set id(value) { this._id = value; elements.set(value, this); }
  get id() { return this._id; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this._text = ""; this.children = items; }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
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
let operationStatus = "pending";
let proposalCreated = false;
let resolveLate;
const hash = "a".repeat(64);
const operationId = "33333333-3333-4333-8333-333333333333";
const operation = () => ({
  id: operationId, correlation_id: operationId, tool_name: "factory_prepare_settings",
  scope_key: "project001-dev", scope: {factory: "factory", project: "001", environment: "dev"},
  factory_api_url: "https://factory-api.example",
  request: {settings: {department_name: "Research"}}, preview: {can_execute: true},
  affected_resources: [], created_at: "2026-10-03", expires_at: "2026-10-04",
  status: operationStatus, plan_hash: hash, progress: {phase: operationStatus},
});
const context = {
  scopes: [{key: "project001-dev", label: "factory / 001 / dev",
    scope: {factory: "factory", project: "001", environment: "dev", tenant_id: config.tenant_id,
      subscription_id: clientId, resource_group: "project-rg"},
    permissions: ["knowledge.read", "factory.read", "config.write"]}],
  settings: {writes_enabled: !["cancel-disabled", "proposal-blocked"].includes(mode)},
  capabilities: {
    model_read_only: true, proposal_creation: true,
    proposal_blockers: mode === "proposal-blocked" ? ["writes_disabled", "factory_target_unconfigured"] : [],
  },
};
const answer = {
  answer: '<img src=x onerror="steal()"> [S1]', scope_key: "project001-dev", audience: "project",
  correlation_id: operationId, tool_activity: [],
  citations: [{citation_id: "S1", heading: "<script>bad</script>", is_history: true,
    source_type: "release_note", source_url: "javascript:steal()", version: "1.2"}],
};
const response = (data) => ({ok: true, status: 200, json: async () => data});
const sandbox = {
  document: {getElementById: ui, createElement: (tag) => new Element(tag)},
  location, history: {replaceState(_, __, url) { historyCalls.push(url); current = new URL(url, current); }},
  crypto: webcrypto, isSecureContext: true, URL, URLSearchParams, TextEncoder,
  sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key)},
  btoa: value => Buffer.from(value, "binary").toString("base64"),
  setInterval: () => 1,
  fetch: async (url, options = {}) => {
    calls.push({url, options, body: options.body ? String(options.body) : null, location: current.href});
    if (url === "/api/public-config") return response(config);
    if (url.endsWith("/oauth2/v2.0/token")) return response({
      token_type: "Bearer", access_token: "UNIT_TEST_ACCESS_TOKEN", expires_in: 3600,
    });
    if (url === "/api/context") return response(context);
    if (url.startsWith("/api/knowledge/status")) return response({
      status: {
        status: mode === "out-of-sync" ? "index_out_of_sync" : mode === "reindex" ? "reindex_required" : "ready",
        stale: false, indexed_document_count: 10, reconciliation_pending: false,
        search_document_count: mode === "out-of-sync" ? 9 : 10,
      },
    });
    if (url === "/api/operations") return response({
      operations: ["approval", "cancel-disabled"].includes(mode) || proposalCreated ? [operation()] : [],
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
    throw new Error("Unexpected mock request: " + url);
  },
};
sandbox.window = sandbox;
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
async function waitFor(predicate) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw new Error("Mock browser condition did not complete");
}
async function dispatch(element, name) {
  await element.handlers[name]({preventDefault() {}});
}
function descendants(element) {
  return element.children.flatMap(child => [child, ...descendants(child)]);
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
    if (mode === "proposal-blocked") {
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
      await waitFor(() => ui("proposed-plans").textContent.includes("Execute approved metadata"));
      const approval = calls.find(call => call.url.endsWith("/approve"));
      assert.deepEqual(JSON.parse(approval.body), {plan_hash: hash});
      assert(!calls.some(call => call.url.endsWith("/execute")));
      const execute = descendants(ui("proposed-plans")).find(child =>
        child.tagName === "button" && child.textContent.includes("Execute approved"));
      await dispatch(execute, "click");
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
        assert.equal(ui("answer").textContent, answer.answer);
        assert.equal(ui("answer").children.length, 0);
        assert(ui("citations").textContent.includes("HISTORICAL RELEASE NOTE"));
        assert(!descendants(ui("citations")).some(child => child.tagName === "a"));
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
