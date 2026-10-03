import copy
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, RateLimitError

from aifactory_agent import foundry
from aifactory_agent.config import load_settings
from aifactory_agent.knowledge import IndexingError
from aifactory_agent.security import Principal


EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"
SCOPE = "project001-dev"


@pytest.fixture
def settings():
    return load_settings(EXAMPLE)


def caller(settings, **changes):
    return Principal(
        **{
            "tenant_id": settings.tenant_id,
            "object_id": str(settings.auth.grants[0].object_id),
            "scopes": frozenset({SCOPE}),
            "permissions": frozenset({"knowledge.read", "factory.read", "cost.read"}),
            **changes,
        }
    )


def document(identifier="source-1"):
    return {
        "id": identifier, "content": f"Evidence for {identifier}",
        "source_path": "documentation/factory.md", "source_url": "https://example.com/factory",
        "source_type": "current_guidance", "heading": "Factory", "line_start": 1, "line_end": 2,
    }


class FakeKnowledge:
    def __init__(self, status=None, batches=None):
        self.readiness = status if status is not None else {
            "status": "ready", "stale": False, "reconciliation_pending": False,
            "indexed_document_count": 2, "search_document_count": 2,
        }
        self.batches = batches if batches is not None else [[document()]]
        self.status_calls = 0
        self.searches = []

    def status(self):
        self.status_calls += 1
        return self.readiness.copy()

    def search(self, question, scope_key):
        self.searches.append((question, scope_key))
        return copy.deepcopy(self.batches[min(len(self.searches) - 1, len(self.batches) - 1)])


class FakeItem:
    type = "function_call"

    def __init__(self, name, arguments=None, call_id=None):
        self.name = name
        self.arguments = json.dumps(arguments if arguments is not None else {})
        self.call_id = call_id or f"call-{name}"

    def model_dump(self, *, exclude_none):
        return {
            "type": self.type, "name": self.name,
            "arguments": self.arguments, "call_id": self.call_id,
        }


def response(text="An evidenced answer [S1].", *, calls=(), status="completed", identifier="reply"):
    return SimpleNamespace(
        id=identifier, status=status, output_text=text, output=list(calls),
        usage=SimpleNamespace(input_tokens=10, output_tokens=3),
    )


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def respond(self, messages, reference):
        self.requests.append((copy.deepcopy(messages), reference.copy()))
        selected = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        if isinstance(selected, Exception):
            raise selected
        return selected


class FakeGateway:
    def __init__(self, responses=None):
        self.responses = responses if responses is not None else [response()]
        self.settings = []
        self.sessions = []
        self.closed = 0

    @contextmanager
    def open(self, settings):
        self.settings.append(settings)
        session = FakeSession(self.responses)
        self.sessions.append(session)
        try:
            yield session
        finally:
            self.closed += 1


class FakeTools:
    def __init__(self, descriptors=None, result=None):
        self.available = descriptors if descriptors is not None else foundry.factory_tools()
        self.result = result if result is not None else {"ok": True}
        self.executions = []

    def descriptors(self):
        return copy.deepcopy(self.available)

    def execute(self, name, arguments):
        self.executions.append((name, arguments))
        return self.result.copy()


class FakeAudit:
    def __init__(self):
        self.events = []

    @contextmanager
    def operation(self, name, call_id=None):
        event = {"name": name, "call_id": call_id, "outcome": "failed"}
        self.events.append(event)
        yield event


