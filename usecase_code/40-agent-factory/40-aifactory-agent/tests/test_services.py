from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from aifactory_agent.services import AgentDependencies, AgentFactory, AgentServices
from aifactory_agent.security import Principal
from aifactory_agent.web import create_app
from test_security import CALLER, CLIENT, SCOPE, TENANT, settings


def injected_dependencies():
    knowledge = Mock()
    knowledge.status.return_value = {
        "status": "ready", "stale": False, "reconciliation_pending": False,
        "indexed_document_count": 4, "search_document_count": 4,
    }
    store = Mock()
    store.list.return_value = []
    conversation = Mock()
    conversation.answer.return_value = {"answer": "injected"}
    tools = Mock()
    costs = Mock()
    return AgentDependencies(
        knowledge_factory=Mock(return_value=knowledge),
        operation_store_factory=Mock(return_value=store),
        conversation_factory=Mock(return_value=conversation),
        tool_factory=Mock(return_value=tools),
        cost_factory=Mock(return_value=costs),
        authenticate=Mock(return_value=Principal(TENANT, CALLER)),
    ), knowledge, store, conversation


def test_services_are_lazy_and_request_tools_keep_caller_local(settings):
    dependencies, knowledge, store, _ = injected_dependencies()
    services = AgentServices(settings, dependencies=dependencies)
    dependencies.knowledge_factory.assert_not_called()
    dependencies.operation_store_factory.assert_not_called()
    assert services.knowledge() is knowledge
    assert services.knowledge() is knowledge
    assert services.operation_store() is store
    assert services.operation_store() is store
    dependencies.knowledge_factory.assert_called_once_with(settings)
    dependencies.operation_store_factory.assert_called_once_with(settings)
    caller, stranger = Principal(TENANT, CALLER), Principal(TENANT, CLIENT)
    services.tools(caller, SCOPE)
    services.tools(stranger, SCOPE)
    assert dependencies.tool_factory.call_args_list[0].args[1] is caller
    assert dependencies.tool_factory.call_args_list[1].args[1] is stranger
    assert not hasattr(services, "principal")


def test_factory_creates_two_isolated_agents_and_does_not_mutate_prototype(settings):
    first, _, _, _ = injected_dependencies()
    second, _, _, _ = injected_dependencies()
    factory = AgentFactory({"expert": settings, "reviewer": settings.model_copy(update={
        "agent_name": "factory-reviewer",
        "auth": settings.auth.model_copy(update={"grants": []}),
    })}, dependencies={"expert": first, "reviewer": second})
    expert, reviewer = factory.create("expert"), factory.create("reviewer")
    assert expert.settings.agent_name == "enterprise-scale-ai-factory"
    assert reviewer.settings.agent_name == "factory-reviewer"
    assert expert.knowledge() is not reviewer.knowledge()
    assert expert.operation_store() is not reviewer.operation_store()
    assert settings.auth.grants
    with pytest.raises(ValueError, match="Unknown agent"):
        factory.create("missing")


def test_factory_rejects_ambiguous_duplicate_agent_storage_identity(settings):
    with pytest.raises(ValueError, match="distinct"):
        AgentFactory({"one": settings, "two": settings})


def test_app_routes_use_injected_services_without_patch_or_cloud(settings):
    settings = settings.model_copy(update={"auth": settings.auth.model_copy(update={
        "client_id": CLIENT, "audience": "api://" + CLIENT,
    })})
    dependencies, knowledge, store, conversation = injected_dependencies()
    app = create_app(settings, services=AgentServices(settings, dependencies=dependencies))
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-only"}
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
        assert client.get("/api/operations", headers=headers).json() == {"operations": []}
        result = client.post("/api/chat", headers=headers, json={
            "question": "Question", "audience": "project", "scope_key": SCOPE,
        })
        assert result.status_code == 200 and result.json() == {"answer": "injected"}
    dependencies.authenticate.assert_called()
    conversation.answer.assert_called_once()
    assert dependencies.knowledge_factory.call_count == 1
    assert dependencies.operation_store_factory.call_count == 1


def test_different_settings_cannot_be_injected_into_app(settings):
    services = AgentServices(settings)
    with pytest.raises(ValueError, match="settings"):
        create_app(settings.model_copy(update={"agent_name": "other-agent"}), services=services)


