import asyncio
import copy
import importlib.util
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from aifactory_mcp import host


def tool(name="factory_health", read_only=True, schema=None):
    return SimpleNamespace(
        name=name,
        description=f"Read {name}.",
        annotations=SimpleNamespace(readOnlyHint=read_only),
        inputSchema=schema or {"type": "object", "properties": {}, "required": []},
    )


class Session:
    def __init__(self, tools=None):
        self.tools = tools if tools is not None else [tool()]
        self.discovery = []

    async def list_tools(self, cursor=None):
        self.discovery.append(cursor)
        return SimpleNamespace(tools=self.tools, nextCursor=None)


class Model:
    def __init__(self, *responses):
        self.responses = self
        self.outputs = list(responses)
        self.requests = []
        self.thread_ids = []

    def create(self, **kwargs):
        self.thread_ids.append(threading.get_ident())
        self.requests.append(copy.deepcopy(kwargs))
        return self.outputs.pop(0)


def response(*calls, text="", status="completed"):
    return SimpleNamespace(
        output=list(calls), output_text=text, status=status, id="response-id",
    )


def call(name="factory_health", arguments="{}", call_id="call-1"):
    return {
        "type": "function_call", "name": name,
        "arguments": arguments, "call_id": call_id,
    }


@pytest.fixture
def runtime():
    return SimpleNamespace(
        settings=SimpleNamespace(
            azure=SimpleNamespace(
                model_deployment="configured-gpt-6.1-sol",
                project_endpoint="https://example.services.ai.azure.com/api/projects/existing",
            ),
            agent_name="existing-factory-agent",
            max_tool_rounds=3,
            max_output_tokens=1800,
        ),
        foundry=SimpleNamespace(
            INSTRUCTIONS="Use evidence. Chat remains read-only: direct the user to the skills panel.",
            __file__="existing_agent\\aifactory_agent\\foundry.py",
        ),
    )


@pytest.fixture
def invocations(monkeypatch):
    observed = []

    async def invoke(session, name, arguments):
        observed.append((name, arguments))
        return {"ok": True, "health": "healthy"}

    monkeypatch.setattr(host, "invoke", invoke)
    return observed


def run(runtime, model, session=None, question="Report Factory API health using factory_health."):
    return asyncio.run(host.run_host(session or Session(), runtime, question, model_client=model))


def test_model_to_mcp_loop_preserves_reasoning_and_real_agent_instructions(runtime, invocations):
    reasoning = {"type": "reasoning", "id": "reason-1", "encrypted_content": "opaque", "summary": []}
    model = Model(response(reasoning, call()), response(text="LIVE OBSERVATION: API is healthy."))
    result = run(runtime, model)

    assert result["status"] == "completed"
    assert result["output"] == "LIVE OBSERVATION: API is healthy."
    assert result["model_deployment"] == "configured-gpt-6.1-sol"
    assert result["instructions_source"].endswith("aifactory_agent\\foundry.py")
    assert result["deployment_modified"] is False
    assert invocations == [("factory_health", {})]
    assert result["trace"][0]["name"] == "factory_health"
    assert result["trace"][0]["status"] == "completed"
    assert result["trace"][0]["result"]["ok"] is True
    first, second = model.requests
    assert first["instructions"].startswith(runtime.foundry.INSTRUCTIONS)
    assert "MCP" in first["instructions"]
    assert "skills panel" in first["instructions"]
    assert first["model"] == runtime.settings.azure.model_deployment
    assert first["max_output_tokens"] == runtime.settings.max_output_tokens
    assert first["store"] is False
    assert first["include"] == ["reasoning.encrypted_content"]
    assert "agent_reference" not in first.get("extra_body", {})
    assert reasoning in second["input"]
    outputs = [item for item in second["input"] if item.get("type") == "function_call_output"]
    assert json.loads(outputs[0]["output"])["health"] == "healthy"
    assert outputs[0]["call_id"] == "call-1"
    assert all(identifier != threading.get_ident() for identifier in model.thread_ids)


