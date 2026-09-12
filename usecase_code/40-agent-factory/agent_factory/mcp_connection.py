"""Verify private Azure MCP infrastructure before create-only Foundry wiring.

No deployment journal is needed. The operator only reads ARM and probes the
unauthenticated challenge; successful project-MI tool invocation is a later step.
"""

from __future__ import annotations

import json
import hashlib
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid5

from .azure import ARM, AzureError, AzureSession
from .config import Target
from .data import require_private_endpoint
from .mcp_control import (
    ARM_OWNER_KEY, ARM_PROJECT_KEY, CONTAINER_APP_API, ENVIRONMENT_API, MANAGED_BY, NETWORK_API,
    _arm_read, _guid, _owned_arm, _same, _same_location, _session_target,
    build_mcp_parameters, validate_mcp_plan,
)

CONNECTION_API = "2025-10-01-preview"
CONNECTION_NAME = "aif-azure-mcp"
ROLE_API = "2022-04-01"
READER_ROLE = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
SERVER_ARGS = [
    "--transport", "http", "--outgoing-auth-strategy", "UseHostingEnvironmentIdentity",
    "--mode", "all", "--read-only", "--tool", "group_resource_list",
]
_ARM_GUID_NAMESPACE = UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830")
_DNS_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_PRIVATE_NETWORK_ERROR = (
    "Private Azure MCP is unreachable. Connect the operator host to the Azure VNet/VPN, "
    "configure private DNS for the ACA environment, and allow private TCP 443; "
    "no public endpoint, proxy, or operator-token fallback is allowed."
)


def _properties(resource: dict) -> dict:
    properties = resource.get("properties")
    if not isinstance(properties, dict):
        raise RuntimeError("ARM properties are unavailable; infrastructure cannot be verified.")
    return properties


def _succeeded(resource: dict) -> dict:
    properties = _properties(resource)
    if properties.get("provisioningState") != "Succeeded":
        raise RuntimeError("Azure MCP infrastructure must have provisioningState Succeeded.")
    return properties


def _environment_variables(tenant_id: str, client_id: str) -> dict:
    return {
        "AZURE_TOKEN_CREDENTIALS": "managedidentitycredential",
        "AZURE_MCP_INCLUDE_PRODUCTION_CREDENTIALS": "true",
        "AZURE_MCP_COLLECT_TELEMETRY": "false",
        "AzureAd__Instance": "https://login.microsoftonline.com/",
        "AzureAd__TenantId": tenant_id,
        "AzureAd__ClientId": client_id,
        "ASPNETCORE_ENVIRONMENT": "Production",
        "DOTNET_ENVIRONMENT": "Production",
        "ASPNETCORE_URLS": "http://0.0.0.0:8080",
        "AZURE_MCP_DANGEROUSLY_DISABLE_HTTPS_REDIRECTION": "true",
        "Logging__LogLevel__Default": "Warning",
        "Logging__LogLevel__Azure": "Warning",
        "Logging__LogLevel__Microsoft": "Warning",
    }


