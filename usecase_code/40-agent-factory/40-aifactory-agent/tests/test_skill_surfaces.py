from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from aifactory_agent import skills, web
from aifactory_agent.operations import MemoryOperationBackend, OperationStore
from aifactory_agent.tools import CONFIGURE_TOOL, FactoryTools
from test_security import SCOPE, principal, settings
from test_tools import preview, request


def test_exact_requested_names_useful_diagnostics_and_monthly_alias():
    assert len(skills.SKILL_LABELS) == 11
    for name in skills.SKILL_LABELS:
        assert skills.normalize_skill("/" + name) == name
    assert skills.normalize_skill("get-monthly-forecasted-project-estimated-azure-cost") == skills.COST_SKILLS[2]
    with pytest.raises(RuntimeError):
        skills.normalize_skill("shell")


def test_registry_defaults_block_actions_without_grant_or_operator_enablement(settings, principal):
    catalog = skills.skill_catalog(settings, principal, SCOPE)
    assert {entry["name"] for entry in catalog} == set(skills.SKILL_LABELS)
    for entry in catalog:
        assert entry["arguments_schema"]["additionalProperties"] is False
        if entry["name"] not in skills.DIAGNOSTIC_SKILLS:
            assert entry["available"] is False
            assert "permission_required" in entry["blockers"]
        if entry["kind"] == "action":
            assert entry["model_callable"] is False
            assert "skill_disabled" in entry["blockers"]
            assert "operation_signing_unconfigured" in entry["blockers"]


def test_chat_dispatch_cannot_prepare_action_skills(settings, principal, monkeypatch):
    adapter = FactoryTools(settings, principal, SCOPE)
    call = Mock(side_effect=AssertionError("Model dispatch must not construct an action client"))
    monkeypatch.setattr(adapter, "_client", call)
    for name in skills.ACTION_SKILLS:
        assert adapter.execute(name, {})["ok"] is False
    call.assert_not_called()


@pytest.fixture
def app(settings, principal):
    application = web.create_app(settings)
    store = Mock(spec=OperationStore)
    application.dependency_overrides[web.get_principal] = lambda: principal
    application.dependency_overrides[web.get_operation_store] = lambda: store
    return application, store


def test_skill_discovery_does_not_expose_private_profiles(app):
    application, store = app
    with TestClient(application) as client:
        response = client.get("/api/skills", params={"scope_key": SCOPE})
        assert response.status_code == 200
        assert len(response.json()["skills"]) == 11
        assert "bootstrap_profiles" not in response.text
        assert "factory-api-key" not in response.text
    assert not store.mock_calls


@pytest.mark.parametrize("name", skills.ACTION_SKILLS)
def test_action_cannot_run_via_monitoring_endpoint(app, name):
    application, store = app
    with TestClient(application) as client:
        response = client.post(f"/api/skills/{name}/run", json={"scope_key": SCOPE, "arguments": {}})
        assert response.status_code == 409
    assert not store.mock_calls


@pytest.mark.parametrize("name", skills.ACTION_SKILLS)
def test_metadata_grant_does_not_authorize_factory_action(app, monkeypatch, name):
    application, store = app
    prepare = Mock(side_effect=AssertionError("Insufficient grants must stop before preparation"))
    monkeypatch.setattr(FactoryTools, "prepare_skill", prepare)
    with TestClient(application) as client:
        response = client.post(f"/api/skills/{name}/propose", json={"scope_key": SCOPE, "arguments": {}})
        assert response.status_code == 403
    prepare.assert_not_called()
    assert not store.mock_calls


def test_cost_skill_does_not_create_approve_or_execute_operation(app, monkeypatch):
    from aifactory_agent.costs import CostSkills
    application, store = app
    current = application.state.settings
    grant = current.auth.grants[0]
    application.state.settings = current.model_copy(update={"auth": current.auth.model_copy(update={
        "grants": [grant.model_copy(update={"permissions": grant.permissions + ["cost.read"]})],
    })})
    run = Mock(return_value={"ok": True, "data": {"basis": "actual", "currency": "USD"}})
    monkeypatch.setattr(CostSkills, "execute", run)
    with TestClient(application) as client:
        response = client.post(f"/api/skills/{skills.COST_SKILLS[2]}/run", json={
            "scope_key": SCOPE, "arguments": {"resource_group": "factory-project001-dev-rg"},
        })
        assert response.status_code == 200
    run.assert_called_once()
    assert not store.mock_calls


