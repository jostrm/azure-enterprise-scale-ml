"""The existing server's corpus-only mode cannot expose Factory operations."""
import json
import sys
from dataclasses import replace

import anyio
import pytest

from aifactory_mcp.client import connect_http, connect_stdio, invoke
from test_backend import assert_error
from test_dual_graph import GRAPH_TOOLS, graph_snapshot, snapshot_runtime
from test_integration import http_endpoint, signed_token, loopback_only
from test_runtime import CALLER, MCP, SCOPE, artifacts, config_path, configuration, signing_key
from test_application_runtime import APP_CALLER, application_config


@pytest.fixture
def runtime(snapshot_runtime, config_path):
    selected = replace(snapshot_runtime, graph_only=True)
    selected.settings.auth.grants[0].permissions[:] = ["graph.read"]
    config_path.write_text(selected.settings.model_dump_json(), encoding="utf-8")
    return selected


def test_graph_only_never_initializes_factory_tools_or_operation_store(runtime, monkeypatch):
    monkeypatch.setattr(runtime.tools, "FactoryTools", lambda *a, **k: pytest.fail("Factory tools initialized"))
    monkeypatch.setattr(runtime.operations, "OperationStore", lambda *a, **k: pytest.fail("Operation store initialized"))
    selected = runtime.backend(runtime.local_principal(CALLER), SCOPE)
    assert {tool["name"] for tool in selected.list_tools()} == GRAPH_TOOLS
    assert selected.call_tool("graph_status", {})["ok"] is True
    assert not hasattr(selected, "approve")
    for name in ("factory_health", "factory_skills", "factory_operations",
                 "factory_prepare_create", "factory_execute_operation", "factory_cli_health"):
        assert_error("unsupported_tool", lambda: selected.call_tool(name, {}))
    assert_error("invalid_arguments", lambda: selected.call_tool("graph_status", {"root": "other"}))
    assert_error("invalid_arguments", lambda: selected.call_tool("graph_status", []))


def test_graph_only_rechecks_scope_and_graph_grant(runtime):
    selected = runtime.backend(runtime.local_principal(CALLER), SCOPE)
    assert_error("forbidden", lambda: runtime.backend(runtime.local_principal(CALLER), "other"))
    runtime.settings.auth.grants[0].permissions[:] = ["factory.read", "knowledge.read"]
    assert_error("forbidden", selected.list_tools)
    assert_error("forbidden", lambda: selected.call_tool("graph_status", {}))


def test_graph_only_cli_is_explicit_and_forwarded_to_stdio_child():
    from aifactory_mcp.__main__ import _child_arguments, parser

    parsed = parser().parse_args([
        "tools", "--config", "agent.json", "--scope", SCOPE, "--object-id", CALLER, "--graph-only",
    ])
    assert "--graph-only" in _child_arguments(parsed)
    with pytest.raises(SystemExit):
        parser().parse_args([
            "approve", "--config", "agent.json", "--scope", SCOPE, "--operation-id", "x", "--graph-only",
        ])


def test_graph_only_application_requires_only_graph_grant_and_graph_allowlist(
    runtime, configuration, config_path, application_config,
):
    from aifactory_mcp.runtime import load_runtime
    from aifactory_mcp.auth import ApplicationPrincipal

    config = json.loads(config_path.read_text())
    config["auth"]["grants"].append({
        "object_id": APP_CALLER, "scopes": [SCOPE], "permissions": ["graph.read"],
    })
    config_path.write_text(json.dumps(config), encoding="utf-8")
    policy = json.loads(application_config.read_text())
    policy["identities"][0]["allowed_tools"] = ["graph_status"]
    application_config.write_text(json.dumps(policy), encoding="utf-8")
    selected = load_runtime(config_path, graph_only=True, application_auth=application_config)
    principal = ApplicationPrincipal(
        selected.local_principal(APP_CALLER), frozenset({SCOPE}), frozenset({"graph_status"}),
    )
    assert [tool["name"] for tool in selected.backend(principal, SCOPE).list_tools()] == ["graph_status"]
    policy["identities"][0]["allowed_tools"].append("factory_health")
    application_config.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ValueError, match="Graph-only"):
        load_runtime(config_path, graph_only=True, application_auth=application_config)


async def assert_graph_only_protocol(session):
    assert {tool.name for tool in (await session.list_tools()).tools} == GRAPH_TOOLS
    assert (await invoke(session, "graph_status", {}))["ok"] is True
    result = await session.call_tool("factory_prepare_create", {})
    assert result.isError
    assert result.structuredContent["error"]["code"] == "unsupported_tool"


@pytest.mark.anyio
async def test_graph_only_actual_stdio_with_only_graph_read(runtime, config_path):
    with anyio.fail_after(45):
        async with connect_stdio(sys.executable, [
            "-m", "aifactory_mcp", "serve", "--config", str(config_path),
            "--scope", SCOPE, "--object-id", CALLER, "--graph-only",
        ], env={"PYTHONPATH": str(MCP / "src"), "PYTHONDONTWRITEBYTECODE": "1"}) as session:
            await assert_graph_only_protocol(session)


@pytest.mark.anyio
async def test_graph_only_actual_signed_http_with_only_graph_read(http_endpoint, signed_token):
    url, _ = http_endpoint
    with anyio.fail_after(30):
        async with connect_http(url, signed_token()) as session:
            await assert_graph_only_protocol(session)
