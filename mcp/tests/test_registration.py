from __future__ import annotations

import hashlib
import json
import runpy
import socket
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from aifactory_mcp.registration import (
    ApplicationRole,
    DEFAULT_ALLOWED_TOOLS,
    READ_ONLY_TOOLS,
    REQUIRED_ROLE,
    RegistrationTarget,
    build_registration_plan,
)


@pytest.fixture
def target():
    return RegistrationTarget(
        subscription_id="f0fe8b33-73bf-41e4-9997-e3920d793c06",
        tenant_id="c157e61b-4a1e-488c-9a0c-d9a23e864a65",
        resource_group="spider-esml-project001-sdc-dev-001-rg",
        foundry_account="aif2bltscaae001dev",
        foundry_project="aif2-p001bltdev",
        project_principal_id="78fcb1e6-30cf-477e-ba9a-4d935b547252",
        project_client_id="2de2956f-6c3b-410c-95bd-8a9403f9686f",
        mcp_application_id="11111111-2222-4333-8444-555555555555",
        mcp_url="https://aifactory-governed-mcp.example.com/mcp",
    )


def test_exact_create_only_connection_and_tool_shape(target):
    plan = build_registration_plan(target, scope_key="project001-dev")
    project_id = (
        f"/subscriptions/{target.subscription_id}/resourceGroups/{target.resource_group}"
        f"/providers/Microsoft.CognitiveServices/accounts/{target.foundry_account}"
        f"/projects/{target.foundry_project}"
    )
    connection_id = f"{project_id}/connections/aifactory-governed-mcp"
    assert plan["mode"] == "plan-only"
    assert plan["target"]["project_resource_id"] == project_id
    assert plan["target"]["service_name"] == "aifactory-governed-mcp"
    assert plan["connection_request"] == {
        "method": "PUT",
        "resource_id": connection_id,
        "url": f"https://management.azure.com{connection_id}?api-version=2025-10-01-preview",
        "headers": {"If-None-Match": "*"},
        "body": {"properties": {
            "authType": "ProjectManagedIdentity",
            "category": "RemoteTool",
            "target": target.mcp_url,
            "isSharedToAll": False,
            "audience": str(target.mcp_application_id),
            "metadata": {
                "ApiType": "Azure",
                "aifactory.managed_by": "aifactory-mcp",
                "aifactory.project_id": project_id,
            },
        }},
    }
    assert plan["agent_tool"] == {
        "type": "mcp",
        "server_label": "aifactory-governed",
        "server_url": target.mcp_url,
        "allowed_tools": list(DEFAULT_ALLOWED_TOOLS),
        "require_approval": "always",
        "project_connection_id": "aifactory-governed-mcp",
    }
    assert plan["updatePolicy"] == (
        "append only after reviewing existing agent tools/version; never replace existing connections"
    )
    assert not {"model", "instructions", "tools", "credentials"} & plan.keys()


def test_graph_registration_is_opt_in_plan_only_not_an_implicit_grant(target):
    original = build_registration_plan(target, scope_key="project001-dev")
    assert "graph.read" not in original["required_agent_grant"]["permissions"]
    requested = replace(target, allowed_tools=("graph_status", "dual_graph_context"))
    plan = build_registration_plan(requested, scope_key="project001-dev")
    assert plan["mode"] == "plan-only"
    assert plan["required_agent_grant"]["permissions"] == ["factory.read", "graph.read"]
    assert plan["agent_tool"]["require_approval"] == "always"
    assert any("grants no corpus access" in item for item in plan["review_required"])


def test_identity_grant_and_separate_api_application_template(target):
    plan = build_registration_plan(target, scope_key="project001-dev")
    assert plan["application_auth"] == {
        "audience": str(target.mcp_application_id),
        "required_role": "AiFactory.Mcp.Read",
        "identities": [{
            "object_id": str(target.project_principal_id),
            "client_id": str(target.project_client_id),
            "scope_keys": ["project001-dev"],
            "allowed_tools": list(DEFAULT_ALLOWED_TOOLS),
        }],
    }
    assert plan["required_agent_grant"] == {
        "object_id": str(target.project_principal_id),
        "scopes": ["project001-dev"],
        "permissions": ["factory.read"],
    }
    template = plan["entra_app_template"]
    assert template["applicationId"] == str(target.mcp_application_id)
    assert template["requiredApplicationRole"] == {
        "id": str(uuid5(target.mcp_application_id, REQUIRED_ROLE)),
        "allowedMemberTypes": ["Application"],
        "value": REQUIRED_ROLE,
        "displayName": "AI Factory MCP read",
        "description": "Read explicitly allowed AI Factory MCP tools as an application.",
        "isEnabled": True,
    }
    assert template["api"] == {"requestedAccessTokenVersion": 2}
    assert template["optionalClaims"] == {
        "accessToken": [{"name": "idtyp", "essential": True}],
    }
    assert template["servicePrincipalRequirements"] == {"appRoleAssignmentRequired": True}
    assert "separate" in plan["token_routing"].lower()


