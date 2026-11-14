import copy
import json
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from test_runtime import (
    CALLER, SCOPE, action_fixtures, artifacts, config_path, configuration, runtime, security_fixtures,
)
from azure.core.exceptions import AzureError
from azurefactory.errors import APIError, AuthError, ConfigError, RequestTimeout


@pytest.fixture
def setup_backend(runtime):
    from aifactory_agent.operations import MemoryOperationBackend, OperationStore
    from aifactory_agent.tools import FactoryTools
    from aifactory_mcp.backend import AgentBackend

    api = action_fixtures.FakeAPI(runtime.settings)
    api.health = lambda: {"status": "ok"}
    api.creation_capabilities = lambda: {"capabilities": ["review"]}
    store = OperationStore(runtime.settings, backend=MemoryOperationBackend())

    class BoundTools(FactoryTools):
        def _client(self, *, authenticated=True):
            self._api_key = api.api_key
            return api

    backend = AgentBackend(runtime, runtime.local_principal(CALLER), SCOPE,
                           operation_store=store, tools_factory=BoundTools)
    return backend, api, store


def prepare(backend):
    return backend.call_tool("factory_prepare_delete", {})["operation"]


def approve(backend, record):
    return backend.approve(record["id"], record["plan_hash"], record["preview"]["confirmation_phrase"])


def assert_error(code, callback):
    from aifactory_mcp.backend import BackendError

    with pytest.raises(BackendError) as exc:
        callback()
    assert exc.value.code == code
    assert 400 <= exc.value.status_code <= 599
    return exc.value