def test_discovery_filters_missing_false_annotations_and_all_action_tools(runtime, invocations):
    tools = [
        tool(), tool("factory_settings", True), tool("missing_hint", None),
        tool("writable", False), tool("factory_prepare", True),
        tool("factory_approval", True), tool("factory_approve", True),
        tool("factory_execute", True), tool("factory_cancel", True),
        tool("factory_cli_health", True), tool("integer_hint", 1),
    ]
    tools.append(SimpleNamespace(name="no_annotations", inputSchema={"type": "object"}))
    model = Model(response(text="Only approved reads are available."))
    run(runtime, model, Session(tools))
    assert {item["name"] for item in model.requests[0]["tools"]} == {
        "factory_health", "factory_settings",
    }
    assert invocations == []


@pytest.mark.parametrize("name", [
    "unknown_health", "factory_prepare", "factory_approve", "factory_approval",
    "factory_execute", "factory_cancel", "factory_cli_health",
])
def test_dispatch_rejects_hallucinated_or_forbidden_names(runtime, invocations, name):
    model = Model(response(call(name)))
    result = run(runtime, model)
    assert result["status"] == "error"
    assert result["output"] is None
    assert result["trace"][0]["status"] == "rejected"
    assert invocations == []
    assert len(model.requests) == 1


@pytest.mark.parametrize("arguments", [
    "{", "[]", '"text"', "null", "123", "true", '{"a": NaN}', '{"a":1,"a":2}',
    '{"a": 1e9999}',
])
def test_arguments_must_be_unambiguous_json_object(runtime, invocations, arguments):
    result = run(runtime, Model(response(call(arguments=arguments))))
    assert result["status"] == "error"
    assert result["output"] is None
    assert result["trace"][0]["status"] == "rejected"
    assert invocations == []


def test_mcp_error_is_failure_not_fallback_success(runtime, monkeypatch):
    async def fail(*args):
        raise host.ClientToolError("MCP denied the call")

    monkeypatch.setattr(host, "invoke", fail)
    model = Model(response(call()))
    result = run(runtime, model)
    assert result["status"] == "error"
    assert result["trace"][0]["status"] == "error"
    assert result["output"] is None
    assert len(model.requests) == 1


def test_negative_tool_observation_is_not_success(runtime, monkeypatch):
    async def fail(*args):
        return {"ok": False, "error": "Upstream failed"}

    monkeypatch.setattr(host, "invoke", fail)
    result = run(runtime, Model(response(call())))
    assert result["status"] == "error"
    assert result["trace"][0]["status"] == "error"
    assert result["trace"][0]["result"]["ok"] is False


def test_round_limit_stops_repeated_calls_with_trace(runtime, invocations):
    runtime.settings.max_tool_rounds = 2
    model = Model(response(call(call_id="first")), response(call(call_id="second")))
    result = run(runtime, model)
    assert result["status"] == "error"
    assert "limit" in result["error"].lower()
    assert result["output"] is None
    assert len(model.requests) == 2
    assert len(invocations) == len(result["trace"]) == 2


def test_no_read_only_tools_does_not_call_model(runtime, invocations):
    model = Model()
    result = run(runtime, model, Session([tool("factory_prepare", True)]))
    assert result["status"] == "error"
    assert "read-only" in result["error"]
    assert model.requests == []
    assert invocations == []


@pytest.mark.parametrize("question", ["", " ", "x" * 8001, None])
def test_invalid_question_rejected_before_discovery_or_model(runtime, question):
    session, model = Session(), Model()
    with pytest.raises(ValueError, match="1-8000"):
        run(runtime, model, session, question)
    assert not session.discovery
    assert not model.requests