def injected(settings, *, knowledge=None, gateway=None, tools=None):
    knowledge = knowledge if knowledge is not None else FakeKnowledge()
    gateway = gateway if gateway is not None else FakeGateway()
    tools = tools if tools is not None else FakeTools()
    tool_requests, audit_requests, live_requests, audits = [], [], [], []

    def tool_factory(principal, scope_key):
        tool_requests.append((principal, scope_key))
        return tools

    def audit_factory(current_settings, principal, scope_key, correlation):
        audit_requests.append((current_settings, principal, scope_key, correlation))
        audit = FakeAudit()
        audits.append(audit)
        return audit

    def live_state_reader(current_settings, scope_key):
        live_requests.append((current_settings, scope_key))
        return {"source_type": "live_observation", "installed_factory_version": "unknown"}

    conversation = foundry.Conversation(
        settings, knowledge, tool_factory=tool_factory, model_gateway=gateway,
        audit_factory=audit_factory, live_state_reader=live_state_reader,
    )
    return SimpleNamespace(
        conversation=conversation, knowledge=knowledge, gateway=gateway, tools=tools,
        tool_requests=tool_requests, audit_requests=audit_requests,
        live_requests=live_requests, audits=audits,
    )


def test_fully_injected_answer_needs_no_cloud_constructors_or_monkeypatch(settings):
    knowledge = FakeKnowledge(batches=[[document()], [document(), document("source-2")]])
    calls = [
        FakeItem("knowledge_search", {"query": "More evidence"}),
        FakeItem("knowledge_status"), FakeItem("azure_live_state"), FakeItem("factory_health"),
    ]
    harness = injected(settings, knowledge=knowledge, gateway=FakeGateway([
        response(calls=calls), response("Evidence [S1] and [S2]."),
    ]))
    principal = caller(settings)
    result = harness.conversation.answer("How does the factory work?", "project", principal, SCOPE)

    assert result["answer"] == "Evidence [S1] and [S2]."
    assert result["model_usage"] == {"input_tokens": 20, "output_tokens": 6}
    assert [item["citation_id"] for item in result["citations"]] == ["S1", "S2"]
    assert all("content" not in item for item in result["citations"])
    assert harness.knowledge.searches == [
        ("How does the factory work?", SCOPE), ("More evidence", SCOPE),
    ]
    assert harness.tool_requests == [(principal, SCOPE)]
    assert harness.tools.executions == [("factory_health", {})]
    assert harness.live_requests == [(settings, SCOPE)]
    assert harness.audit_requests == [(settings, principal, SCOPE, result["correlation_id"])]
    assert all(event["outcome"] == "completed" for event in harness.audits[0].events)
    assert [item["name"] for item in result["tool_activity"]] == [call.name for call in calls]
    assert harness.gateway.closed == 1
    user_message = json.loads(harness.gateway.sessions[0].requests[0][0][1]["content"][0]["text"])
    assert user_message["retrieved_evidence_data"]["evidence"][0]["citation_id"] == "S1"
    outputs = [item for item in harness.gateway.sessions[0].requests[1][0]
               if item["type"] == "function_call_output"]
    assert [item["call_id"] for item in outputs] == [call.call_id for call in calls]


def test_two_agents_keep_settings_and_versioned_model_references_independent(settings):
    first = settings.model_copy(update={"agent_name": "first-agent", "agent_version": "7"})
    second = settings.model_copy(update={
        "agent_name": "second-agent", "agent_version": None,
        "azure": settings.azure.model_copy(update={"model_deployment": "second-model"}),
    })
    first_harness, second_harness = injected(first), injected(second)
    for harness, configured in ((first_harness, first), (second_harness, second)):
        harness.conversation.answer("Explain setup", "platform", caller(configured), SCOPE)
        assert harness.gateway.settings == [configured]
    assert first_harness.gateway.sessions[0].requests[0][1] == {
        "type": "agent_reference", "name": "first-agent", "version": "7",
    }
    assert second_harness.gateway.sessions[0].requests[0][1] == {
        "type": "agent_reference", "name": "second-agent",
    }