def test_descriptors_match_real_skills_and_tools(setup_backend):
    from aifactory_agent.skills import ACTION_SKILLS, argument_model, skill_catalog
    from aifactory_agent.tools import FactoryTools

    backend, _, _ = setup_backend
    descriptors = backend.list_tools()
    tools = {item["name"]: item for item in descriptors}
    assert len(tools) == len(descriptors)
    actual = FactoryTools(backend.runtime.settings, backend.principal, SCOPE).descriptors()
    accepted = {"factory_health", "factory_capabilities", "factory_catalog", "factory_settings", "factory_cli_health",
                *backend.runtime.costs.COST_TOOL_TO_SKILL}
    assert {item["name"] for item in actual if item["name"] in accepted} <= tools.keys()
    for name, skill in zip(
        ("factory_prepare_create", "factory_prepare_delete", "factory_prepare_add_project"), ACTION_SKILLS,
    ):
        assert tools[name]["inputSchema"] == argument_model(skill).model_json_schema()
        assert tools[name]["annotations"]["readOnlyHint"] is False
    assert tools["factory_prepare_delete"]["annotations"]["destructiveHint"] is True
    assert tools["factory_execute_operation"]["annotations"]["destructiveHint"] is True
    assert tools["factory_operation_status"]["annotations"]["readOnlyHint"] is False
    for item in tools.values():
        assert len(item["name"]) <= 64
        assert item["inputSchema"]["additionalProperties"] is False
        assert set(item["annotations"]) == {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
    assert not any("approve" in name for name in tools)
    assert backend.call_tool("factory_skills", {})["data"] == skill_catalog(
        backend.runtime.settings, backend.principal, SCOPE,
    )


def test_upstream_reserved_or_future_mutators_cannot_override_mcp_contract(setup_backend, monkeypatch):
    from aifactory_agent.tools import FactoryTools, NoArguments

    backend, _, _ = setup_backend
    original = FactoryTools.descriptors

    def descriptors(tools):
        return [*original(tools), *[
            tools._descriptor(name, "Future upstream behavior", NoArguments)
            for name in ("factory_operation_status", "factory_prepare_delete", "factory_future_mutator")
        ]]

    monkeypatch.setattr(FactoryTools, "descriptors", descriptors)
    definitions = backend.list_tools()
    names = [item["name"] for item in definitions]
    assert len(names) == len(set(names))
    assert "factory_future_mutator" not in names
    status = next(item for item in definitions if item["name"] == "factory_operation_status")
    assert status["annotations"]["readOnlyHint"] is False
    assert set(status["inputSchema"]["properties"]) == {"operation_id"}
    assert status["inputSchema"]["required"] == ["operation_id"]
    assert_error("invalid_arguments", lambda: backend.call_tool("factory_operation_status", {}))
    assert_error("unsupported_tool", lambda: backend.call_tool("factory_future_mutator", {}))


@pytest.mark.parametrize("name", ["factory_health", "cost_monthly_project_forecast"])
def test_duplicate_accepted_upstream_descriptors_fail_closed(setup_backend, monkeypatch, name):
    from aifactory_agent.tools import FactoryTools

    backend, _, _ = setup_backend
    original = FactoryTools.descriptors

    def descriptors(tools):
        definitions = original(tools)
        return [*definitions, next(item for item in definitions if item["name"] == name)]

    monkeypatch.setattr(FactoryTools, "descriptors", descriptors)
    assert_error("invalid_factory_contract", backend.list_tools)
    assert_error("invalid_factory_contract", lambda: backend.call_tool("factory_health", {}))


def test_real_factory_read_and_catalog_are_scoped(setup_backend):
    backend, api, _ = setup_backend
    assert backend.call_tool("factory_health", {})["data"] == {"status": "ok"}
    assert backend.call_tool("factory_capabilities", {})["data"] == {"capabilities": ["review"]}
    data = backend.call_tool("factory_catalog", {})["data"]
    assert data["factory"]["id"] == security_fixtures.FACTORY
    assert data["project"]["number"] == "001"
    api.catalog["factories"][0]["prefix"] = "another"
    assert_error("factory_scope_mismatch", lambda: backend.call_tool("factory_catalog", {}))


@pytest.mark.parametrize("tool,args", [
    ("factory_health", {"endpoint": "https://attacker.test"}),
    ("factory_prepare_delete", {"force": True}),
    ("factory_prepare_create", {"folder": "C:\\arbitrary"}),
    ("factory_prepare_add_project", {"project_number": 1, "display_name": "bad"}),
    ("factory_operation", {"operation_id": "not-a-uuid"}),
    ("factory_execute_operation", {"operation_id": security_fixtures.CALLER, "approved": True}),
    ("factory_skills", []),
    ("cost_monthly_project_forecast", {"resource_group": "bad/path"}),
    ("factory_operations", {"scope_key": "project002-dev"}),
])
def test_closed_input_validation_before_dispatch(setup_backend, tool, args):
    backend, api, _ = setup_backend
    assert_error("invalid_arguments", lambda: backend.call_tool(tool, args))
    assert api.calls == []


@pytest.mark.parametrize("name", ["factory_approve_operation", "approve", "shell", "/delete-aifactory", None])
def test_no_arbitrary_dispatch_or_model_approval(setup_backend, name):
    backend, api, _ = setup_backend
    assert_error("unsupported_tool", lambda: backend.call_tool(name, {}))
    assert api.calls == []


def test_disabled_actions_stay_discoverable_with_explicit_blockers(runtime, configuration, config_path):
    from aifactory_mcp.runtime import load_runtime

    configuration["factory"]["writes_enabled"] = False
    config_path.write_text(json.dumps(configuration), encoding="utf-8")
    runtime = load_runtime(config_path)
    backend = runtime.backend(runtime.local_principal(CALLER), SCOPE)
    assert "factory_prepare_delete" in {tool["name"] for tool in backend.list_tools()}
    catalog = backend.call_tool("factory_skills", {})["data"]
    assert all("writes_disabled" in item["blockers"] for item in catalog if item["kind"] == "action")
    assert_error("writes_disabled", lambda: backend.call_tool("factory_prepare_delete", {}))


def test_authorization_rechecked_and_permissions_not_unioned(runtime, setup_backend):
    backend, _, _ = setup_backend
    assert_error("forbidden", lambda: runtime.backend(runtime.local_principal(security_fixtures.CLIENT), SCOPE))
    assert_error("forbidden", lambda: runtime.backend(runtime.local_principal(CALLER), "project002-dev"))
    original = list(runtime.settings.auth.grants)
    runtime.settings.auth.grants.clear()
    try:
        assert_error("forbidden", backend.list_tools)
        assert_error("forbidden", lambda: backend.call_tool("factory_health", {}))
    finally:
        runtime.settings.auth.grants.extend(original)


def test_prepare_persists_review_and_execute_requires_human_approval(setup_backend):
    backend, api, store = setup_backend
    record = prepare(backend)
    assert record["status"] == "pending"
    assert store.read(backend.principal, record["id"])["plan_hash"] == record["plan_hash"]
    assert store.backend.events[-1]["event"] == "proposed"
    assert not any(call[0] == "delete_aifactory_confirm" for call in api.calls)
    assert_error("approval_required", lambda: backend.call_tool("factory_execute_operation", {"operation_id": record["id"]}))
    assert_error("plan_hash_mismatch", lambda: backend.approve(record["id"], "0" * 64))
    assert_error("confirmation_phrase_required", lambda: backend.approve(record["id"], record["plan_hash"]))
    assert approve(backend, record)["operation"]["status"] == "approved"
    result = backend.call_tool("factory_execute_operation", {"operation_id": record["id"]})
    assert result["operation"]["status"] == "running"
    assert result["operation"]["progress"]["completion_known"] is False
    assert_error("approval_required", lambda: backend.call_tool("factory_execute_operation", {"operation_id": record["id"]}))
    assert sum(call[0] == "delete_aifactory_confirm" for call in api.calls) == 1
    observed = backend.call_tool("factory_operation_status", {"operation_id": record["id"]})
    assert observed["operation"]["status"] == "succeeded"
    assert store.backend.events[-1]["event"] == "succeeded"


def test_cancel_pending_plan_prevents_execution(setup_backend):
    backend, _, _ = setup_backend
    record = prepare(backend)
    assert backend.call_tool("factory_cancel_operation", {"operation_id": record["id"]})["operation"]["status"] == "cancelled"
    assert_error("operation_conflict", lambda: approve(backend, record))


def test_operations_never_escape_bound_scope(setup_backend):
    from aifactory_mcp.backend import AgentBackend

    backend, _, store = setup_backend
    record = prepare(backend)
    values = backend.runtime.settings.model_dump(mode="json")
    values["scopes"]["other"] = copy.deepcopy(values["scopes"][SCOPE])
    values["auth"]["grants"].append({"object_id": CALLER, "scopes": ["other"], "permissions": ["factory.read", "factory.delete"]})
    settings = backend.runtime.settings.model_validate(values)
    # Use the actual store with both authorized scopes: the adapter must still bind one.
    store.settings = settings
    other = AgentBackend(replace(backend.runtime, settings=settings), backend.principal, "other", operation_store=store)
    assert other.call_tool("factory_operations", {})["data"] == []
    for name in ("factory_operation", "factory_operation_status", "factory_execute_operation", "factory_cancel_operation"):
        assert_error("operation_scope_mismatch", lambda: other.call_tool(name, {"operation_id": record["id"]}))
    assert_error("operation_scope_mismatch", lambda: other.approve(record["id"], record["plan_hash"]))
    assert store.read(backend.principal, record["id"])["status"] == "pending"


@pytest.mark.parametrize("approved", [False, True])
def test_read_only_operation_tools_do_not_expire_or_audit_plans(setup_backend, approved):
    backend, _, store = setup_backend
    record = prepare(backend)
    if approved:
        approve(backend, record)
    before = copy.deepcopy(store.backend._records)
    events = copy.deepcopy(store.backend.events)
    now = store._now()
    store.clock = lambda: now + timedelta(hours=1)

    result = backend.call_tool("factory_operation", {"operation_id": record["id"]})
    listed = backend.call_tool("factory_operations", {})["data"]
    persisted = next(iter(before.values()))[0]
    assert result["operation"] == persisted
    assert listed == [persisted]
    assert store.backend._records == before
    assert store.backend.events == events
    descriptors = {item["name"]: item for item in backend.list_tools()}
    assert descriptors["factory_operation"]["annotations"]["readOnlyHint"] is True
    assert descriptors["factory_operations"]["annotations"]["readOnlyHint"] is True
    # A read-only snapshot does not extend the plan's approval/execution lifetime.
    action = ((lambda: backend.call_tool("factory_execute_operation", {"operation_id": record["id"]}))
              if approved else (lambda: approve(backend, record)))
    assert_error("plan_expired", action)


def test_foreign_scope_expired_plan_is_not_mutated_by_any_precheck(setup_backend):
    from aifactory_mcp.backend import AgentBackend

    backend, _, store = setup_backend
    record = prepare(backend)
    values = backend.runtime.settings.model_dump(mode="json")
    values["scopes"]["other"] = copy.deepcopy(values["scopes"][SCOPE])
    values["auth"]["grants"].append({
        "object_id": CALLER, "scopes": ["other"], "permissions": ["factory.read", "factory.delete"],
    })
    settings = backend.runtime.settings.model_validate(values)
    store.settings = settings
    other = AgentBackend(replace(backend.runtime, settings=settings), backend.principal, "other",
                         operation_store=store)
    before = copy.deepcopy(store.backend._records)
    events = copy.deepcopy(store.backend.events)
    now = store._now()
    store.clock = lambda: now + timedelta(hours=1)

    assert other.call_tool("factory_operations", {})["data"] == []
    for name in ("factory_operation", "factory_operation_status", "factory_execute_operation",
                 "factory_cancel_operation"):
        assert_error("operation_scope_mismatch", lambda: other.call_tool(name, {"operation_id": record["id"]}))
    assert_error("operation_scope_mismatch", lambda: other.approve(record["id"], record["plan_hash"]))
    assert store.backend._records == before
    assert store.backend.events == events


def test_snapshot_reads_still_validate_integrity_and_revoked_permissions(setup_backend):
    backend, _, store = setup_backend
    record = prepare(backend)
    key = store._key(backend.principal, record["id"])
    stored, etag = store.backend.read(key)
    stored["request"]["factory_id"] = security_fixtures.CLIENT
    store.backend.replace(key, stored, etag)
    assert_error("plan_changed", lambda: backend.call_tool("factory_operation", {"operation_id": record["id"]}))
    assert_error("plan_changed", lambda: backend.call_tool("factory_operations", {}))
    backend.runtime.settings.auth.grants[0].permissions.remove("factory.delete")
    assert_error("forbidden", lambda: backend.call_tool("factory_operation", {"operation_id": record["id"]}))
    assert backend.call_tool("factory_operations", {})["data"] == []


@pytest.mark.parametrize("failure", [
    RequestTimeout("credential-private"), APIError("credential-private", status=500),
    AzureError("credential-private"), httpx.ConnectError("credential-private"), OSError("credential-private"),
    AuthError("credential-private"), ConfigError("credential-private"),
])
def test_uncertain_execution_is_error_envelope_and_cannot_replay(setup_backend, failure):
    backend, api, _ = setup_backend
    record = prepare(backend)
    approve(backend, record)

    def fail(**kwargs):
        raise failure

    api.delete_aifactory_confirm = fail
    result = backend.call_tool("factory_execute_operation", {"operation_id": record["id"]})
    assert result["ok"] is False
    assert result["operation"]["status"] == "uncertain"
    assert "credential-private" not in json.dumps(result)
    assert_error("approval_required", lambda: backend.call_tool("factory_execute_operation", {"operation_id": record["id"]}))


@pytest.mark.parametrize("failure", [
    APIError("unknown-secret-value", status=502), AzureError("unknown-secret-value"),
    httpx.ConnectError("unknown-secret-value"), OSError("unknown-secret-value"),
    AuthError("unknown-secret-value"), ConfigError("unknown-secret-value"),
])
def test_internal_failures_are_sanitized(setup_backend, failure, capsys, caplog):
    from aifactory_mcp.backend import BackendError

    backend, api, _ = setup_backend

    def fail():
        raise failure

    api.health = fail
    with pytest.raises(BackendError) as exc:
        backend.call_tool("factory_health", {})
    assert "unknown-secret-value" not in str(exc.value)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown-secret-value" not in captured.err + caplog.text


@pytest.mark.parametrize("failure", [RuntimeError("programming defect"), TypeError("programming defect")])
def test_programmer_errors_propagate_without_logging(setup_backend, failure, capsys, caplog):
    backend, api, _ = setup_backend

    def fail():
        raise failure

    api.health = fail
    with pytest.raises(type(failure), match="programming defect"):
        backend.call_tool("factory_health", {})
    captured = capsys.readouterr()
    assert captured.out == captured.err == caplog.text == ""


def test_execute_programmer_error_propagates_without_replaying_claimed_operation(setup_backend, caplog):
    backend, api, store = setup_backend
    record = prepare(backend)
    approve(backend, record)

    def fail(**kwargs):
        raise TypeError("programming defect")

    api.delete_aifactory_confirm = fail
    with pytest.raises(TypeError, match="programming defect"):
        backend.call_tool("factory_execute_operation", {"operation_id": record["id"]})
    assert caplog.text == ""
    assert store.read(backend.principal, record["id"])["status"] == "executing"
    assert_error("approval_required", lambda: backend.call_tool("factory_execute_operation", {"operation_id": record["id"]}))


def test_outputs_redact_known_api_key_and_secret_fields(setup_backend):
    backend, api, _ = setup_backend
    api.health = lambda: {"message": f"test {api.api_key}", "password": "hidden", "nested": {"api_key": "hidden"}}
    text = json.dumps(backend.call_tool("factory_health", {}))
    assert api.api_key not in text and "hidden" not in text


def test_default_store_is_lazy_and_durable(runtime, monkeypatch):
    from aifactory_agent.operations import BlobOperationBackend
    import aifactory_agent.operations

    backend = runtime.backend(runtime.local_principal(CALLER), SCOPE)
    created = []
    actual = aifactory_agent.operations.OperationStore

    def build(settings):
        store = actual(settings)
        created.append(store)
        return store

    monkeypatch.setattr(aifactory_agent.operations, "OperationStore", build)
    backend.list_tools()
    backend.call_tool("factory_skills", {})
    assert created == []
    assert isinstance(backend.operation_store.backend, BlobOperationBackend)
    assert backend.operation_store is created[0]


def test_real_add_project_prepare_approve_and_execute(setup_backend):
    backend, api, store = setup_backend
    api.catalog["factories"] = [action_fixtures.factory_target(existing_project=False)]
    record = backend.call_tool("factory_prepare_add_project", {
        "project_number": "001", "display_name": "Research",
    })["operation"]
    assert store.read(backend.principal, record["id"])["request"]["action"] == "add-project"
    backend.approve(record["id"], record["plan_hash"])
    api.result = {"contract_version": 1, "catalog": {"contract_version": 1, "revision": "b" * 64,
                  "factories": [record["preview"]["target"]]}, "job": None}
    result = backend.call_tool("factory_execute_operation", {"operation_id": record["id"]})
    assert result["ok"] is True
    assert result["operation"]["status"] == "succeeded"
    assert result["operation"]["outcome"]["data"]["resources_deployed"] is False


def test_bootstrap_awaiting_continuation_is_not_success_or_automatic_continue(setup_backend):
    backend, api, _ = setup_backend
    record = backend.call_tool("factory_prepare_create", {})["operation"]
    backend.approve(record["id"], record["plan_hash"])
    api.result = action_fixtures.workflow_status(record, status="awaiting-review")
    result = backend.call_tool("factory_execute_operation", {"operation_id": record["id"]})
    assert result["operation"]["status"] == "awaiting_continuation"
    assert result["operation"]["progress"]["completion_known"] is False
    assert not any(call[0] == "creation_workflow_continue" for call in api.calls)


def test_failed_execution_is_persisted_error_not_success(setup_backend):
    backend, api, store = setup_backend
    record = prepare(backend)
    approve(backend, record)
    api.catalog["revision"] = "d" * 64
    result = backend.call_tool("factory_execute_operation", {"operation_id": record["id"]})
    assert result["ok"] is False
    assert result["error"]["code"] == "operation_failed"
    assert result["operation"]["status"] == "failed"
    assert store.read(backend.principal, record["id"])["status"] == "failed"
    assert not any(call[0] == "delete_aifactory_confirm" for call in api.calls)


@pytest.mark.parametrize("state", ["failed", "uncertain"])
def test_observed_failed_or_uncertain_job_is_error_envelope(setup_backend, state):
    backend, api, _ = setup_backend
    if state == "uncertain":
        record = backend.call_tool("factory_prepare_create", {})["operation"]
        backend.approve(record["id"], record["plan_hash"])
        api.result = action_fixtures.workflow_status(record)
        api.workflow_state = action_fixtures.workflow_status(record, status=state)
    else:
        record = prepare(backend)
        approve(backend, record)
        api.delete_aifactory_status = lambda *_: api.job("delete-factory", status=state)
    backend.call_tool("factory_execute_operation", {"operation_id": record["id"]})
    result = backend.call_tool("factory_operation_status", {"operation_id": record["id"]})
    assert result["ok"] is False
    assert result["operation"]["status"] == state


def test_costs_use_real_cost_skill_and_bound_azure_resource_group(setup_backend, monkeypatch):
    import httpx
    from types import SimpleNamespace
    from aifactory_agent import config, costs
    from test_runtime import load_fixture_module

    cost_fixtures = load_fixture_module("test_costs")
    backend, _, _ = setup_backend
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "management.azure.com"
        assert str(security_fixtures.SUBSCRIPTION) in request.url.path
        assert "/resourceGroups/factory-project001-dev-rg/" in request.url.path
        return httpx.Response(200, json=cost_fixtures.forecast_page() if request.url.path.endswith("/forecast")
                              else cost_fixtures.actual_page())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(costs.httpx, "Client", lambda **_: client)
    monkeypatch.setattr(config, "credential", lambda _: SimpleNamespace(
        get_token=lambda *_: SimpleNamespace(token="fake-test-arm-token"),
    ))
    result = backend.call_tool("cost_monthly_project_forecast", {"resource_group": "factory-project001-dev-rg"})
    assert result["ok"] is True
    assert result["data"]["skill"] == costs.COST_SKILLS[2]
    assert len(requests) == 2
    assert_error("forbidden", lambda: backend.call_tool(
        "cost_monthly_project_forecast", {"resource_group": "another-project-dev-rg"},
    ))


def test_secrets_redacted_from_unauthenticated_health_even_before_key_load(setup_backend, monkeypatch):
    backend, api, _ = setup_backend
    monkeypatch.setenv("AIFACTORY_API_KEY", "ambient-factory-key")
    api.health = lambda: {"message": "ambient-factory-key"}
    assert "ambient-factory-key" not in json.dumps(backend.call_tool("factory_health", {}))