def test_optional_input_schema_is_not_claimed_strict_and_not_mutated(runtime):
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Arguments",
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 5}},
        "required": ["query"],
    }
    original = copy.deepcopy(schema)
    model = Model(response(text="Ready."))
    run(runtime, model, Session([tool("knowledge_search", schema=schema)]))
    descriptor = model.requests[0]["tools"][0]
    assert descriptor["strict"] is False
    assert descriptor["parameters"]["required"] == ["query"]
    assert "$schema" not in descriptor["parameters"]
    assert schema == original


def test_paginated_discovery_includes_all_read_tools(runtime):
    class PaginatedSession(Session):
        async def list_tools(self, cursor=None):
            self.discovery.append(cursor)
            if cursor is None:
                return SimpleNamespace(tools=[tool()], nextCursor="page-2")
            return SimpleNamespace(tools=[tool("factory_capabilities")], nextCursor=None)

    session = PaginatedSession()
    model = Model(response(text="Ready."))
    run(runtime, model, session)
    assert session.discovery == [None, "page-2"]
    assert len(model.requests[0]["tools"]) == 2


@pytest.mark.parametrize("status,text", [("incomplete", "Partial"), ("failed", ""), ("completed", "")])
def test_incomplete_or_empty_model_response_is_not_success(runtime, status, text):
    result = run(runtime, Model(response(text=text, status=status)))
    assert result["status"] == "error"
    assert result["output"] is None


def test_unexpected_output_item_is_not_a_successful_read(runtime, invocations):
    result = run(runtime, Model(response({"type": "custom_tool_call", "name": "execute"}, text="Done.")))
    assert result["status"] == "error"
    assert invocations == []


def test_async_model_injection_is_supported(runtime):
    class AsyncModel(Model):
        async def create(self, **kwargs):
            self.requests.append(kwargs)
            return self.outputs.pop(0)

    result = run(runtime, AsyncModel(response(text="Ready.")))
    assert result["status"] == "completed"


@pytest.mark.parametrize("mode", ["duplicate", "repeated_cursor"])
def test_invalid_discovery_stops_before_model(runtime, mode):
    class InvalidSession(Session):
        async def list_tools(self, cursor=None):
            if mode == "duplicate":
                return SimpleNamespace(tools=[tool(), tool()], nextCursor=None)
            return SimpleNamespace(tools=[], nextCursor="repeated")

    model = Model()
    result = run(runtime, model, InvalidSession())
    assert result["status"] == "error"
    assert not model.requests


def test_replayed_tool_identifier_is_not_executed_again(runtime, invocations):
    model = Model(response(call()), response(call()))
    result = run(runtime, model)
    assert result["status"] == "error"
    assert len(invocations) == 1
    assert result["trace"][-1]["status"] == "rejected"


def test_default_model_opens_and_closes_off_event_loop(runtime, monkeypatch):
    model = Model(response(text="Ready."))
    lifecycle = []

    class Stack:
        def close(self):
            lifecycle.append(("close", threading.get_ident()))

    def open_model(actual_runtime):
        assert actual_runtime is runtime
        lifecycle.append(("open", threading.get_ident()))
        return model, Stack()

    monkeypatch.setattr(host, "_open_model", open_model)
    result = asyncio.run(host.run_host(Session(), runtime, "Health?"))
    assert result["status"] == "completed"
    assert [item[0] for item in lifecycle] == ["open", "close"]
    assert all(item[1] != threading.get_ident() for item in lifecycle)


@pytest.mark.parametrize("stage", ["discovery", "invoke", "model"])
def test_programming_errors_propagate_instead_of_claiming_service_failure(runtime, monkeypatch, stage):
    class BrokenSession(Session):
        async def list_tools(self, cursor=None):
            raise RuntimeError("programmer bug")

    class BrokenModel(Model):
        def create(self, **kwargs):
            raise RuntimeError("programmer bug")

    async def broken_invoke(*args):
        raise RuntimeError("programmer bug")

    session = BrokenSession() if stage == "discovery" else Session()
    model = BrokenModel() if stage == "model" else Model(response(call()))
    if stage == "invoke":
        monkeypatch.setattr(host, "invoke", broken_invoke)
    with pytest.raises(RuntimeError, match="programmer bug"):
        run(runtime, model, session)


