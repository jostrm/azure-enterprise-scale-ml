import copy
import json
from types import SimpleNamespace

import httpx
import jwt
import pytest

from aifactory_mcp.runtime import load_runtime
from aifactory_mcp.server import create_http_app
from test_runtime import (
    CALLER, SCOPE, artifacts, config_path, configuration, runtime, security_fixtures, signing_key,
)

APP = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
APP_CALLER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
APP_CLIENT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


@pytest.fixture
def application_config(artifacts):
    path = artifacts / "application-auth.json"
    path.write_text(json.dumps({
        "audience": APP, "required_role": "AiFactory.Mcp.Read",
        "identities": [{
            "object_id": APP_CALLER, "client_id": APP_CLIENT, "scope_keys": [SCOPE],
            "allowed_tools": ["factory_health", "factory_capabilities", "factory_skills"],
        }],
    }), encoding="utf-8")
    return path


@pytest.fixture
def application_runtime(application_config, configuration, config_path, signing_key, monkeypatch):
    configuration["auth"]["grants"].append({
        "object_id": APP_CALLER, "scopes": [SCOPE], "permissions": ["factory.read"],
    })
    config_path.write_text(json.dumps(configuration), encoding="utf-8")
    from aifactory_mcp import auth
    monkeypatch.setattr(auth.jwt, "PyJWKClient", lambda *args, **kwargs: SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=signing_key.public_key()),
    ))
    return load_runtime(config_path, application_auth=application_config)


def app_token(signing_key, **overrides):
    claims = security_fixtures.claims()
    claims.pop("scp", None)
    claims.update(aud=APP, oid=APP_CALLER, azp=APP_CLIENT, ver="2.0",
                  idtyp="app", roles=["AiFactory.Mcp.Read"])
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="RS256")


def test_application_runtime_preserves_delegated_identity_and_rejects_cross_scope(
    application_runtime, signing_key,
):
    delegated = jwt.encode(security_fixtures.claims(), signing_key, algorithm="RS256")
    assert application_runtime.principal_from_token(delegated).object_id == CALLER
    principal = application_runtime.principal_from_token(app_token(signing_key))
    assert principal.principal.object_id == APP_CALLER
    backend = application_runtime.backend(principal, SCOPE)
    assert {item["name"] for item in backend.list_tools()} == {
        "factory_health", "factory_capabilities", "factory_skills",
    }
    assert backend.call_tool("factory_skills", {})["ok"] is True
    with pytest.raises(PermissionError):
        application_runtime.backend(principal, "other")
    for name in ("factory_prepare_delete", "factory_execute_operation", "factory_operations",
                 "factory_operation_status", "factory_cli_health"):
        with pytest.raises(PermissionError):
            backend.call_tool(name, {})
    assert not hasattr(backend, "approve")


@pytest.mark.parametrize("permissions", [[], ["factory.read", "factory.delete"]])
def test_application_configuration_requires_explicit_read_only_grants(
    application_config, configuration, config_path, permissions,
):
    configuration["auth"]["grants"].append({
        "object_id": APP_CALLER, "scopes": [SCOPE], "permissions": permissions,
    })
    config_path.write_text(json.dumps(configuration), encoding="utf-8")
    with pytest.raises(ValueError, match="grant"):
        load_runtime(config_path, application_auth=application_config)


def test_application_discovery_rechecks_grants(application_runtime, signing_key):
    principal = application_runtime.principal_from_token(app_token(signing_key))
    backend = application_runtime.backend(principal, SCOPE)
    application_runtime.settings.auth.grants.clear()
    with pytest.raises(RuntimeError, match="permission"):
        backend.list_tools()


