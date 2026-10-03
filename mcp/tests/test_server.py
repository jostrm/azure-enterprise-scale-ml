import json
from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from aifactory_mcp.server import create_http_app, create_server


class Backend:
    def list_tools(self):
        return [{
            "name": "factory_health",
            "description": "Read API health",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": True},
        }]

    def call_tool(self, name, arguments):
        if name == "factory_health":
            return {"ok": True, "data": {"status": "healthy"}}
        raise AssertionError("Unknown tools must never reach the backend")


class Runtime:
    settings = SimpleNamespace(
        auth=SimpleNamespace(audience="api://mcp-test", required_scope="access_as_user"),
        tenant_id="11111111-1111-4111-8111-111111111111",
    )

    def __init__(self, backend=None):
        self.selected_backend = backend or Backend()
        self.callers = []

    def local_principal(self, object_id):
        return SimpleNamespace(object_id=object_id)

    def backend(self, principal, scope_key):
        self.callers.append((principal.object_id, scope_key))
        return self.selected_backend

    def principal_from_token(self, token):
        if token != "test-valid-token":
            raise PermissionError("sensitive token contents")
        return SimpleNamespace(object_id="verified-caller")


@pytest.mark.anyio
async def test_official_mcp_session_discovers_and_calls():
    runtime = Runtime()
    server = create_server(runtime, "project001-dev", object_id="local-operator")
    async with create_connected_server_and_client_session(server) as session:
        tools = await session.list_tools()
        assert tools.tools[0].name == "factory_health"
        assert tools.tools[0].annotations.readOnlyHint is True
        result = await session.call_tool("factory_health", {})
        assert not result.isError
        assert result.structuredContent == {"ok": True, "data": {"status": "healthy"}}
        assert ("local-operator", "project001-dev") in runtime.callers


@pytest.mark.anyio
async def test_unknown_tools_and_extra_arguments_are_protocol_errors():
    server = create_server(Runtime(), "project001-dev", object_id="operator")
    async with create_connected_server_and_client_session(server) as session:
        for name, arguments in (("factory_approve_operation", {}),
                                ("factory_health", {"url": "https://other.example"})):
            result = await session.call_tool(name, arguments)
            assert result.isError


@pytest.mark.anyio
async def test_failed_backend_envelope_is_not_success():
    class Failed(Backend):
        def call_tool(self, name, arguments):
            return {"ok": False, "error": {"code": "factory_timeout",
                                         "message": "Completion unknown; do not retry."}}
    server = create_server(Runtime(Failed()), "project001-dev", object_id="operator")
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("factory_health", {})
        assert result.isError
        assert result.structuredContent["error"]["code"] == "factory_timeout"


@pytest.mark.anyio
async def test_unexpected_error_does_not_disclose_exception():
    class Failed(Backend):
        def call_tool(self, name, arguments):
            raise RuntimeError("password=must-not-leak")
    server = create_server(Runtime(Failed()), "project001-dev", object_id="operator")
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("factory_health", {})
        assert result.isError
        assert "must-not-leak" not in result.model_dump_json()


def test_stdio_requires_explicit_local_identity():
    with pytest.raises(ValueError, match="identity"):
        create_server(Runtime(), "project001-dev")


@pytest.mark.anyio
async def test_http_requires_auth_and_rejects_bad_origin():
    app = create_http_app(Runtime(), "project001-dev",
                          resource_url="http://127.0.0.1:8899/mcp")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://127.0.0.1:8899") as client:
        response = await client.post("/mcp", json={})
        assert response.status_code == 401
        assert "resource_metadata" in response.headers["www-authenticate"]
        response = await client.post("/mcp", json={},
                                     headers={"Authorization": "Bearer bad-token"})
        assert response.status_code == 401
        assert "sensitive" not in response.text
        response = await client.post("/mcp", json={},
                                     headers={"Authorization": "Bearer test-valid-token",
                                              "Origin": "https://evil.example"})
        assert response.status_code in (400, 403, 421)


@pytest.mark.anyio
async def test_http_exposes_resource_metadata_not_client_selected_identity():
    app = create_http_app(Runtime(), "project001-dev",
                          resource_url="http://127.0.0.1:8899/mcp")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://127.0.0.1:8899") as client:
        response = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert response.status_code == 200
        body = response.json()
        assert body["resource"] == "http://127.0.0.1:8899/mcp"
        assert body["authorization_servers"] == [
            "https://login.microsoftonline.com/11111111-1111-4111-8111-111111111111/v2.0"
        ]


def test_remote_plaintext_http_is_rejected():
    with pytest.raises(ValueError, match="HTTPS"):
        create_http_app(Runtime(), "project001-dev", resource_url="http://server.example/mcp")