@pytest.mark.parametrize("stage,code", [
    ("discovery", "mcp_discovery_failed"),
    ("invoke", "mcp_transport_failed"),
    ("model", "model_request_failed"),
])
def test_known_io_failures_have_sanitized_actionable_codes(runtime, monkeypatch, stage, code):
    class FailedSession(Session):
        async def list_tools(self, cursor=None):
            raise OSError("SECRET raw endpoint details")

    class FailedModel(Model):
        def create(self, **kwargs):
            raise OSError("SECRET raw endpoint details")

    async def failed_invoke(*args):
        raise OSError("SECRET raw endpoint details")

    session = FailedSession() if stage == "discovery" else Session()
    model = FailedModel() if stage == "model" else Model(response(call()))
    if stage == "invoke":
        monkeypatch.setattr(host, "invoke", failed_invoke)
    result = run(runtime, model, session)
    assert result["error_code"] == code
    assert "SECRET" not in json.dumps(result)
    assert result["status"] == "error"


@pytest.mark.parametrize("sdk", ["openai", "azure"])
def test_model_sdk_errors_are_sanitized(runtime, sdk):
    if sdk == "openai":
        from openai import OpenAIError
        error = OpenAIError("SECRET")
    else:
        from azure.core.exceptions import AzureError
        error = AzureError("SECRET")

    class FailedModel(Model):
        def create(self, **kwargs):
            raise error

    result = run(runtime, FailedModel())
    assert result["error_code"] == "model_request_failed"
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("stage", ["discovery", "invoke"])
def test_mcp_sdk_errors_are_sanitized(runtime, monkeypatch, stage):
    from mcp import McpError
    from mcp.types import ErrorData

    error = McpError(ErrorData(code=-32000, message="SECRET server detail"))

    class FailedSession(Session):
        async def list_tools(self, cursor=None):
            raise error

    async def failed_invoke(*args):
        raise error

    monkeypatch.setattr(host, "invoke", failed_invoke)
    session = FailedSession() if stage == "discovery" else Session()
    result = run(runtime, Model(response(call())), session)
    assert result["error_code"] == (
        "mcp_discovery_failed" if stage == "discovery" else "mcp_transport_failed"
    )
    assert "SECRET" not in json.dumps(result)