@pytest.mark.parametrize("tool", [
    "cost_default_project_idle", "cost_common_idle", "cost_monthly_project_forecast",
])
def test_cost_tools_add_only_cost_read(target, tool):
    selected = replace(target, allowed_tools=("factory_health", tool))
    plan = build_registration_plan(selected, scope_key="project001-dev")
    assert plan["required_agent_grant"]["permissions"] == ["factory.read", "cost.read"]
    assert plan["agent_tool"]["allowed_tools"] == ["factory_health", tool]
    assert plan["application_auth"]["identities"][0]["allowed_tools"] == ["factory_health", tool]


@pytest.mark.parametrize("tool", ["factory_catalog", "factory_settings"])
def test_other_explicit_read_tools_need_no_extra_permission(target, tool):
    plan = build_registration_plan(replace(target, allowed_tools=(tool,)), scope_key="scope")
    assert plan["required_agent_grant"]["permissions"] == ["factory.read"]


def test_immutable_inputs_are_canonical_and_output_does_not_alias_them(target):
    tools = ["factory_health"]
    selected = replace(target, allowed_tools=tools, tenant_id=str(target.tenant_id).upper())
    tools.append("factory_settings")
    assert selected.allowed_tools == ("factory_health",)
    assert isinstance(selected.tenant_id, UUID)
    with pytest.raises(FrozenInstanceError):
        selected.connection_name = "changed"
    first = build_registration_plan(selected, scope_key="scope")
    first["agent_tool"]["allowed_tools"].append("factory_settings")
    assert first["application_auth"]["identities"][0]["allowed_tools"] == ["factory_health"]
    assert build_registration_plan(selected, scope_key="scope")["agent_tool"]["allowed_tools"] == ["factory_health"]


@pytest.mark.parametrize("field", [
    "subscription_id", "tenant_id", "project_principal_id", "project_client_id", "mcp_application_id",
])
@pytest.mark.parametrize("invalid", [
    "", "not-a-guid", "00000000-0000-0000-0000-000000000000", True, None,
    "https://login.microsoftonline.com/common", "api://11111111-2222-4333-8444-555555555555",
])
def test_invalid_or_implicit_identity_authorities_fail_closed(target, field, invalid):
    with pytest.raises(ValueError):
        replace(target, **{field: invalid})


@pytest.mark.parametrize("field", [
    "resource_group", "foundry_account", "foundry_project", "connection_name", "server_label", "service_name",
])
@pytest.mark.parametrize("invalid", ["", "..", "a/b", "a\\b", "a%2fb", "a?b", "a#b", "a\nb", "*"])
def test_names_cannot_escape_resource_paths(target, field, invalid):
    with pytest.raises(ValueError):
        replace(target, **{field: invalid})


@pytest.mark.parametrize("url", [
    "http://mcp.example.com/mcp", "https://mcp.example.com", "https://mcp.example.com/mcp/",
    "https://user:secret@mcp.example.com/mcp", "https://@mcp.example.com/mcp",
    "https://mcp.example.com/mcp?token=secret", "https://mcp.example.com/mcp?",
    "https://mcp.example.com/mcp#fragment", "https://mcp.example.com/mcp#",
    " https://mcp.example.com/mcp", "https://mcp.example.com/mcp\n",
    "https://mcp.example.com\\other/mcp", "https://mcp.example.com/a/../mcp",
    "https://mcp.example.com/a/./mcp", "https://mcp.example.com//mcp",
    "https://mcp.example.com/%2e%2e/mcp", "https://mcp.example.com/%6dcp",
    "https://MCP.example.com/mcp", "HTTPS://mcp.example.com/mcp",
    "https://mcp.example.com./mcp", "https://mcp.example.com:443/mcp",
    "https://mcp.example.com:8443/mcp", "https://mcp.example.com:/mcp",
    "https://mcp.example.com:bad/mcp", "https://127.0.0.1/mcp",
    "https://[::1]/mcp", "https://localhost/mcp", "https://mcp.localhost/mcp",
    "https://mcp.exämple.com/mcp", "https://-bad.example.com/mcp",
    "https://aif-mcp-project001-dev.env.swedencentral.azurecontainerapps.io/mcp",
    "https://aif-mcp-project001-dev--revision.env.swedencentral.azurecontainerapps.io/mcp",
    "https://example.com/aif-mcp-project001-dev/mcp",
])
def test_unsafe_noncanonical_or_protected_urls_fail(target, url):
    with pytest.raises(ValueError):
        replace(target, mcp_url=url)