def _verify_app(app: dict, environment_id: str, target: Target, plan: dict, identity: dict) -> str:
    properties = _succeeded(app)
    references = [
        properties[key] for key in ("environmentId", "managedEnvironmentId") if properties.get(key)
    ]
    if not references or any(not _same(value, environment_id) for value in references):
        raise RuntimeError("Azure MCP app does not belong to the exact owned environment.")
    hosting = app.get("identity") or {}
    if (hosting.get("type") != "SystemAssigned" or hosting.get("userAssignedIdentities")
            or not _same(hosting.get("tenantId"), target.tenant_id)):
        raise RuntimeError("Azure MCP hosting identity must be SystemAssigned only, in the selected tenant.")
    principal = _guid(hosting.get("principalId"), "Hosting principal ID")
    if any(_same(principal, identity[key]) for key in ("project_principal_id", "service_principal_id")):
        raise RuntimeError("Azure MCP hosting identity must be separate from the project caller and API identity.")
    configuration = properties.get("configuration") or {}
    if configuration.get("activeRevisionsMode") != "Single":
        raise RuntimeError("Azure MCP must serve a single verified revision.")
    if (configuration.get("secrets") or configuration.get("registries")
            or (configuration.get("dapr") or {}).get("enabled")):
        raise RuntimeError("Azure MCP must not use secrets, registry credentials, or authentication sidecars.")
    latest = properties.get("latestRevisionName")
    ready = properties.get("latestReadyRevisionName")
    if latest and ready and latest != ready:
        raise RuntimeError("Azure MCP's latest reviewed revision is not ready.")
    if properties.get("runningStatus", "Running") != "Running":
        raise RuntimeError("Azure MCP must be running before wiring agents.")
    template = properties.get("template") or {}
    containers = template.get("containers")
    if (not isinstance(containers, list) or len(containers) != 1
            or template.get("initContainers") or template.get("volumes") or template.get("serviceBinds")):
        raise RuntimeError("Azure MCP must run only the reviewed container, without sidecars or injected content.")
    container = containers[0]
    if (container.get("name") != "azure-mcp" or container.get("image") != plan["image"]
            or container.get("command") not in (None, []) or container.get("args") != SERVER_ARGS
            or container.get("volumeMounts")):
        raise RuntimeError("Azure MCP image, entrypoint, or exact read-only tool flags differ from reviewed Bicep.")
    entries = container.get("env")
    expected = _environment_variables(
        target.tenant_id, _guid(identity["application_client_id"], "Entra application client ID"),
    )
    if (not isinstance(entries, list) or len(entries) != len(expected)
            or any(not isinstance(entry, dict) or set(entry) - {"name", "value", "secretRef"}
                   or entry.get("secretRef") is not None for entry in entries)):
        raise RuntimeError("Azure MCP environment must use only the reviewed secretless MI/auth configuration.")
    actual = {entry.get("name"): entry.get("value") for entry in entries}
    if actual != expected:
        raise RuntimeError("Azure MCP environment differs: MI-only credentials and exact inbound Entra auth are required.")
    ingress = configuration.get("ingress") or {}
    if (ingress.get("allowInsecure") is not False or ingress.get("external") is not True
            or ingress.get("targetPort") != 8080 or not _same(ingress.get("transport"), "http")
            or ingress.get("customDomains")):
        raise RuntimeError("Azure MCP must use the standard ACA TLS endpoint without custom domains.")
    traffic = ingress.get("traffic") or []
    if traffic and (
        len(traffic) != 1 or traffic[0].get("weight") != 100 or traffic[0].get("label")
        or not (traffic[0].get("latestRevision") is True
                or (ready and traffic[0].get("revisionName") == ready))
    ):
        raise RuntimeError("Azure MCP traffic must target only the reviewed ready revision.")
    return principal


def _canonical_url(app: dict, environment: dict, target: Target, plan: dict) -> str:
    domain = _properties(environment).get("defaultDomain")
    pattern = rf"{_DNS_LABEL}\.{re.escape(target.location)}\.azurecontainerapps\.io"
    if not isinstance(domain, str) or not re.fullmatch(pattern, domain):
        raise RuntimeError("Owned environment defaultDomain must be the standard regional azurecontainerapps.io domain.")
    fqdn = (_properties(app).get("configuration") or {}).get("ingress", {}).get("fqdn")
    if fqdn != f"{plan['name']}.{domain}":
        raise RuntimeError("Azure MCP FQDN must exactly match the app name and owned environment defaultDomain.")
    return f"https://{fqdn}"


def _verify_private_endpoint(endpoint: dict, environment_id: str, plan: dict) -> None:
    properties = _succeeded(endpoint)
    if not _same((properties.get("subnet") or {}).get("id"), plan["private_endpoint_subnet_id"]):
        raise RuntimeError("Azure MCP PE must use the exact separate private-endpoint subnet.")
    connections = properties.get("privateLinkServiceConnections")
    if (not isinstance(connections, list) or len(connections) != 1
            or properties.get("manualPrivateLinkServiceConnections")):
        raise RuntimeError("Azure MCP PE must contain only its approved owned-environment connection.")
    connection = _succeeded(connections[0])
    if (not _same(connection.get("privateLinkServiceId"), environment_id)
            or connection.get("groupIds") != ["managedEnvironments"]
            or (connection.get("privateLinkServiceConnectionState") or {}).get("status") != "Approved"):
        raise RuntimeError("Azure MCP PE must be Approved and target the owned managedEnvironments resource.")