def example(name):
    path = Path(__file__).resolve().parents[1] / "usecase_code" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"example_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_foundry_example_defaults_to_preview_without_transport_or_model(runtime, monkeypatch, capsys):
    script = example("foundry_readonly")
    monkeypatch.setattr(script, "load_runtime", lambda *args, **kwargs: runtime)

    def unexpected(*args, **kwargs):
        pytest.fail("Preview must not open a transport or make a model request")

    monkeypatch.setattr(script, "connect_stdio", unexpected)
    monkeypatch.setattr(script, "run_host", unexpected)
    assert script.main([
        "--config", "existing.json", "--scope", "project001-dev", "--object-id", "operator",
        "--question", "Report Factory API health using factory_health.",
    ]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["status"] == "preview"
    assert preview["model_request_sent"] is False
    assert preview["model_deployment"] == runtime.settings.azure.model_deployment


def test_foundry_example_live_opt_in_uses_same_interpreter_and_scoped_server(
    runtime, monkeypatch, capsys,
):
    script = example("foundry_readonly")
    monkeypatch.setattr(script, "load_runtime", lambda *args, **kwargs: runtime)
    connected = []

    @asynccontextmanager
    async def connect(command, args, env=None):
        connected.append((command, args))
        yield "session"

    async def run_host(session, actual_runtime, question):
        assert session == "session"
        assert actual_runtime is runtime
        assert question == "Health?"
        return {"status": "completed", "output": "Healthy", "trace": []}

    monkeypatch.setattr(script, "connect_stdio", connect)
    monkeypatch.setattr(script, "run_host", run_host)
    assert script.main([
        "--config", "existing.json", "--scope", "project001-dev", "--object-id", "operator",
        "--question", "Health?", "--repository-root", str(Path.cwd()), "--live-read-only",
    ]) == 0
    command, args = connected[0]
    assert command == script.sys.executable
    assert args[:3] == ["-m", "aifactory_mcp", "serve"]
    assert args[args.index("--scope") + 1] == "project001-dev"
    assert args[args.index("--object-id") + 1] == "operator"
    assert "--repository-root" in args
    assert json.loads(capsys.readouterr().out)["status"] == "completed"


@pytest.mark.parametrize("name", ["foundry_readonly", "read_only_client"])
def test_examples_only_forward_explicitly_needed_credentials_to_local_server(
    name, runtime, monkeypatch, capsys,
):
    script = example(name)
    monkeypatch.setenv("AIFACTORY_API_KEY", "TEST-ONLY-NOT-A-REAL-KEY")
    monkeypatch.setenv("AZURE_CONFIG_DIR", "local-azure-config")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-be-forwarded")
    if name == "foundry_readonly":
        monkeypatch.setattr(script, "load_runtime", lambda *args, **kwargs: runtime)
    environments = []

    @asynccontextmanager
    async def connect(command, args, env=None):
        environments.append(env)
        yield Session([tool(), tool("factory_capabilities")])

    async def invoke(*args):
        return {"ok": True}

    async def run_host(*args):
        return {"status": "completed", "output": "Healthy"}

    monkeypatch.setattr(script, "connect_stdio", connect)
    if name == "foundry_readonly":
        monkeypatch.setattr(script, "run_host", run_host)
    else:
        monkeypatch.setattr(script, "invoke", invoke)
    args = ["--config", "existing.json", "--scope", "project001-dev", "--object-id", "operator"]
    if name == "foundry_readonly":
        args.extend(["--question", "Health?", "--live-read-only"])
    assert script.main(args) == 0
    assert environments[0]["AIFACTORY_API_KEY"] == "TEST-ONLY-NOT-A-REAL-KEY"
    assert environments[0]["AZURE_CONFIG_DIR"] == "local-azure-config"
    assert "UNRELATED_SECRET" not in environments[0]
    assert "TEST-ONLY-NOT-A-REAL-KEY" not in capsys.readouterr().out


def test_read_only_client_only_invokes_discovered_annotated_health_and_capabilities(
    monkeypatch, capsys,
):
    script = example("read_only_client")
    observed = []

    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield Session([
            tool(), tool("factory_capabilities"), tool("factory_cli_health"),
            tool("factory_prepare"), tool("factory_execute"),
        ])

    async def invoke(session, name, arguments):
        observed.append((name, arguments))
        return {"ok": True}

    monkeypatch.setattr(script, "connect_stdio", connect)
    monkeypatch.setattr(script, "invoke", invoke)
    assert script.main([
        "--config", "existing.json", "--scope", "project001-dev", "--object-id", "operator",
    ]) == 0
    assert observed == [("factory_health", {}), ("factory_capabilities", {})]
    assert json.loads(capsys.readouterr().out)["status"] == "completed"


@pytest.mark.parametrize("name", ["foundry_readonly", "read_only_client"])
def test_example_programming_errors_are_not_hidden(name, monkeypatch):
    script = example(name)

    async def broken_run(*args):
        raise RuntimeError("programmer bug")

    monkeypatch.setattr(script, "_run", broken_run)
    args = ["--config", "existing.json", "--scope", "project001-dev", "--object-id", "operator"]
    if name == "foundry_readonly":
        args.extend(["--question", "Health?"])
    with pytest.raises(RuntimeError, match="programmer bug"):
        script.main(args)
