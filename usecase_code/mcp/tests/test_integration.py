"""Real MCP transports and agent governance; only cloud/service boundaries are faked."""

import asyncio
import copy
import importlib
import ipaddress
import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import anyio
import httpx
import jwt
import pytest
import uvicorn
from mcp import ClientSession, McpError
from mcp.client import stdio
from mcp.shared.memory import create_connected_server_and_client_session

from aifactory_mcp.client import ClientToolError, connect_http, connect_stdio, invoke
from aifactory_mcp.host import run_host
from aifactory_mcp.server import create_http_app, create_server
from test_backend import setup_backend
from test_runtime import (
    CALLER, MCP, SCOPE, artifacts, config_path, configuration, runtime,
    security_fixtures, signing_key,
)


@pytest.fixture(autouse=True)
def loopback_only(monkeypatch):
    """Fail closed if an in-process integration accidentally reaches a cloud SDK."""
    for method in ("connect", "connect_ex"):
        original = getattr(socket.socket, method)

        def guarded(sock, address, _original=original):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                host = address[0]
                assert host == "localhost" or ipaddress.ip_address(host).is_loopback, (
                    "Integration tests may connect only to loopback services"
                )
            return _original(sock, address)

        monkeypatch.setattr(socket.socket, method, guarded)
    monkeypatch.setenv("AIFACTORY_API_KEY", "integration-test-api-key")


class RuntimeProbe:
    def __init__(self, actual, *, injected_backend=None, network=False):
        self.actual = actual
        self.injected_backend = injected_backend
        self.network = network
        self.callers = []

    def __getattr__(self, name):
        return getattr(self.actual, name)

    def local_principal(self, object_id):
        assert not self.network, "HTTP must never fall back to a local principal"
        return self.actual.local_principal(object_id)

    def backend(self, principal, scope_key):
        self.callers.append((principal.object_id, scope_key))
        if self.injected_backend is None:
            return self.actual.backend(principal, scope_key)
        selected = self.injected_backend
        if principal == selected.principal and scope_key == selected.scope_key:
            return selected
        from aifactory_mcp.backend import AgentBackend

        return AgentBackend(
            self.actual, principal, scope_key, operation_store=selected.operation_store,
            tools_factory=type(selected._tools),
        )


@pytest.fixture
def health_api():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.command, self.path))
            body = b'{"status":"integration-healthy"}'
            self.send_response(200 if self.path == "/health" else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


@pytest.fixture
def signed_token(runtime, signing_key, monkeypatch):
    def keys(url):
        assert url == (
            f"https://login.microsoftonline.com/{runtime.settings.tenant_id}/discovery/v2.0/keys"
        )
        return SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=signing_key.public_key())
        )

    monkeypatch.setattr(runtime.security, "_jwks_client", keys)

    def issue(**changes):
        return jwt.encode(
            security_fixtures.claims(**changes), signing_key, algorithm="RS256",
            headers={"kid": "integration-only"},
        )

    return issue


@pytest.fixture
def http_endpoint(runtime, signed_token):
    observed = RuntimeProbe(runtime, network=True)
    ready = threading.Event()
    failures = []

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{reserved.getsockname()[1]}/mcp"
        server = Server(uvicorn.Config(
            create_http_app(observed, SCOPE, resource_url=url),
            loop="asyncio", lifespan="on", ws="none", log_level="critical",
            access_log=False, timeout_graceful_shutdown=2,
        ))

        def run():
            try:
                server.run(sockets=[reserved])
            except BaseException as exc:
                failures.append(exc)
                ready.set()

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            assert ready.wait(timeout=15), "HTTP startup exceeded its bounded wait"
            assert not failures
            assert server.started and worker.is_alive()
            yield url, observed
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            if worker.is_alive():
                server.force_exit = True
                worker.join(timeout=5)
            assert not worker.is_alive(), "HTTP server did not stop"
            assert not failures