@pytest.mark.parametrize("failure", ["scope", "tenant", "caller", "revoked", "cross_scope"])
def test_current_settings_authorization_cannot_be_bypassed_by_injected_dependencies(settings, failure):
    principal, scope_key = caller(settings), SCOPE
    if failure == "scope":
        scope_key = "another-project"
    elif failure == "tenant":
        principal = caller(settings, tenant_id="11111111-1111-4111-8111-111111111111")
    elif failure == "caller":
        principal = caller(settings, object_id="22222222-2222-4222-8222-222222222222")
    elif failure == "revoked":
        settings = settings.model_copy(update={"auth": settings.auth.model_copy(update={"grants": []})})
    else:
        settings = settings.model_copy(update={
            "scopes": {**settings.scopes, "other-scope": settings.scopes[SCOPE]},
            "auth": settings.auth.model_copy(update={
                "grants": [settings.auth.grants[0].model_copy(update={"scopes": ["other-scope"]})],
            }),
        })
    harness = injected(settings)
    with pytest.raises(PermissionError):
        harness.conversation.answer("Explain setup", "platform", principal, scope_key)
    assert harness.knowledge.status_calls == 0
    assert not harness.tool_requests and not harness.audit_requests and not harness.gateway.sessions


@pytest.mark.parametrize("count", [None, 0, -1, True, 1.0, "1"])
def test_empty_or_invalid_knowledge_cannot_start_inference(settings, count):
    status = {"status": "ready", "stale": False, "reconciliation_pending": False}
    if count is not None:
        status["indexed_document_count"] = count
    harness = injected(settings, knowledge=FakeKnowledge(status=status))
    with pytest.raises(IndexingError):
        harness.conversation.answer("Explain setup", "platform", caller(settings), SCOPE)
    assert not harness.knowledge.searches and not harness.audit_requests and not harness.gateway.sessions


@pytest.mark.parametrize("changes", [
    {"status": "refresh_incomplete"}, {"stale": True}, {"reconciliation_pending": True},
    {"search_document_count": 1}, {"search_document_count": True},
])
def test_unready_or_unreconciled_knowledge_fails_closed(settings, changes):
    knowledge = FakeKnowledge()
    knowledge.readiness.update(changes)
    harness = injected(settings, knowledge=knowledge)
    with pytest.raises(IndexingError):
        harness.conversation.answer("Explain setup", "project", caller(settings), SCOPE)
    assert not harness.gateway.sessions


def test_legacy_ready_status_without_search_count_remains_compatible(settings):
    knowledge = FakeKnowledge()
    del knowledge.readiness["search_document_count"]
    harness = injected(settings, knowledge=knowledge)
    assert harness.conversation.answer("Explain setup", "project", caller(settings), SCOPE)["answer"]


@pytest.mark.parametrize("name", [
    "factory_prepare_settings", "factory_prepare_skill", "factory_approve_operation",
    "factory_execute_operation", "factory_delete", "create_agent_oftype_for_project",
    "create_ml_model_oftype_for_project", "arbitrary_shell",
])
def test_model_cannot_execute_writes_even_when_injected_tools_advertise_them(settings, name):
    tools = FakeTools(descriptors=[foundry.function(name, "Malicious write exposure")])
    harness = injected(settings, tools=tools, gateway=FakeGateway([response(calls=[FakeItem(name)])]))
    with pytest.raises(PermissionError, match="read-only"):
        harness.conversation.answer("Run it", "platform", caller(settings), SCOPE)
    assert not tools.executions and harness.gateway.closed == 1


def test_read_allowlist_intersects_actual_descriptors(settings):
    harness = injected(
        settings, tools=FakeTools(descriptors=[]),
        gateway=FakeGateway([response(calls=[FakeItem("factory_health")])]),
    )
    with pytest.raises(PermissionError):
        harness.conversation.answer("Read health", "platform", caller(settings), SCOPE)
    assert not harness.tools.executions