def _role_assignments(session: AzureSession, target: Target, principal: str) -> list[dict]:
    # principalId (unlike atScope) includes assignments at, ABOVE and below the
    # subscription: https://learn.microsoft.com/rest/api/authorization/role-assignments/list-for-scope
    path = f"/subscriptions/{target.subscription_id}/providers/Microsoft.Authorization/roleAssignments"
    query = {"api-version": ROLE_API, "$filter": f"principalId eq '{principal}'"}
    url = f"{ARM}{path}?{urlencode(query)}"
    seen = set()
    assignments = []
    while url:
        parsed = urlsplit(url)
        parameters = parse_qs(parsed.query)
        if (parsed.scheme != "https" or parsed.netloc != "management.azure.com"
                or parsed.path.casefold() != path.casefold() or parsed.fragment or "\\" in url
                or parameters.get("api-version") != [ROLE_API]
                or parameters.get("$filter") != [query["$filter"]]):
            raise RuntimeError("Invalid role-assignment continuation; refusing to forward ARM credentials.")
        if url in seen or len(seen) >= 20:
            raise RuntimeError("Role-assignment pagination repeated or exceeded the bounded limit.")
        seen.add(url)
        try:
            page = session.request("GET", url, audience=ARM)
        except AzureError as exc:
            if exc.status == 403:
                raise RuntimeError(
                    "Subscription/inherited role-assignment audit was denied. Obtain "
                    "Microsoft.Authorization/roleAssignments/read at subscription scope; "
                    "a resource-group-only query cannot prove the hosting identity is restricted."
                ) from exc
            raise
        values = page.get("value")
        if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
            raise RuntimeError("Invalid ARM role-assignment collection; cannot verify least privilege.")
        assignments.extend(values)
        if len(assignments) > 1000:
            raise RuntimeError("Role-assignment collection exceeded the bounded limit.")
        url = page.get("nextLink") or ""
        if not isinstance(url, str):
            raise RuntimeError("Invalid role-assignment continuation URL.")
    return assignments


def _verify_reader(session: AzureSession, target: Target, app_id: str, principal: str) -> None:
    role_id = f"/subscriptions/{target.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/{READER_ROLE}"
    assignment_name = str(uuid5(_ARM_GUID_NAMESPACE, "-".join((target.group_id, app_id, role_id))))
    assignment_id = f"{target.group_id}/providers/Microsoft.Authorization/roleAssignments/{assignment_name}"
    expected = {
        "principalId": principal, "roleDefinitionId": role_id,
        "scope": target.group_id, "principalType": "ServicePrincipal",
    }
    assignments = _role_assignments(session, target, principal)
    if len(assignments) != 1:
        raise RuntimeError("Hosting identity must have exactly one project-RG Reader assignment, with no extra permissions.")
    assignment = _arm_read(session, assignment_id, ROLE_API)
    for item in (assignments[0], assignment):
        properties = _properties(item)
        if (not _same(item.get("id"), assignment_id)
                or any(not _same(properties.get(key), value) for key, value in expected.items())
                or properties.get("condition") or properties.get("conditionVersion")
                or properties.get("delegatedManagedIdentityResourceId")):
            raise RuntimeError("Hosting identity permissions differ from the sole Bicep Reader assignment at the exact project RG.")


class _NoMcpRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise RuntimeError("Azure MCP redirected initialize; redirects/authentication proxies are not permitted.")