def test_agent_operation_namespaces_do_not_expose_another_agents_approval(settings):
    from aifactory_agent.operations import MemoryOperationBackend, OperationError, OperationStore
    from aifactory_agent.tools import CONFIGURE_TOOL
    from test_tools import preview, request
    backend = MemoryOperationBackend()
    caller = Principal(TENANT, CALLER)
    first = OperationStore(settings, backend=backend)
    other_settings = settings.model_copy(update={"agent_name": "factory-reviewer"})
    second = OperationStore(other_settings, backend=backend)
    pending = first.propose(caller, SCOPE, CONFIGURE_TOOL, request(settings), preview())
    assert second.list(caller) == []
    with pytest.raises(OperationError):
        second.read(caller, pending["id"])
    record, _ = backend.read(first._key(caller, pending["id"]))
    backend.create(second._key(caller, pending["id"]), record)
    with pytest.raises(OperationError, match="agent"):
        second.approve(caller, pending["id"], pending["plan_hash"])


def test_factory_api_and_cost_adapters_accept_constructor_injection(settings):
    from aifactory_agent.tools import FactoryTools
    client = Mock()
    client.health.return_value = {"status": "healthy"}
    client.creation_capabilities.return_value = {"supported": True}
    factory = Mock(return_value=client)
    costs = Mock()
    costs.execute.return_value = {"ok": True, "data": {"basis": "actual"}}
    grants = [settings.auth.grants[0].model_copy(update={
        "permissions": settings.auth.grants[0].permissions + ["cost.read"],
    })]
    settings = settings.model_copy(update={"auth": settings.auth.model_copy(update={"grants": grants})})
    tools = FactoryTools(settings, Principal(TENANT, CALLER), SCOPE,
                         client_factory=factory, key_provider=lambda: "test-only",
                         cost_factory=lambda configured, principal, scope, cred: costs)
    assert tools.execute("factory_health", {})["data"]["status"] == "healthy"
    assert tools.execute("factory_capabilities", {})["ok"]
    assert factory.call_args.args == (settings.factory.api_url, "test-only", 60)
    assert tools.execute("cost_default_project_idle", {})["data"]["basis"] == "actual"


def test_default_model_tool_composition_uses_injected_cost_factory(settings):
    dependencies, _, _, _ = injected_dependencies()
    grant = settings.auth.grants[0].model_copy(update={"permissions": ["factory.read", "cost.read"]})
    settings = settings.model_copy(update={"auth": settings.auth.model_copy(update={"grants": [grant]})})
    dependencies = AgentDependencies(
        operation_store_factory=dependencies.operation_store_factory,
        cost_factory=dependencies.cost_factory,
    )
    dependencies.cost_factory.return_value.execute.return_value = {"ok": True, "data": {"basis": "injected"}}
    services = AgentServices(settings, dependencies=dependencies)
    assert services.tools(Principal(TENANT, CALLER), SCOPE).execute(
        "cost_default_project_idle", {},
    )["data"]["basis"] == "injected"
    dependencies.cost_factory.assert_called_once()


def test_tool_audit_accepts_injected_storage_without_credential_construction(settings):
    from aifactory_agent.audit import ToolAudit
    container = Mock()
    caller = Principal(TENANT, CALLER)
    audit = ToolAudit(settings, caller, SCOPE, "correlation", container=container)
    with audit.operation("factory_health") as event:
        event["outcome"] = "completed"
    blob = container.get_blob_client.call_args.args[0]
    assert settings.agent_name in blob
    container.get_blob_client.return_value.upload_blob.assert_called_once()


def test_request_service_override_owns_conversation_tools_not_mutable_app_state(settings):
    from aifactory_agent import web
    dependencies, knowledge, _, conversation = injected_dependencies()
    other_dependencies, _, _, _ = injected_dependencies()
    def build(configured, evidence, tools):
        conversation.answer.side_effect = lambda question, audience, principal, scope: (
            tools(principal, scope) and {"answer": "request-local"}
        )
        return conversation
    dependencies = AgentDependencies(
        knowledge_factory=dependencies.knowledge_factory,
        operation_store_factory=dependencies.operation_store_factory,
        tool_factory=dependencies.tool_factory,
        conversation_factory=build,
        authenticate=dependencies.authenticate,
    )
    current = AgentServices(settings, dependencies=dependencies)
    application = web.create_app(settings, services=AgentServices(settings, dependencies=other_dependencies))
    application.dependency_overrides[web.get_services] = lambda: current
    with TestClient(application) as client:
        response = client.post("/api/chat", headers={"Authorization": "Bearer test-only"}, json={
            "question": "Question", "audience": "platform", "scope_key": SCOPE,
        })
        assert response.status_code == 200 and response.json()["answer"] == "request-local"
    dependencies.tool_factory.assert_called_once()
    other_dependencies.tool_factory.assert_not_called()