@pytest.mark.parametrize("descriptor", foundry.factory_tools(), ids=lambda item: item["name"])
def test_all_existing_authorized_read_tool_names_remain_callable(settings, descriptor):
    name = descriptor["name"]
    arguments = {}
    if name == "factory_operation_status":
        arguments = {"operation_id": "22222222-2222-4222-8222-222222222222"}
    elif name in {"cost_common_idle", "cost_monthly_project_forecast"}:
        arguments = {"resource_group": settings.scopes[SCOPE].resource_group}
    harness = injected(settings, gateway=FakeGateway([
        response(calls=[FakeItem(name, arguments)]), response(),
    ]))
    harness.conversation.answer("Read state", "project", caller(settings), SCOPE)
    assert harness.tools.executions == [(name, arguments)]


def test_injected_descriptors_cannot_expand_canonical_read_argument_schema(settings):
    tools = FakeTools(descriptors=[
        foundry.function("factory_health", "Read", {"scope_key": {"type": "string"}}),
    ])
    harness = injected(settings, tools=tools, gateway=FakeGateway([
        response(calls=[FakeItem("factory_health", {"scope_key": "another-project"})]),
    ]))
    with pytest.raises(ValueError):
        harness.conversation.answer("Read health", "platform", caller(settings), SCOPE)
    assert not tools.executions


@pytest.mark.parametrize("name", ["factory_health", "azure_live_state", "cost_default_project_idle"])
def test_injected_tools_cannot_bypass_current_read_permissions(settings, name):
    settings = settings.model_copy(update={
        "auth": settings.auth.model_copy(update={
            "grants": [settings.auth.grants[0].model_copy(update={"permissions": ["knowledge.read"]})],
        }),
    })
    harness = injected(settings, gateway=FakeGateway([response(calls=[FakeItem(name)])]))
    with pytest.raises(PermissionError):
        harness.conversation.answer("Read state", "platform", caller(settings), SCOPE)
    assert not harness.tools.executions and not harness.live_requests


@pytest.mark.parametrize("name", ["knowledge_search", "knowledge_status", "azure_live_state", "factory_health"])
def test_tool_arguments_cannot_override_scope_even_with_fake_backends(settings, name):
    arguments = {"scope_key": "another-project"}
    if name == "knowledge_search":
        arguments["query"] = "setup"
    harness = injected(settings, gateway=FakeGateway([response(calls=[FakeItem(name, arguments)])]))
    with pytest.raises(ValueError):
        harness.conversation.answer("Explain setup", "project", caller(settings), SCOPE)
    assert len(harness.knowledge.searches) == 1
    assert not harness.tools.executions and not harness.live_requests


@pytest.mark.parametrize("text", ["Fabricated citation [S99].", "Answer without citations.", ""])
def test_citations_and_nonempty_answer_are_required(settings, text):
    harness = injected(settings, gateway=FakeGateway([response(text)]))
    with pytest.raises(RuntimeError):
        harness.conversation.answer("Explain setup", "project", caller(settings), SCOPE)
    assert harness.gateway.closed == 1


def test_no_matching_evidence_allows_an_explicit_uncertainty_answer(settings):
    harness = injected(
        settings, knowledge=FakeKnowledge(batches=[[]]),
        gateway=FakeGateway([response("The documentation does not establish this.")]),
    )
    result = harness.conversation.answer("What is installed?", "project", caller(settings), SCOPE)
    assert result["citations"] == []
    assert result["answer"] == "The documentation does not establish this."


def test_citation_ids_do_not_leak_between_requests(settings):
    harness = injected(settings, gateway=FakeGateway([response("Evidence [S2].")]))
    harness.knowledge.batches = [[document(), document("source-2")], [document("source-3")]]
    first = harness.conversation.answer("First question", "project", caller(settings), SCOPE)
    assert [item["citation_id"] for item in first["citations"]] == ["S1", "S2"]
    with pytest.raises(RuntimeError, match="unsupported source citation"):
        harness.conversation.answer("Second question", "project", caller(settings), SCOPE)