def test_skill_route_rejects_scope_overrides_and_raw_plan(app):
    application, _ = app
    with TestClient(application) as client:
        response = client.post(f"/api/skills/{skills.ACTION_SKILLS[0]}/propose", json={
            "scope_key": SCOPE, "arguments": {}, "tenant_id": "other", "approval": True, "request": {},
        })
        assert response.status_code == 422
        assert "other" not in response.text


def test_diagnostics_reuse_existing_api_and_never_propose(app, monkeypatch):
    application, store = app
    execute = Mock(return_value={"ok": True, "data": {"status": "healthy"}})
    monkeypatch.setattr(FactoryTools, "execute", execute)
    with TestClient(application) as client:
        response = client.post("/api/skills/get-aifactory-health/run", json={"scope_key": SCOPE, "arguments": {}})
        assert response.status_code == 200 and response.json()["data"]["status"] == "healthy"
    execute.assert_called_once_with("factory_health", {})
    assert not store.mock_calls


def test_diagnostic_operation_status_rejects_other_active_scope(app):
    application, store = app
    store.read.return_value = {"scope_key": "project002-dev"}
    with TestClient(application) as client:
        response = client.post("/api/skills/get-aifactory-operation-status/run", json={
            "scope_key": SCOPE, "arguments": {"operation_id": "88888888-8888-4888-8888-888888888888"},
        })
        assert response.status_code == 403
    store.observe.assert_not_called()


def test_diagnostic_status_and_continuation_do_not_accept_raw_jobs_or_plans(app):
    application, store = app
    with TestClient(application) as client:
        response = client.post("/api/skills/get-aifactory-operation-status/run", json={
            "scope_key": SCOPE, "arguments": {"job_id": "other", "folder": "other"},
        })
        assert response.status_code == 400
        response = client.post("/api/operations/88888888-8888-4888-8888-888888888888/continue", json={
            "plan_hash": "a" * 64, "observation_hash": "b" * 64, "request": {"command": "arbitrary"},
        })
        assert response.status_code == 422
    assert not store.mock_calls


@pytest.mark.parametrize("name,permission", [
    ("create-agent-oftype-for-project", "agent.create"),
    ("create-ml-model-oftype-for-project", "model.create"),
])
def test_workload_creation_requires_dedicated_grant_and_never_runs_from_chat(app, name, permission):
    application, store = app
    with TestClient(application) as client:
        response = client.post(f"/api/skills/{name}/propose", json={"scope_key": SCOPE, "arguments": {}})
        assert response.status_code == 403
        response = client.post(f"/api/skills/{name}/run", json={"scope_key": SCOPE, "arguments": {}})
        assert response.status_code == 409
    assert skills.SKILL_PERMISSIONS[name] == permission
    assert not store.mock_calls


def test_async_store_start_is_not_success_and_cannot_replay(settings, principal):
    store = OperationStore(settings, backend=MemoryOperationBackend())
    operation = store.propose(principal, SCOPE, CONFIGURE_TOOL, request(settings), preview())
    store.approve(principal, operation["id"], operation["plan_hash"])
    calls = []
    result = store.execute(principal, operation["id"], lambda record: (
        calls.append(record["id"]) or {"ok": True, "execution_status": "running", "data": {"job_id": "fake-job"}}
    ))
    assert result["status"] == "running"
    assert result["progress"]["completion_known"] is False
    assert result["progress"]["retry_allowed"] is False
    with pytest.raises(RuntimeError):
        store.execute(principal, operation["id"], lambda _: pytest.fail("must not replay"))
    result = store.observe(principal, operation["id"], lambda record: {
        "ok": True, "execution_status": "succeeded", "data": {"job_id": "fake-job", "status": "succeeded"},
    })
    assert result["status"] == "succeeded"
    assert result["outcome"]["data"]["job_id"] == "fake-job"
    assert result["observation"]["execution_status"] == "succeeded"
    assert calls == [operation["id"]]


def test_invalid_async_status_never_invents_completion(settings, principal):
    store = OperationStore(settings, backend=MemoryOperationBackend())
    operation = store.propose(principal, SCOPE, CONFIGURE_TOOL, request(settings), preview())
    store.approve(principal, operation["id"], operation["plan_hash"])
    store.execute(principal, operation["id"], lambda _: {"ok": True, "execution_status": "running"})
    with pytest.raises(RuntimeError):
        store.observe(principal, operation["id"], lambda _: {"ok": True, "execution_status": "unknown"})
    assert store.read(principal, operation["id"])["status"] == "running"