def test_canonical_https_nested_route_is_explicitly_preserved(target):
    selected = replace(target, mcp_url="https://governed.example.com/tools/factory-v1/mcp")
    assert build_registration_plan(selected, scope_key="scope")["agent_tool"]["server_url"] == selected.mcp_url


@pytest.mark.parametrize("name", ["aif-azure-mcp", "AIF-AZURE-MCP", "aif-mcp-project001-dev"])
@pytest.mark.parametrize("field", ["connection_name", "service_name", "server_label"])
def test_existing_service_and_connection_names_are_never_reused(target, field, name):
    with pytest.raises(ValueError):
        replace(target, **{field: name})


@pytest.mark.parametrize("tools", [
    (), [], "*", ("*",), ("factory_*",), ("unknown",), ("factory_cli_health",),
    ("factory_execute_skill",), ("factory_create",), ("knowledge_search",),
    ("factory_health", "factory_health"), ("FACTORY_HEALTH",), (None,), None,
])
def test_empty_duplicate_wildcard_unknown_or_write_tool_authority_fails(target, tools):
    with pytest.raises(ValueError):
        replace(target, allowed_tools=tools)


@pytest.mark.parametrize("scope", ["", "*", "project/*", "a b", "../scope", "a\nb", "-scope", "_scope", None])
def test_invalid_scope_authority_fails(target, scope):
    with pytest.raises(ValueError):
        build_registration_plan(target, scope_key=scope)


def test_application_and_caller_identity_must_be_distinct(target):
    for identity in (target.project_principal_id, target.project_client_id):
        with pytest.raises(ValueError):
            replace(target, mcp_application_id=identity)
    with pytest.raises(ValueError):
        replace(target, project_client_id=target.project_principal_id)


def test_existing_role_id_can_only_describe_exact_application_read_role(target):
    role = ApplicationRole(id="99999999-aaaa-4bbb-8ccc-dddddddddddd")
    plan = build_registration_plan(target, scope_key="scope", existing_application_role=role)
    assert plan["entra_app_template"]["requiredApplicationRole"]["id"] == str(role.id)
    with pytest.raises(FrozenInstanceError):
        role.value = "Other"
    for kwargs in (
        {"value": "Other"}, {"allowed_member_types": ("User",)},
        {"allowed_member_types": ("Application", "User")}, {"is_enabled": False},
        {"is_enabled": 1}, {"id": "invalid"},
    ):
        with pytest.raises(ValueError):
            ApplicationRole(id=role.id, **kwargs) if "id" not in kwargs else ApplicationRole(**kwargs)
    with pytest.raises(ValueError):
        build_registration_plan(target, scope_key="scope", existing_application_role={"id": str(role.id)})


def test_plan_hash_is_sha256_of_canonical_json_without_hash(target):
    plan = build_registration_plan(target, scope_key="scope")
    assert plan == build_registration_plan(target, scope_key="scope")
    hash_value = plan.pop("plan_hash")
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert hash_value == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert hash_value != build_registration_plan(target, scope_key="different")["plan_hash"]
    assert hash_value != build_registration_plan(
        replace(target, connection_name="another-governed-mcp"), scope_key="scope",
    )["plan_hash"]