@pytest.mark.parametrize("limit", [1, 3])
def test_model_tool_rounds_are_bounded(settings, limit):
    settings = settings.model_copy(update={"max_tool_rounds": limit})
    harness = injected(settings, gateway=FakeGateway([response(calls=[FakeItem("factory_health")])]))
    with pytest.raises(RuntimeError, match="bounded tool-call limit"):
        harness.conversation.answer("Read health", "platform", caller(settings), SCOPE)
    assert len(harness.gateway.sessions[0].requests) == limit
    assert len(harness.tools.executions) == limit
    assert harness.gateway.closed == 1


def test_incomplete_response_never_claims_success(settings):
    harness = injected(settings, gateway=FakeGateway([response(status="incomplete")]))
    with pytest.raises(RuntimeError, match="did not complete"):
        harness.conversation.answer("Explain setup", "project", caller(settings), SCOPE)


def test_read_tool_failure_is_audited_and_returned_as_data(settings):
    harness = injected(
        settings, tools=FakeTools(result={"ok": False, "error": "not available"}),
        gateway=FakeGateway([response(calls=[FakeItem("factory_health")]), response()]),
    )
    harness.conversation.answer("Read health", "project", caller(settings), SCOPE)
    assert harness.audits[0].events[-1]["outcome"] == "failed"
    messages = harness.gateway.sessions[0].requests[1][0]
    assert json.loads(messages[-1]["output"]) == {"ok": False, "error": "not available"}


def test_concurrent_requests_do_not_share_principals_or_correlations(settings):
    second_id = "22222222-2222-4222-8222-222222222222"
    settings = settings.model_copy(update={
        "auth": settings.auth.model_copy(update={
            "grants": [settings.auth.grants[0],
                       settings.auth.grants[0].model_copy(update={"object_id": second_id})],
        }),
    })
    barrier = Barrier(2)
    harness = injected(settings)
    gateway = harness.gateway

    @contextmanager
    def open_session(current_settings):
        session = FakeSession([response(calls=[FakeItem("factory_health")]), response()])
        gateway.sessions.append(session)
        barrier.wait(timeout=5)
        yield session

    gateway.open = open_session

    def tools_for(principal, scope_key):
        return FakeTools(result={"ok": True, "caller": principal.object_id})

    harness.conversation.tool_factory = tools_for
    principals = [caller(settings), caller(settings, object_id=second_id)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(harness.conversation.answer, "Read health", "project", principal, SCOPE)
                   for principal in principals]
        results = [future.result(timeout=10) for future in futures]
    assert len({result["correlation_id"] for result in results}) == 2
    assert {request[1].object_id for request in harness.audit_requests} == {
        principal.object_id for principal in principals
    }
    assert {json.loads(session.requests[1][0][-1]["output"])["caller"]
            for session in gateway.sessions} == {principal.object_id for principal in principals}


class FakeResponses:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def throttled(delay):
    return RateLimitError(
        "throttled", response=httpx.Response(
            429, headers={"retry-after": delay}, request=httpx.Request("POST", "https://example.com"),
        ), body=None,
    )


def test_real_gateway_uses_settings_and_closes_both_sdk_contexts(settings):
    sdk_calls, closed = [], []
    expected = response()
    model_client = SimpleNamespace(responses=FakeResponses([expected]))

    @contextmanager
    def openai_client(**kwargs):
        sdk_calls.append(("openai", kwargs))
        try:
            yield model_client
        finally:
            closed.append("openai")

    @contextmanager
    def project_client(**kwargs):
        sdk_calls.append(("project", kwargs))
        try:
            yield SimpleNamespace(get_openai_client=openai_client)
        finally:
            closed.append("project")

    token_credential = object()
    gateway = foundry.FoundryModelGateway(
        project_client_factory=project_client,
        credential_factory=lambda current: token_credential if current is settings else None,
    )
    messages, reference = [{"role": "user", "content": "question"}], {"name": settings.agent_name}
    with gateway.open(settings) as session:
        assert session.respond(messages, reference) is expected
    assert sdk_calls == [
        ("project", {"endpoint": settings.azure.project_endpoint, "credential": token_credential}),
        ("openai", {"timeout": 120, "max_retries": 0}),
    ]
    assert closed == ["openai", "project"]
    assert model_client.responses.requests == [{
        "input": messages, "extra_body": {"agent_reference": reference}, "store": False,
        "include": ["reasoning.encrypted_content"], "max_output_tokens": settings.max_output_tokens,
    }]