def rpc(method="tools/call", *, request_id=1):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if method == "tools/call":
        body["params"] = {"name": "factory_skills", "arguments": {}}
    return body


def http_headers(token=None, **extra):
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return {**headers, **extra}


def error_code(result):
    assert result.isError
    assert result.structuredContent["ok"] is False
    return result.structuredContent["error"]["code"]


@pytest.mark.anyio
async def test_stdio_subprocess_discovers_skills_and_reads_real_sdk_health(
    configuration, config_path, health_api, monkeypatch,
):
    url, calls = health_api
    configuration["factory"].update(api_url=url, writes_enabled=False)
    config_path.write_text(json.dumps(configuration), encoding="utf-8")
    children = []
    spawn = stdio._create_platform_compatible_process

    async def track_process(**kwargs):
        child = await spawn(**kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", track_process)
    env = {
        "PYTHONPATH": str(MCP / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "AIFACTORY_API_KEY": "integration-child-test-key",
    }
    args = [
        "-m", "aifactory_mcp", "serve", "--config", str(config_path),
        "--scope", SCOPE, "--object-id", CALLER,
    ]
    with anyio.fail_after(45):
        async with connect_stdio(sys.executable, args, env=env) as session:
            assert isinstance(session, ClientSession)
            assert len(children) == 1 and children[0].returncode is None
            tools = (await session.list_tools()).tools
            assert {"factory_health", "factory_skills"} <= {tool.name for tool in tools}
            assert not any("approv" in tool.name for tool in tools)
            skills = await invoke(session, "factory_skills", {})
            assert skills["ok"] is True and skills["data"]
            assert all(
                "writes_disabled" in item["blockers"]
                for item in skills["data"] if item["kind"] == "action"
            )
            assert calls == [], "Discovery and skill catalog must stay offline"
            health = await invoke(session, "factory_health", {})
            assert health["data"] == {"status": "integration-healthy"}
    assert calls == [("GET", "/health")]
    assert children[0].returncode is not None, "The official stdio context must reap its child"


def test_real_stdio_cli_keeps_structured_tool_failure(config_path):
    result = subprocess.run([
        sys.executable, "-m", "aifactory_mcp", "call", "unsupported_tool",
        "--config", str(config_path), "--scope", SCOPE, "--object-id", CALLER,
    ], capture_output=True, text=True, timeout=30, cwd=MCP)
    assert result.returncode == 1
    assert result.stdout == ""
    failure = json.loads(result.stderr.splitlines()[-1])
    assert failure["ok"] is False
    assert failure["result"]["error"]["code"] == "unsupported_tool"
    assert "ExceptionGroup" not in result.stderr


@pytest.mark.anyio
async def test_real_http_connection_preserves_tool_failure(http_endpoint, signed_token):
    url, _ = http_endpoint
    with anyio.fail_after(20):
        with pytest.raises(ClientToolError) as failure:
            async with connect_http(url, signed_token()) as session:
                await invoke(session, "unsupported_tool", {})
    assert failure.value.result["error"]["code"] == "unsupported_tool"


@pytest.mark.parametrize("bad_token", [False, True])
def test_http_cli_expected_connection_failure_has_no_traceback(http_endpoint, signed_token, monkeypatch, capsys, bad_token):
    from aifactory_mcp.__main__ import main

    url, _ = http_endpoint
    monkeypatch.setenv("AIFACTORY_MCP_TOKEN", "invalid-token" if bad_token
                       else signed_token(oid=security_fixtures.CLIENT))
    assert main(["tools", "--config", "unused", "--scope", SCOPE, "--url", url]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "AI Factory MCP failed" in captured.err
    assert "Traceback" not in captured.err and "invalid-token" not in captured.err


def test_http_cli_retains_actual_uncertain_operation(http_endpoint, signed_token, setup_backend, monkeypatch, capsys):
    from aifactory_mcp.__main__ import main
    from azurefactory.errors import RequestTimeout

    url, observed = http_endpoint
    backend, api, store = setup_backend
    record = backend.call_tool("factory_prepare_delete", {})["operation"]
    backend.approve(record["id"], record["plan_hash"], record["preview"]["confirmation_phrase"])
    calls = []

    def timeout(**kwargs):
        calls.append(kwargs)
        raise RequestTimeout("private details")

    monkeypatch.setattr(api, "delete_aifactory_confirm", timeout)
    monkeypatch.setattr(type(observed.actual), "backend", lambda self, principal, scope_key: backend)
    monkeypatch.setenv("AIFACTORY_MCP_TOKEN", signed_token())
    assert main([
        "call", "factory_execute_operation", "--config", "unused", "--scope", SCOPE,
        "--url", url, "--arguments", json.dumps({"operation_id": record["id"]}),
    ]) == 1
    captured = capsys.readouterr()
    output = json.loads(captured.err.splitlines()[-1])
    assert output["result"]["operation"]["id"] == record["id"]
    assert output["result"]["operation"]["status"] == "uncertain"
    assert output["result"]["error"]["code"] == "operation_uncertain"
    assert "private details" not in captured.err
    assert len(calls) == 1
    assert store.read(backend.principal, record["id"])["status"] == "uncertain"


@pytest.mark.anyio
async def test_streamable_http_concurrent_sessions_keep_verified_callers_separate(
    http_endpoint, signed_token,
):
    url, observed = http_endpoint
    both_connected = asyncio.Barrier(2)
    permitted_discovered = asyncio.Event()

    async def permitted():
        async with connect_http(url, signed_token()) as session:
            assert isinstance(session, ClientSession)
            await both_connected.wait()
            tools = await session.list_tools()
            assert "factory_skills" in {tool.name for tool in tools.tools}
            permitted_discovered.set()
            for _ in range(3):
                assert (await invoke(session, "factory_skills", {}))["ok"] is True

    async def ungranted():
        async with connect_http(url, signed_token(oid=security_fixtures.CLIENT)) as session:
            await both_connected.wait()
            await permitted_discovered.wait()
            for _ in range(3):
                result = await session.call_tool("factory_skills", {})
                assert error_code(result) == "forbidden"

    with anyio.fail_after(30):
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(permitted())
            tasks.create_task(ungranted())
    assert (CALLER, SCOPE) in observed.callers
    assert (security_fixtures.CLIENT, SCOPE) in observed.callers
    assert {scope for _, scope in observed.callers} == {SCOPE}


@pytest.mark.anyio
async def test_streamable_http_ungranted_discovery_reports_access_denied(
    http_endpoint, signed_token,
):
    url, _ = http_endpoint
    with anyio.fail_after(20):
        async with connect_http(url, signed_token(oid=security_fixtures.CLIENT)) as session:
            with pytest.raises(McpError) as denied:
                await session.list_tools()
    assert denied.value.error.code == -32001
    assert denied.value.error.message == "Access denied for this scope."


@pytest.mark.anyio
async def test_streamable_http_reauthenticates_each_request_on_reused_connection(
    http_endpoint, signed_token,
):
    url, observed = http_endpoint
    with anyio.fail_after(20):
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            for index, caller in enumerate((CALLER, security_fixtures.CLIENT, CALLER)):
                before = len(observed.callers)
                response = await client.post(
                    url, json=rpc(request_id=index + 1),
                    headers=http_headers(
                        signed_token(oid=caller), **{"Mcp-Session-Id": "untrusted-shared-session"},
                    ),
                )
                assert response.status_code == 200
                result = response.json()["result"]
                assert result["isError"] is (caller != CALLER)
                if caller == CALLER:
                    assert result["structuredContent"]["ok"] is True
                else:
                    assert result["structuredContent"]["error"]["code"] == "forbidden"
                # The SDK can lazily discover a schema on the first call; every lookup
                # for this HTTP request must nevertheless use its verified identity.
                assert observed.callers[before:]
                assert set(observed.callers[before:]) == {(caller, SCOPE)}
            for token in (None, signed_token(exp=1)):
                before = len(observed.callers)
                response = await client.post(
                    url, json=rpc(), headers=http_headers(
                        token, **{"Mcp-Session-Id": "untrusted-shared-session"},
                    ),
                )
                assert response.status_code == 401
                assert len(observed.callers) == before


@pytest.mark.anyio
@pytest.mark.parametrize("credential_case", ["missing", "expired", "wrong-audience"])
async def test_streamable_http_rejects_invalid_auth_on_every_method(
    http_endpoint, signed_token, credential_case,
):
    url, observed = http_endpoint
    token = {
        "missing": None, "expired": signed_token(exp=1),
        "wrong-audience": signed_token(aud="api://not-this-resource"),
    }[credential_case]
    with anyio.fail_after(20):
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            for method in ("GET", "POST", "DELETE"):
                response = await client.request(
                    method, url, json=rpc(), headers=http_headers(token),
                )
                assert response.status_code == 401
                assert response.json() == {"error": "authentication_required"}
                assert "resource_metadata" in response.headers["www-authenticate"]
    assert observed.callers == []


@pytest.mark.anyio
@pytest.mark.parametrize("header,value", [
    ("Origin", "https://attacker.invalid"),
    ("Host", "attacker.invalid"),
])
async def test_streamable_http_blocks_rebinding_before_tool_dispatch(
    http_endpoint, signed_token, header, value,
):
    url, observed = http_endpoint
    with anyio.fail_after(20):
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.post(
                url, json=rpc(), headers=http_headers(signed_token(), **{header: value}),
            )
            assert response.status_code == 403
            assert response.json() == {"error": "invalid_origin"}
    assert observed.callers == []


@pytest.mark.anyio
async def test_mcp_governed_delete_requires_human_approval_and_cannot_replay(
    runtime, setup_backend,
):
    backend, api, store = setup_backend
    observed = RuntimeProbe(runtime, injected_backend=backend)
    server = create_server(observed, SCOPE, object_id=CALLER)
    with anyio.fail_after(20):
        async with create_connected_server_and_client_session(server) as session:
            tools = (await session.list_tools()).tools
            assert not any("approv" in tool.name for tool in tools)
            assert error_code(await session.call_tool("factory_approve_operation", {})) == "unsupported_tool"
            record = (await invoke(session, "factory_prepare_delete", {}))["operation"]
            assert record["status"] == "pending"
            assert record["object_id"] == CALLER and record["scope_key"] == SCOPE
            assert store.read(backend.principal, record["id"])["plan_hash"] == record["plan_hash"]
            args = {"operation_id": record["id"]}
            assert error_code(await session.call_tool("factory_execute_operation", args)) == "approval_required"
            assert not any(call[0] == "delete_aifactory_confirm" for call in api.calls)
            # Explicit stand-in for human review outside MCP, never a model-callable tool.
            approved = backend.approve(
                record["id"], record["plan_hash"], record["preview"]["confirmation_phrase"],
            )
            assert approved["operation"]["status"] == "approved"
            execution = (await invoke(session, "factory_execute_operation", args))["operation"]
            assert execution["status"] == "running"
            assert execution["progress"]["completion_known"] is False
            assert error_code(await session.call_tool("factory_execute_operation", args)) == "approval_required"
            status = (await invoke(session, "factory_operation_status", args))["operation"]
            assert status["status"] == "succeeded"
            assert status["progress"]["completion_known"] is True
    assert sum(call[0] == "delete_aifactory_confirm" for call in api.calls) == 1
    assert [event["event"] for event in store.backend.events] == [
        "proposed", "approved", "executing", "running", "succeeded",
    ]
    assert set(observed.callers) == {(CALLER, SCOPE)}


@pytest.mark.anyio
async def test_mcp_operation_id_does_not_transfer_ownership_between_authorized_callers(
    runtime, setup_backend,
):
    backend, api, store = setup_backend
    grant = runtime.settings.auth.grants[0]
    runtime.settings.auth.grants.append(type(grant).model_validate({
        **grant.model_dump(mode="json"), "object_id": security_fixtures.CLIENT,
    }))
    observed = RuntimeProbe(runtime, injected_backend=backend)
    owner = create_server(observed, SCOPE, object_id=CALLER)
    other = create_server(observed, SCOPE, object_id=security_fixtures.CLIENT)
    with anyio.fail_after(20):
        async with (
            create_connected_server_and_client_session(owner) as first,
            create_connected_server_and_client_session(other) as second,
        ):
            record = (await invoke(first, "factory_prepare_delete", {}))["operation"]
            assert (await second.list_tools()).tools
            assert (await invoke(second, "factory_operations", {}))["data"] == []
            for name in (
                "factory_operation", "factory_operation_status",
                "factory_execute_operation", "factory_cancel_operation",
            ):
                denied = await second.call_tool(name, {"operation_id": record["id"]})
                assert error_code(denied) == "operation_not_found"
            assert (await invoke(first, "factory_operation", {"operation_id": record["id"]}))[
                "operation"
            ]["status"] == "pending"
    assert store.read(backend.principal, record["id"])["status"] == "pending"
    assert not any(call[0] == "delete_aifactory_confirm" for call in api.calls)


@pytest.mark.anyio
async def test_foundry_host_uses_real_instructions_mcp_and_factory_tools(
    runtime, setup_backend, monkeypatch,
):
    backend, api, store = setup_backend
    foundry = importlib.import_module("aifactory_agent.foundry")
    observations = []
    actual_health = api.health

    def health():
        observations.append("fake-api-health")
        return actual_health()

    monkeypatch.setattr(api, "health", health)

    class Responses:
        def __init__(self):
            self.requests = []
            self.responses = self

        def create(self, **kwargs):
            self.requests.append(copy.deepcopy(kwargs))
            if len(self.requests) == 1:
                return SimpleNamespace(status="completed", output_text="", output=[{
                    "type": "function_call", "name": "factory_health",
                    "arguments": "{}", "call_id": "integration-health",
                }])
            assert len(self.requests) == 2
            assert observations == ["fake-api-health"]
            outputs = [item for item in kwargs["input"] if item.get("type") == "function_call_output"]
            assert len(outputs) == 1
            assert outputs[0]["call_id"] == "integration-health"
            assert json.loads(outputs[0]["output"])["data"] == {"status": "ok"}
            return SimpleNamespace(
                status="completed", output=[],
                output_text="LIVE OBSERVATION: the test Factory API reports ok.",
            )

    model = Responses()
    observed = RuntimeProbe(runtime, injected_backend=backend)
    server = create_server(observed, SCOPE, object_id=CALLER)
    with anyio.fail_after(20):
        async with create_connected_server_and_client_session(server) as session:
            result = await run_host(
                session, runtime, "Use factory_health once to report Factory API health.",
                model_client=model,
            )
    assert result["status"] == "completed"
    assert result["deployment_modified"] is False
    assert Path(result["instructions_source"]).resolve() == Path(foundry.__file__).resolve()
    assert len(model.requests) == 2
    assert model.requests[0]["instructions"].startswith(foundry.INSTRUCTIONS)
    assert model.requests[0]["model"] == runtime.settings.azure.model_deployment
    assert model.requests[0]["store"] is False
    assert result["trace"] == [{
        "name": "factory_health", "call_id": "integration-health", "round": 1,
        "status": "completed", "arguments": {},
        "result": {"ok": True, "data": {"status": "ok"}},
    }]
    assert "factory_operation_status" not in result["available_tools"]
    assert not any(
        fragment in name
        for name in result["available_tools"]
        for fragment in ("prepare", "approv", "execute", "cancel")
    )
    assert observations == ["fake-api-health"]
    assert set(observed.callers) == {(CALLER, SCOPE)}
    assert api.calls == [] and store.backend.events == []