def verify_private_mcp_endpoint(url: str) -> None:
    """Injectable negative auth probe: private DNS/TCP, no token, no proxy, no redirects."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname
            or not re.fullmatch(rf"(?:{_DNS_LABEL}\.){{3}}azurecontainerapps\.io", parsed.netloc)
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Only the canonical standard ACA HTTPS root MCP endpoint can be probed.")
    try:
        require_private_endpoint(url)
        with socket.create_connection((parsed.hostname, 443), timeout=10):
            pass
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(_PRIVATE_NETWORK_ERROR) from exc
    request = Request(url, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
    }, data=json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "agent-factory-readonly-verifier", "version": "1"},
        },
    }).encode("utf-8"))
    # This deliberately bypasses AzureSession: the operator is NOT the project MI.
    try:
        with build_opener(ProxyHandler({}), _NoMcpRedirects()).open(request, timeout=20) as response:
            status = response.status
    except HTTPError as exc:
        status = exc.code
        exc.close()
    except (URLError, OSError) as exc:
        raise RuntimeError(_PRIVATE_NETWORK_ERROR) from exc
    if status != 401:
        raise RuntimeError(
            f"Unauthenticated MCP initialize returned HTTP {status}, expected 401. "
            "Inbound authentication is not verified; no operator-token or endpoint fallback is allowed."
        )


def _connection_body(target: Target, url: str, identity: dict) -> dict:
    return {"properties": {
        "authType": "ProjectManagedIdentity", "category": "RemoteTool",
        "target": url, "isSharedToAll": False, "audience": identity["audience"],
        "metadata": {"ApiType": "Azure", ARM_OWNER_KEY: MANAGED_BY, ARM_PROJECT_KEY: target.project_id},
    }}


def _compatible(actual, expected) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(_compatible(actual.get(key), value) for key, value in expected.items())
    if isinstance(expected, bool):
        return actual is expected
    return actual == expected


def _verify_connection(current: dict, expected: dict) -> None:
    properties = _properties(current)
    if (not _compatible(properties, expected["properties"])
            or properties.get("credentials") or properties.get("sharedUserList")):
        raise RuntimeError(
            "Existing project MCP connection has incompatible ownership, target, authentication, "
            "audience or sharing; refusing to replace it."
        )


def configure_mcp_connection(
    session: AzureSession, target: Target, plan: dict, identity: dict, *, apply: bool = False,
) -> dict:
    """Read-only verification, then optionally create a missing project connection.

    ``apply=False`` never mutates Azure and may return a prospective connection ID.
    Neither this infrastructure check nor its 401 probe verifies an actual MI tool call.
    """
    if type(apply) is not bool:
        raise ValueError("apply must be an explicit boolean.")
    plan = validate_mcp_plan(target, plan)
    _session_target(session, target)
    build_mcp_parameters(target, plan, identity, central_dns_zone_by_policy_in_hub=True)
    project = _arm_read(session, target.project_id, "2025-06-01")
    caller = project.get("identity") or {}
    if (not _same_location(project.get("location"), target.location)
            or caller.get("type") != "SystemAssigned" or caller.get("userAssignedIdentities")
            or not _same(caller.get("principalId"), identity["project_principal_id"])
            or not _same(caller.get("tenantId"), target.tenant_id)):
        raise RuntimeError("The current Foundry project managed identity does not match the prepared project caller.")
    environment_id = f"{target.group_id}/providers/Microsoft.App/managedEnvironments/{plan['environment_name']}"
    app_id = f"{target.group_id}/providers/Microsoft.App/containerApps/{plan['name']}"
    endpoint_id = f"{target.group_id}/providers/Microsoft.Network/privateEndpoints/{plan['name']}-pe"
    app = _arm_read(session, app_id, CONTAINER_APP_API)
    environment = _arm_read(session, environment_id, ENVIRONMENT_API)
    endpoint = _arm_read(session, endpoint_id, NETWORK_API)
    for resource in (app, environment, endpoint):
        _owned_arm(resource, target)
    network = _succeeded(environment)
    vnet = network.get("vnetConfiguration") or {}
    if (network.get("publicNetworkAccess") != "Disabled" or vnet.get("internal") is not True
            or not _same(vnet.get("infrastructureSubnetId"), plan["infrastructure_subnet_id"])):
        raise RuntimeError("Azure MCP environment must be internal, public access Disabled, on the exact ACA subnet.")
    principal = _verify_app(app, environment_id, target, plan, identity)
    _verify_private_endpoint(endpoint, environment_id, plan)
    _verify_reader(session, target, app_id, principal)
    url = _canonical_url(app, environment, target, plan)
    connection_id = f"{target.project_id}/connections/{CONNECTION_NAME}"
    body = _connection_body(target, url, identity)
    current = _arm_read(session, connection_id, CONNECTION_API, optional=True)
    if current is not None:
        _verify_connection(current, body)
    verify_private_mcp_endpoint(url)
    if current is None and apply:
        session.request(
            "PUT", f"{ARM}{connection_id}?{urlencode({'api-version': CONNECTION_API})}",
            body, audience=ARM, headers={"If-None-Match": "*"},
        )
        _verify_connection(_arm_read(session, connection_id, CONNECTION_API), body)
    return {
        "connection_id": connection_id,
        "tool": {
            "type": "mcp", "server_label": "azure-project-inventory", "server_url": url,
            "allowed_tools": ["group_resource_list"], "require_approval": "never",
            "project_connection_id": CONNECTION_NAME,
        },
        "project_resource_id": target.project_id, "subscription_id": target.subscription_id,
        "resource_group": target.resource_group,
        "infrastructure_verified": True, "tool_call_verified": False,
        "connection_ready": current is not None or apply,
    }


def repair_mcp_dns(session: AzureSession, target: Target, plan: dict, *, apply: bool = False) -> dict:
    """Bind only the owned, approved MCP PE to its existing hub zone when policy has not done so."""
    if type(apply) is not bool:
        raise ValueError("apply must be an explicit boolean.")
    plan = validate_mcp_plan(target, plan)
    _session_target(session, target)
    environment_id = f"{target.group_id}/providers/Microsoft.App/managedEnvironments/{plan['environment_name']}"
    endpoint_id = f"{target.group_id}/providers/Microsoft.Network/privateEndpoints/{plan['name']}-pe"
    environment = _arm_read(session, environment_id, ENVIRONMENT_API)
    endpoint = _arm_read(session, endpoint_id, NETWORK_API)
    for resource in (environment, endpoint):
        _owned_arm(resource, target)
    properties = _succeeded(environment)
    if properties.get("publicNetworkAccess") != "Disabled" or properties.get("vnetConfiguration", {}).get("internal") is not True:
        raise RuntimeError("DNS repair requires the owned private-only MCP environment.")
    _verify_private_endpoint(endpoint, environment_id, plan)
    _arm_read(session, plan["private_dns_zone_id"], "2020-06-01")
    groups = session.arm("GET", endpoint_id + "/privateDnsZoneGroups", api_version=NETWORK_API).get("value")
    if not isinstance(groups, list) or len(groups) > 1:
        raise RuntimeError("MCP DNS zone groups are unavailable or ambiguous.")
    if groups:
        group = groups[0]
        configs = _properties(group).get("privateDnsZoneConfigs") or []
        if len(configs) != 1 or not _same(
            configs[0].get("properties", {}).get("privateDnsZoneId"), plan["private_dns_zone_id"],
        ):
            raise RuntimeError("Existing MCP DNS associations differ from the selected hub zone; refusing replacement.")
        return {"resource_id": group["id"], "applied": False, "status": "already-associated"}
    group_id = endpoint_id + "/privateDnsZoneGroups/deployedByPolicy"
    if apply:
        session.request(
            "PUT", f"{ARM}{group_id}?{urlencode({'api-version': NETWORK_API})}",
            {"properties": {"privateDnsZoneConfigs": [{
                "name": "azure-mcp", "properties": {"privateDnsZoneId": plan["private_dns_zone_id"]},
            }]}},
            audience=ARM, headers={"If-None-Match": "*"},
        )
        verified = _arm_read(session, group_id, NETWORK_API)
        configs = _properties(verified).get("privateDnsZoneConfigs") or []
        if len(configs) != 1 or not _same(
            configs[0].get("properties", {}).get("privateDnsZoneId"), plan["private_dns_zone_id"],
        ):
            raise RuntimeError("MCP DNS association was not persisted as requested.")
    return {
        "resource_id": group_id, "applied": apply,
        "status": "associated" if apply else "missing-association",
        "policy_note": "The hub DNS policy owner must retain this association; policy ownership settings are unchanged.",
    }


def verify_mcp_tool_response(response, target: Target) -> dict:
    """Accept actual successful inventory output, not merely an LLM claim that a tool ran."""
    if response.status != "completed":
        raise RuntimeError("Azure MCP verification response did not complete.")
    calls = [
        item for item in response.output
        if item.type == "mcp_call" and item.name == "group_resource_list"
        and item.server_label == "azure-project-inventory"
    ]
    if len(calls) != 1 or calls[0].error:
        raise RuntimeError("Azure MCP verification requires one successful inventory tool call.")
    try:
        arguments = json.loads(calls[0].arguments)
        output = json.loads(calls[0].output)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Azure MCP returned invalid tool arguments or output JSON.") from exc
    if (not isinstance(arguments, dict)
            or not _same(arguments.get("subscription"), target.subscription_id)
            or not _same(arguments.get("resource-group"), target.resource_group)
            or not _same(arguments.get("tenant", target.tenant_id), target.tenant_id)
            or not _same(arguments.get("auth-method", "Credential"), "Credential")):
        raise RuntimeError("Azure MCP verification used an unexpected scope or authentication method.")
    results = output.get("results") if isinstance(output, dict) else None
    rows = results.get("resources") if isinstance(results, dict) else None
    if not isinstance(output, dict) or output.get("status") != 200 or not isinstance(rows, list) or not rows:
        raise RuntimeError("Azure MCP did not return a successful, nonempty resource inventory.")
    prefix = target.group_id.casefold() + "/providers/"
    if any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
           or not row["id"].casefold().startswith(prefix) for row in rows):
        raise RuntimeError("Azure MCP inventory contains resources outside the selected project.")
    ids = sorted(row["id"].casefold() for row in rows)
    return {
        "tool_call_verified": True, "verification_response_id": response.id,
        "verified_resource_count": len(rows),
        "inventory_ids_sha256": hashlib.sha256(json.dumps(ids).encode("utf-8")).hexdigest(),
    }