def test_throttles_are_bounded_by_attempts_and_total_wait(settings, monkeypatch):
    waits = []
    monkeypatch.setattr(foundry.time, "sleep", waits.append)
    client = SimpleNamespace(responses=FakeResponses([throttled("1"), throttled("2"), response()]))
    assert foundry.create_response(client, settings, [], {}) is not None
    assert waits == [1.0, 2.0] and len(client.responses.requests) == 3
    waits.clear()
    client = SimpleNamespace(responses=FakeResponses([throttled("1")] * 3))
    with pytest.raises(RateLimitError):
        foundry.create_response(client, settings, [], {})
    assert waits == [1.0, 1.0] and len(client.responses.requests) == 3


def test_throttle_wait_budget_never_sleeps_past_limit(settings, monkeypatch):
    waits = []
    monkeypatch.setattr(foundry.time, "sleep", waits.append)
    settings = settings.model_copy(update={"model_throttle_wait_seconds": 1})
    client = SimpleNamespace(responses=FakeResponses([throttled("1"), throttled("1")]))
    with pytest.raises(RateLimitError):
        foundry.create_response(client, settings, [], {})
    assert waits == [1.0] and len(client.responses.requests) == 2


@pytest.mark.parametrize("delay", ["invalid", "nan", "NaN", "inf", "Infinity"])
def test_nonfinite_or_invalid_throttle_delay_fails_without_sleep(settings, monkeypatch, delay):
    waits = []
    monkeypatch.setattr(foundry.time, "sleep", waits.append)
    client = SimpleNamespace(responses=FakeResponses([throttled(delay), response()]))
    with pytest.raises(RuntimeError, match="invalid throttle delay"):
        foundry.create_response(client, settings, [], {})
    assert waits == [] and len(client.responses.requests) == 1


def test_unknown_inference_failures_are_not_retried(settings, monkeypatch):
    waits = []
    monkeypatch.setattr(foundry.time, "sleep", waits.append)
    failure = APIConnectionError(request=httpx.Request("POST", "https://example.com"))
    client = SimpleNamespace(responses=FakeResponses([failure, response()]))
    with pytest.raises(APIConnectionError):
        foundry.create_response(client, settings, [], {})
    assert waits == [] and len(client.responses.requests) == 1


def test_conversation_does_not_retry_unknown_model_failures_and_closes_session(settings):
    failure = APIConnectionError(request=httpx.Request("POST", "https://example.com"))
    harness = injected(settings, gateway=FakeGateway([failure, response()]))
    with pytest.raises(APIConnectionError):
        harness.conversation.answer("Explain setup", "project", caller(settings), SCOPE)
    assert len(harness.gateway.sessions[0].requests) == 1
    assert harness.gateway.closed == 1


def test_existing_constructor_remains_lazy_and_read_only(settings):
    conversation = foundry.Conversation(settings, FakeKnowledge())
    assert conversation.settings is settings
    tools = conversation.tool_factory(caller(settings), SCOPE)
    assert {tool["name"] for tool in tools.descriptors()} == {
        tool["name"] for tool in foundry.factory_tools()
    }


def test_workload_actions_are_panel_instructions_not_model_tools():
    for command in (
        "/create-agent-oftype-for-project", "/create-ml-model-oftype-for-project",
    ):
        assert command in foundry.INSTRUCTIONS
    names = {tool["name"] for tool in foundry.knowledge_tools() + foundry.factory_tools()}
    assert not any("prepare" in name or "approve" in name or "execute" in name for name in names)
    assert "Chat remains read-only" in foundry.INSTRUCTIONS
