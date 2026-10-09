"""Actual MCP stdio and authenticated HTTP, entirely synthetic/offline."""
import sys
import json
from types import SimpleNamespace

import anyio
import httpx
import pytest

from aifactory_mcp.client import connect_http, connect_stdio, invoke
from test_dual_graph import GRAPH_TOOLS, graph_snapshot, snapshot_runtime
from test_integration import http_endpoint, loopback_only, signed_token
from test_runtime import CALLER, MCP, SCOPE, artifacts, config_path, configuration, signing_key
from test_application_runtime import APP_CALLER, app_token, application_config


@pytest.fixture
def runtime(snapshot_runtime):
    return snapshot_runtime


async def exercise(session, snapshot_id):
    definitions = (await session.list_tools()).tools
    assert GRAPH_TOOLS <= {tool.name for tool in definitions}
    status = await invoke(session, "graph_status", {})
    assert status["data"]["snapshot_id"] == snapshot_id
    assert status["data"]["freshness"]["status"] == "unverified"
    queried = await invoke(session, "graph_query", {"operation": "callers", "node_id": "target"})
    assert queried["data"]["results"][0]["source"] == "entry"
    assert queried["data"]["citations"][0]["source_file"] == "src/code.py"
    context = await invoke(session, "dual_graph_context", {"query": "entry"})
    assert context["data"]["snapshot_id"] == snapshot_id
    assert context["data"]["structural_retrieved"] is True
    assert context["data"]["architecture_retrieved"] is True
    assert {item["record_type"] for item in context["data"]["results"]} >= {"node", "note"}
    rejected = await session.call_tool("graph_query", {"operation": "symbols", "root": "private"})
    assert rejected.isError
    assert rejected.structuredContent["error"]["code"] == "invalid_arguments"


@pytest.mark.anyio
async def test_real_stdio_initialize_discovery_and_graph_calls(runtime, config_path, graph_snapshot):
    with anyio.fail_after(45):
        async with connect_stdio(sys.executable, [
            "-m", "aifactory_mcp", "serve", "--config", str(config_path),
            "--scope", SCOPE, "--object-id", CALLER,
        ], env={"PYTHONPATH": str(MCP / "src"), "PYTHONDONTWRITEBYTECODE": "1"}) as session:
            await exercise(session, graph_snapshot[2])


@pytest.mark.anyio
async def test_real_authenticated_http_initialize_discovery_and_graph_calls(
    http_endpoint, signed_token, graph_snapshot, runtime,
):
    url, observed = http_endpoint
    with anyio.fail_after(30):
        async with connect_http(url, signed_token()) as session:
            await exercise(session, graph_snapshot[2])
            runtime.settings.auth.grants[0].permissions.remove("graph.read")
            assert not GRAPH_TOOLS.intersection(tool.name for tool in (await session.list_tools()).tools)
            denied = await session.call_tool("graph_status", {})
            assert denied.isError
    assert observed.callers and all(caller == CALLER and scope == SCOPE for caller, scope in observed.callers)


@pytest.mark.anyio
async def test_application_http_requires_explicit_graph_allowlist_and_rechecks_grant(
    snapshot_runtime, application_config, configuration, config_path, signing_key, monkeypatch,
):
    from aifactory_mcp import auth
    from aifactory_mcp.runtime import load_runtime
    from aifactory_mcp.server import create_http_app

    configuration["auth"]["grants"].append({
        "object_id": APP_CALLER, "scopes": [SCOPE], "permissions": ["factory.read", "graph.read"],
    })
    config_path.write_text(json.dumps(configuration), encoding="utf-8")
    policy = json.loads(application_config.read_text())
    policy["identities"][0]["allowed_tools"] = ["graph_status"]
    application_config.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(auth.jwt, "PyJWKClient", lambda *args, **kwargs: SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=signing_key.public_key()),
    ))
    selected = load_runtime(config_path, application_auth=application_config)
    app = create_http_app(selected, SCOPE, resource_url="http://127.0.0.1:8899/mcp")
    headers = {
        "Authorization": "Bearer " + app_token(signing_key),
        "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25",
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url="http://127.0.0.1:8899") as client:
            async def rpc(method, params=None):
                response = await client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params else {}),
                })
                assert response.status_code == 200
                return response.json()["result"]

            initialized = await rpc("initialize", {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "offline-graph-test", "version": "1"},
            })
            assert initialized["serverInfo"]["name"] == "enterprise-scale-ai-factory"
            assert [tool["name"] for tool in (await rpc("tools/list"))["tools"]] == ["graph_status"]
            assert not (await rpc("tools/call", {"name": "graph_status", "arguments": {}}))["isError"]
            assert (await rpc("tools/call", {
                "name": "graph_query", "arguments": {"operation": "symbols"},
            }))["isError"]
            selected.settings.auth.grants[-1].permissions.remove("graph.read")
            assert (await rpc("tools/list"))["tools"] == []
            assert (await rpc("tools/call", {"name": "graph_status", "arguments": {}}))["isError"]