def test_project_template_skill_uses_injected_strategy_without_factory_api(settings):
    dependencies, _, store, _ = injected_dependencies()
    workload = Mock()
    caller = Principal(TENANT, CALLER)
    name = "create-agent-oftype-for-project"
    grant = settings.auth.grants[0].model_copy(update={"permissions": ["factory.read", "agent.create"]})
    settings = settings.model_copy(update={
        "auth": settings.auth.model_copy(update={"grants": [grant]}),
        "workloads": settings.workloads.model_copy(update={"enabled_skills": [name]}),
    })
    workload.prepare.return_value = {
        "id": "88888888-8888-4888-8888-888888888888", "plan_hash": "a" * 64,
        "tenant_id": caller.tenant_id, "object_id": caller.object_id,
        "scope_key": SCOPE, "tool_name": name, "status": "pending",
    }
    factory = Mock(return_value=workload)
    dependencies = AgentDependencies(
        operation_store_factory=dependencies.operation_store_factory,
        workload_factory=factory,
        authenticate=dependencies.authenticate,
    )
    project_id = (f"/subscriptions/{settings.scopes[SCOPE].subscription_id}"
                  f"/resourceGroups/{settings.scopes[SCOPE].resource_group}"
                  "/providers/Microsoft.CognitiveServices/accounts/example/projects/example")
    app = create_app(settings, services=AgentServices(settings, dependencies=dependencies))
    with TestClient(app) as client:
        response = client.post(f"/api/skills/{name}/propose", headers={"Authorization": "Bearer test-only"},
                               json={"scope_key": SCOPE, "arguments": {
                                   "type": "41-single-agent", "project_resource_id": project_id,
                               }})
        assert response.status_code == 201
    workload.prepare.assert_called_once_with(name, {"type": "41-single-agent", "project_resource_id": project_id})
    factory.assert_called_once()
    store.approve.assert_not_called()
    store.execute.assert_not_called()


def test_template_discovery_is_read_only_and_dependency_injected(settings):
    dependencies, _, store, _ = injected_dependencies()
    workload = Mock()
    workload.discover.return_value = [{"kind": "model", "type": "regression", "serving_mode": "batch",
                                      "available": False, "blockers": ["workload_profile_required"]}]
    dependencies = AgentDependencies(
        operation_store_factory=dependencies.operation_store_factory,
        workload_factory=Mock(return_value=workload),
        authenticate=dependencies.authenticate,
    )
    app = create_app(settings, services=AgentServices(settings, dependencies=dependencies))
    with TestClient(app) as client:
        response = client.get("/api/templates", params={"scope_key": SCOPE},
                              headers={"Authorization": "Bearer test-only"})
        assert response.status_code == 200 and response.json()["templates"][0]["type"] == "regression"
    workload.discover.assert_called_once()
    workload.prepare.assert_not_called()
    store.ensure_ready.assert_not_called()
    store.execute.assert_not_called()


def test_workload_target_and_type_inputs_are_closed_before_injected_provider(settings):
    from aifactory_agent.tools import FactoryTools
    from aifactory_agent.workloads import AGENT_CREATE
    caller = Principal(TENANT, CALLER)
    grant = settings.auth.grants[0].model_copy(update={"permissions": ["factory.read", "agent.create"]})
    settings = settings.model_copy(update={
        "auth": settings.auth.model_copy(update={"grants": [grant]}),
        "workloads": settings.workloads.model_copy(update={"enabled_skills": [AGENT_CREATE]}),
    })
    factory = Mock(side_effect=AssertionError("Invalid input must not construct the provider"))
    tools = FactoryTools(settings, caller, SCOPE, workload_factory=factory)
    from aifactory_agent.tools import ToolError
    for arguments in ({"type": "..\\other", "project_resource_id": "invalid"},
                      {"type": "41-single-agent", "project_resource_id": "invalid", "execute": True}):
        with pytest.raises(ToolError, match="schema"):
            tools.prepare_skill(AGENT_CREATE, arguments)
    factory.assert_not_called()