def test_plan_never_uses_network_or_ambient_credentials(target, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Planning must not access the network.")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setenv("AZURE_ACCESS_TOKEN", "must-not-leak-this-token")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "must-not-leak-this-secret")
    result = json.dumps(build_registration_plan(target, scope_key="scope"))
    assert "must-not-leak" not in result
    assert "Authorization" not in result
    assert '"credentials"' not in result


def test_actual_foundry_sdk_mcp_tool_round_trip(target):
    from azure.ai.projects.models import MCPTool

    descriptor = build_registration_plan(target, scope_key="scope")["agent_tool"]
    tool = MCPTool(descriptor)
    assert tool.project_connection_id == target.connection_name
    assert tool.require_approval == "always"
    assert tool.as_dict() == descriptor


@pytest.mark.parametrize("tools", [DEFAULT_ALLOWED_TOOLS, tuple(sorted(READ_ONLY_TOOLS))])
@pytest.mark.parametrize("scope", ["project001-dev", "A" * 80])
def test_generated_config_matches_application_auth_and_real_agent_grant(target, monkeypatch, tools, scope):
    from aifactory_mcp.auth import ApplicationAuthSettings, READ_ONLY_APPLICATION_TOOLS

    agent_root = (
        Path(__file__).resolve().parents[2] / "usecase_code" / "40-agent-factory" / "40-aifactory-agent"
    )
    monkeypatch.syspath_prepend(str(agent_root))
    from aifactory_agent.config import Grant

    plan = build_registration_plan(replace(target, allowed_tools=tools), scope_key=scope)
    config = ApplicationAuthSettings.model_validate_json(json.dumps(plan["application_auth"]))
    assert config.model_dump(mode="json") == plan["application_auth"]
    assert READ_ONLY_APPLICATION_TOOLS == READ_ONLY_TOOLS
    grant = Grant.model_validate(plan["required_agent_grant"])
    assert grant.model_dump(mode="json") == plan["required_agent_grant"]


def _cli_main():
    script = Path(__file__).resolve().parents[1] / "usecase_code" / "foundry_connection_plan.py"
    return runpy.run_path(str(script))["main"]


def _arguments(target):
    names = (
        "subscription_id", "tenant_id", "resource_group", "foundry_account", "foundry_project",
        "project_principal_id", "project_client_id", "mcp_application_id", "mcp_url",
    )
    return [
        value for name in names for value in ("--" + name.replace("_", "-"), str(getattr(target, name)))
    ] + ["--scope-key", "project001-dev"]


def test_cli_outputs_only_the_pure_plan(target, capsys):
    assert _cli_main()(_arguments(target)) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == build_registration_plan(target, scope_key="project001-dev")


def test_cli_new_application_id_is_required_and_never_guessed(target, capsys):
    args = _arguments(target)
    index = args.index("--mcp-application-id")
    del args[index:index + 2]
    with pytest.raises(SystemExit) as result:
        _cli_main()(args)
    assert result.value.code == 2
    assert not capsys.readouterr().out


@pytest.mark.parametrize("extra", [["--apply"], ["--token", "secret-do-not-print"], ["--audience", "*"]])
def test_cli_rejects_execution_tokens_or_unknown_authority(target, capsys, extra):
    with pytest.raises(SystemExit) as result:
        _cli_main()(_arguments(target) + extra)
    assert result.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "secret-do-not-print" not in captured.err


def test_cli_sanitizes_unsafe_endpoint_validation_errors(target, capsys):
    args = _arguments(target)
    args[args.index("--mcp-url") + 1] = "https://secret-do-not-print@example.com/mcp"
    with pytest.raises(SystemExit) as result:
        _cli_main()(args)
    assert result.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "secret-do-not-print" not in captured.err


def test_cli_uses_same_builder_for_explicit_tools_and_existing_role(target, capsys):
    args = _arguments(target) + [
        "--allowed-tool", "factory_health", "--allowed-tool", "cost_common_idle",
        "--existing-role-id", "99999999-aaaa-4bbb-8ccc-dddddddddddd",
    ]
    assert _cli_main()(args) == 0
    assert json.loads(capsys.readouterr().out) == build_registration_plan(
        replace(target, allowed_tools=("factory_health", "cost_common_idle")),
        scope_key="project001-dev",
        existing_application_role=ApplicationRole(id="99999999-aaaa-4bbb-8ccc-dddddddddddd"),
    )


def test_explicit_static_remote_tool_boundary():
    assert READ_ONLY_TOOLS == frozenset({
        "factory_health", "factory_capabilities", "factory_skills", "factory_catalog", "factory_settings",
        "cost_default_project_idle", "cost_common_idle", "cost_monthly_project_forecast",
        "graph_status", "graph_query", "architecture_search", "architecture_note", "dual_graph_context",
    })