@pytest.mark.anyio
async def test_http_application_identity_cannot_discover_or_call_actions(
    application_runtime, signing_key,
):
    app = create_http_app(application_runtime, SCOPE, resource_url="http://127.0.0.1:8899/mcp")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url="http://127.0.0.1:8899") as client:
            headers = {
                "Authorization": "Bearer " + app_token(signing_key),
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            }
            response = await client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            })
            tools = response.json()["result"]["tools"]
            assert {item["name"] for item in tools} == {
                "factory_health", "factory_capabilities", "factory_skills",
            }
            response = await client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "factory_execute_operation", "arguments": {}},
            })
            assert response.json()["result"]["isError"] is True
            response = await client.post("/mcp", headers={
                **headers, "Authorization": "Bearer " + app_token(signing_key, azp=CALLER),
            }, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
            assert response.status_code == 401


def test_application_backend_refuses_readonly_annotation_drift(application_runtime, signing_key, monkeypatch):
    # The wrapper uses the final MCP descriptor, not raw upstream metadata.
    from aifactory_mcp.backend import AgentBackend
    original = AgentBackend.list_tools

    def changed(self):
        definitions = copy.deepcopy(original(self))
        next(item for item in definitions if item["name"] == "factory_health")["annotations"]["readOnlyHint"] = False
        return definitions

    monkeypatch.setattr(AgentBackend, "list_tools", changed)
    principal = application_runtime.principal_from_token(app_token(signing_key))
    backend = application_runtime.backend(principal, SCOPE)
    with pytest.raises(PermissionError):
        backend.list_tools()


@pytest.mark.parametrize("graph_grant", [False, True])
def test_application_graph_opt_in_requires_grant_and_scope_configuration(
    application_config, configuration, config_path, artifacts, graph_grant,
):
    configuration["dual_graph"] = {
        "snapshot_root": str(artifacts), "allowed_scopes": [SCOPE],
        "expected_snapshot_id": "a" * 64, "allow_source_access": False,
    }
    configuration["auth"]["grants"].append({
        "object_id": APP_CALLER, "scopes": [SCOPE],
        "permissions": ["factory.read"] + (["graph.read"] if graph_grant else []),
    })
    policy = json.loads(application_config.read_text())
    policy["identities"][0]["allowed_tools"] = ["graph_status"]
    application_config.write_text(json.dumps(policy), encoding="utf-8")
    config_path.write_text(json.dumps(configuration), encoding="utf-8")
    if not graph_grant:
        with pytest.raises(ValueError, match="grant"):
            load_runtime(config_path, application_auth=application_config)
    else:
        selected = load_runtime(config_path, application_auth=application_config)
        assert selected.settings.dual_graph is not None
        configuration["dual_graph"]["allowed_scopes"] = []
        config_path.write_text(json.dumps(configuration), encoding="utf-8")
        with pytest.raises((ValueError, RuntimeError)):
            load_runtime(config_path, application_auth=application_config)


@pytest.mark.parametrize("graph_scope", [SCOPE, "other-dev"], ids=["same-scope", "cross-scope"])
def test_application_graph_permissions_combine_only_within_exact_scope(
    application_config, configuration, config_path, artifacts, graph_scope,
):
    from aifactory_mcp.auth import ApplicationPrincipal

    configuration["scopes"]["other-dev"] = copy.deepcopy(configuration["scopes"][SCOPE])
    configuration["dual_graph"] = {
        "snapshot_root": str(artifacts), "allowed_scopes": [SCOPE],
        "expected_snapshot_id": "a" * 64,
    }
    configuration["auth"]["grants"].extend([
        {"object_id": APP_CALLER, "scopes": [SCOPE], "permissions": ["factory.read"]},
        {"object_id": APP_CALLER, "scopes": [graph_scope], "permissions": ["graph.read"]},
    ])
    policy = json.loads(application_config.read_text())
    policy["identities"][0]["allowed_tools"] = ["graph_status"]
    application_config.write_text(json.dumps(policy), encoding="utf-8")
    config_path.write_text(json.dumps(configuration), encoding="utf-8")

    if graph_scope != SCOPE:
        with pytest.raises(ValueError, match="grant"):
            load_runtime(config_path, application_auth=application_config)
        return
    selected = load_runtime(config_path, application_auth=application_config)
    principal = ApplicationPrincipal(
        selected.local_principal(APP_CALLER), frozenset({SCOPE}), frozenset({"graph_status"}),
    )
    assert [tool["name"] for tool in selected.backend(principal, SCOPE).list_tools()] == ["graph_status"]
