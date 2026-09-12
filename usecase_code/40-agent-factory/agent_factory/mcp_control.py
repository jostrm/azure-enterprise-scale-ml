"""Target-bound, secretless control plane for the private Azure MCP server.

Planning/preflight only read Azure. Identity writes require ``apply=True``.
This module never deploys compute, changes networks, or grants Azure RBAC.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import ipaddress
import re
from urllib.parse import urlencode, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from .azure import AzureError, AzureSession
from .config import Target, identifier, required


GRAPH = "https://graph.microsoft.com"
NETWORK_API = "2024-05-01"
CONTAINER_APP_API = "2025-01-01"
MANAGED_BY = "40-agent-factory"
OWNER_TAG = f"aifactory-managed-by:{MANAGED_BY}"
ARM_OWNER_KEY = "aifactory.managed_by"
ARM_PROJECT_KEY = "aifactory.project_id"
MCP_APP_ROLE = "Mcp.Tools.ReadWrite.All"
ALLOWED_TOOLS = ("group_resource_list",)
MAX_GRAPH_PAGES = 20
MAX_GRAPH_ITEMS = 1000
_IMAGE = re.compile(r"mcr\.microsoft\.com/azure-sdk/azure-mcp@sha256:[0-9a-f]{64}")
_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
_SUBNET = re.compile(
    rf"/subscriptions/({_SEGMENT})/resourceGroups/({_SEGMENT})"
    rf"/providers/Microsoft\.Network/virtualNetworks/({_SEGMENT})/subnets/({_SEGMENT})",
    re.IGNORECASE,
)
_DNS = re.compile(
    rf"/subscriptions/({_SEGMENT})/resourceGroups/({_SEGMENT})"
    rf"/providers/Microsoft\.Network/privateDnsZones/({_SEGMENT})", re.IGNORECASE,
)
_CONFIG_KEYS = {
    "name", "infrastructure_subnet_id", "private_endpoint_subnet_id",
    "private_dns_zone_id", "image", "tools",
}
_APP_SELECT = (
    "id,appId,displayName,uniqueName,tags,signInAudience,identifierUris,api,appRoles,"
    "passwordCredentials,keyCredentials,requiredResourceAccess,web,spa,publicClient,"
    "isFallbackPublicClient,tokenEncryptionKeyId"
)
_SP_SELECT = (
    "id,appId,tags,appOwnerOrganizationId,servicePrincipalType,accountEnabled,"
    "appRoleAssignmentRequired,appRoles,oauth2PermissionScopes,passwordCredentials,"
    "keyCredentials,replyUrls"
)


def _guid(value, label: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{label} must be a GUID.") from exc


def _same(left, right) -> bool:
    return isinstance(left, str) and isinstance(right, str) and left.casefold() == right.casefold()


def _target(target: Target) -> None:
    _guid(target.subscription_id, "Target subscription")
    _guid(target.tenant_id, "Target tenant")
    for name in ("resource_group", "account_name", "project_name"):
        identifier(getattr(target, name), name)
    if not re.fullmatch(r"[a-z][a-z0-9]+", target.location):
        raise ValueError("Target location must be a canonical Azure region name.")


def _session_target(session: AzureSession, target: Target) -> None:
    if not (_same(session.subscription_id, target.subscription_id)
            and _same(session.tenant_id, target.tenant_id)):
        raise ValueError("Azure session belongs to another target subscription or tenant.")


def build_mcp_plan(target: Target, azure_mcp: dict) -> dict:
    """Build a JSON-serializable plan from the settings' azure_mcp object (no I/O)."""
    _target(target)
    if not isinstance(azure_mcp, dict) or azure_mcp.keys() - _CONFIG_KEYS:
        raise ValueError("azure_mcp accepts only documented deployment fields; never supply credentials.")
    digest = hashlib.sha256(target.project_id.casefold().encode("utf-8")).hexdigest()
    if "name" in azure_mcp:
        name = required(azure_mcp, "name")
    else:
        stem = re.sub(r"[^a-z0-9-]", "-", f"{target.account_name}-{target.project_name}".lower())
        stem = re.sub("-+", "-", stem).strip("-")
        name = f"mcp-{stem[:18].rstrip('-')}-{digest[:8]}"
    if (not re.fullmatch(r"[a-z][a-z0-9-]{0,30}[a-z0-9]", name)
            or "--" in name):
        raise ValueError("Azure MCP name must be 2-32 lowercase ACA-safe characters.")
    image = required(azure_mcp, "image")
    if not _IMAGE.fullmatch(image):
        raise ValueError("image must pin mcr.microsoft.com/azure-sdk/azure-mcp@sha256:<64 lowercase hex>.")
    tools = azure_mcp.get("tools", list(ALLOWED_TOOLS))
    if not isinstance(tools, list) or tools != list(ALLOWED_TOOLS):
        raise ValueError("tools must be exactly ['group_resource_list']; expansion requires code review.")
    infrastructure = required(azure_mcp, "infrastructure_subnet_id")
    endpoint = required(azure_mcp, "private_endpoint_subnet_id")
    parsed = []
    for resource_id in (infrastructure, endpoint):
        match = _SUBNET.fullmatch(resource_id)
        if not match or not _same(match[1], target.subscription_id):
            raise ValueError("Both subnet IDs must be exact subnet resources in the target subscription.")
        parsed.append(match)
    if infrastructure.lower().rsplit("/subnets/", 1)[0] != endpoint.lower().rsplit("/subnets/", 1)[0]:
        raise ValueError("Infrastructure and private endpoint subnets must be in the same VNet.")
    if _same(infrastructure, endpoint):
        raise ValueError("Infrastructure and private endpoint subnets must be different.")
    if parsed[0][4].lower().endswith("-aca-002"):
        raise ValueError("The Foundry -aca-002 subnet cannot host the private Azure MCP environment.")
    dns = required(azure_mcp, "private_dns_zone_id")
    dns_match = _DNS.fullmatch(dns)
    if not dns_match or not _same(dns_match[3], f"privatelink.{target.location}.azurecontainerapps.io"):
        raise ValueError("private_dns_zone_id must identify the private ACA DNS zone for the target region.")
    _guid(dns_match[1], "DNS subscription")
    return {
        "subscription_id": target.subscription_id, "tenant_id": target.tenant_id,
        "resource_group": target.resource_group, "project_resource_id": target.project_id,
        "location": target.location, "name": name, "environment_name": f"{name}-env",
        "infrastructure_subnet_id": infrastructure, "private_endpoint_subnet_id": endpoint,
        "private_dns_zone_id": dns, "image": image, "tools": list(tools),
        "unique_name": f"aifactory-mcp-{digest[:32]}",
        "project_tag": f"aifactory-project:{digest}",
        "app_role_id": str(uuid5(NAMESPACE_URL, f"{target.project_id.casefold()}#{MCP_APP_ROLE}")),
        "tags": {ARM_OWNER_KEY: MANAGED_BY, ARM_PROJECT_KEY: target.project_id},
    }


def validate_mcp_plan(target: Target, plan: dict) -> dict:
    """Revalidate all serialized plan fields against the selected target; return a copy."""
    if not isinstance(plan, dict):
        raise ValueError("An Azure MCP deployment plan must be an object.")
    expected = build_mcp_plan(target, {key: plan[key] for key in _CONFIG_KEYS if key in plan})
    if plan != expected:
        raise ValueError("Azure MCP plan is modified, incomplete, or bound to another project/target.")
    return deepcopy(expected)


def _arm_read(session: AzureSession, resource_id: str, api_version: str, *, optional=False):
    try:
        result = session.arm("GET", resource_id, api_version=api_version)
    except AzureError as exc:
        if optional and exc.status == 404:
            return None
        raise
    if not isinstance(result, dict) or not _same(result.get("id"), resource_id):
        raise RuntimeError("ARM returned an unexpected resource ID; refusing cross-resource reuse.")
    return result


def _owned_arm(resource: dict, target: Target) -> None:
    tags = resource.get("tags") or {}
    if (tags.get(ARM_OWNER_KEY) != MANAGED_BY
            or not _same(tags.get(ARM_PROJECT_KEY), target.project_id)):
        raise RuntimeError("Existing ACA resource collision: managed_by/project ownership tags do not match.")
    if not _same(resource.get("location"), target.location):
        raise RuntimeError("Existing ACA resource region does not match the selected target.")


def _subnet_properties(resource: dict) -> dict:
    properties = resource.get("properties")
    if not isinstance(properties, dict):
        raise RuntimeError("Subnet properties are unavailable; cannot validate network isolation.")
    return properties


def _check_infrastructure(subnet: dict, environment_id: str | None) -> None:
    properties = _subnet_properties(subnet)
    prefixes = properties.get("addressPrefixes") or [properties.get("addressPrefix")]
    try:
        networks = [ipaddress.ip_network(prefix, strict=True) for prefix in prefixes]
    except (ValueError, TypeError) as exc:
        raise ValueError("Infrastructure subnet must have valid IPv4 address prefixes.") from exc
    if not networks or any(net.version != 4 or net.prefixlen > 27 for net in networks):
        raise ValueError("Infrastructure subnet must be IPv4 /27 or larger.")
    delegations = properties.get("delegations", [])
    if (not isinstance(delegations, list) or len(delegations) != 1
            or delegations[0].get("properties", {}).get("serviceName") != "Microsoft.App/environments"):
        raise ValueError("Infrastructure subnet must be delegated exactly to Microsoft.App/environments.")
    for key in ("ipConfigurations", "privateEndpoints", "serviceAssociationLinks", "resourceNavigationLinks"):
        entries = properties.get(key, [])
        if not isinstance(entries, list):
            raise ValueError(f"Infrastructure subnet {key} cannot be verified.")
        for entry in entries:
            details = entry.get("properties") or {}
            references = [details.get(field) for field in ("link", "linkedResourceId", "linkedResource")]
            if not environment_id or not any(_same(value, environment_id) for value in references):
                raise ValueError(f"Infrastructure subnet {key} is in use outside the owned ACA environment.")


def preflight_mcp(session: AzureSession, target: Target, plan: dict) -> dict:
    """Read ARM resources and obtain the *project* identity; never mutate Azure."""
    plan = validate_mcp_plan(target, plan)
    _session_target(session, target)
    project = _arm_read(session, target.project_id, "2025-06-01")
    if not _same(project.get("location"), target.location):
        raise RuntimeError("Project region does not match the selected target.")
    identity = project.get("identity") or {}
    principal_id = _guid(identity.get("principalId"), "Project identity.principalId")
    if identity.get("tenantId") and not _same(identity["tenantId"], target.tenant_id):
        raise RuntimeError("Project managed identity belongs to another tenant.")
    vnet_id = plan["infrastructure_subnet_id"][:plan["infrastructure_subnet_id"].lower().rfind("/subnets/")]
    vnet = _arm_read(session, vnet_id, NETWORK_API)
    if not _same(vnet.get("location"), target.location):
        raise RuntimeError("VNet region does not match the selected target.")
    environment_id = f"{target.group_id}/providers/Microsoft.App/managedEnvironments/{plan['environment_name']}"
    app_id = f"{target.group_id}/providers/Microsoft.App/containerApps/{plan['name']}"
    environment = _arm_read(session, environment_id, CONTAINER_APP_API, optional=True)
    app = _arm_read(session, app_id, CONTAINER_APP_API, optional=True)
    if environment:
        _owned_arm(environment, target)
        properties = environment.get("properties") or {}
        network = properties.get("vnetConfiguration") or {}
        if properties.get("publicNetworkAccess") != "Disabled" or network.get("internal") is not True:
            raise RuntimeError("Existing public ACA environment cannot be converted in place.")
        if not _same(network.get("infrastructureSubnetId"), plan["infrastructure_subnet_id"]):
            raise RuntimeError("Existing ACA environment belongs to another infrastructure subnet.")
    if app:
        _owned_arm(app, target)
        properties = app.get("properties") or {}
        if not environment or not _same(
            properties.get("managedEnvironmentId") or properties.get("environmentId"), environment_id,
        ):
            raise RuntimeError("Existing ACA app belongs to another or missing environment.")
    infrastructure = _arm_read(session, plan["infrastructure_subnet_id"], NETWORK_API)
    endpoint = _arm_read(session, plan["private_endpoint_subnet_id"], NETWORK_API)
    _check_infrastructure(infrastructure, environment_id if environment else None)
    if _subnet_properties(endpoint).get("delegations"):
        raise ValueError("Private endpoint subnet must not be delegated.")
    _arm_read(session, plan["private_dns_zone_id"], "2020-06-01")
    return {
        "project_resource_id": target.project_id, "project_principal_id": principal_id,
        "tenant_id": target.tenant_id, "subscription_id": target.subscription_id,
        "environment_resource_id": environment_id, "container_app_resource_id": app_id,
        "environment_exists": environment is not None, "container_app_exists": app is not None,
    }


def _graph_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com"
            or parsed.username or parsed.password or parsed.fragment
            or not parsed.path.startswith("/v1.0/") or "\\" in url):
        raise RuntimeError("Invalid Graph continuation URL; refusing to forward credentials.")


def _graph(session: AzureSession, method: str, path: str, body=None) -> dict:
    url = path if path.startswith("https://") else f"{GRAPH}/v1.0/{path}"
    _graph_url(url)
    try:
        return session.request(method, url, body, audience=GRAPH)
    except AzureError as exc:
        if exc.status == 403 or "Authorization_RequestDenied" in str(exc):
            raise RuntimeError(
                "Microsoft Graph denied Azure MCP identity administration. Ask an Entra administrator "
                "to approve the operator's Application.ReadWrite.All (or appropriate owned-app access), "
                "Application.Read.All, Directory.Read.All (delegated-grant audit), and "
                "AppRoleAssignment.ReadWrite.All permissions and an appropriate "
                "Entra role. No credential, delegated-user, Azure CLI/VSCode, or RBAC fallback is allowed."
            ) from exc
        raise


def _graph_pages(session: AzureSession, path: str) -> list[dict]:
    url = f"{GRAPH}/v1.0/{path}"
    seen = set()
    items = []
    while url:
        _graph_url(url)
        if url in seen or len(seen) >= MAX_GRAPH_PAGES:
            raise RuntimeError("Graph pagination repeated or exceeded the bounded page limit.")
        seen.add(url)
        page = _graph(session, "GET", url)
        values = page.get("value")
        if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
            raise RuntimeError("Graph returned an invalid collection.")
        items.extend(values)
        if len(items) > MAX_GRAPH_ITEMS:
            raise RuntimeError("Graph collection exceeded the bounded item limit.")
        url = page.get("@odata.nextLink") or ""
        if not isinstance(url, str):
            raise RuntimeError("Invalid Graph continuation URL.")
    return items


def _find(session: AzureSession, collection: str, key: str, value: str, select: str):
    literal = value.replace("'", "''")
    query = urlencode({"$filter": f"{key} eq '{literal}'", "$select": select, "$top": "2"})
    matches = _graph_pages(session, f"{collection}?{query}")
    if len(matches) > 1:
        raise RuntimeError(f"Graph {collection} collision: expected at most one exact match.")
    if matches and matches[0].get(key) != value:
        raise RuntimeError(f"Graph {collection} returned a non-matching identity.")
    return matches[0] if matches else None


def _owned_graph(resource: dict, plan: dict) -> None:
    tags = resource.get("tags") or []
    if (not isinstance(tags, list) or OWNER_TAG not in tags or plan["project_tag"] not in tags
            or any(tag.startswith("aifactory-project:") and tag != plan["project_tag"] for tag in tags)
            or any(tag.startswith("aifactory-managed-by:") and tag != OWNER_TAG for tag in tags)):
        raise RuntimeError("Graph identity collision: ownership/project tags do not match; refusing takeover.")


def _role(plan: dict) -> dict:
    return {
        "id": plan["app_role_id"], "allowedMemberTypes": ["Application"],
        "displayName": "Invoke approved Azure MCP tools",
        "description": "Invoke MCP tools; this role grants no Azure RBAC permissions.",
        "isEnabled": True, "value": MCP_APP_ROLE,
    }


def _validate_roles(resource: dict, plan: dict) -> None:
    roles = resource.get("appRoles") or []
    if len(roles) != 1 or any(
        roles[0].get(key) != _role(plan)[key]
        for key in ("id", "allowedMemberTypes", "isEnabled", "value")
    ):
        raise RuntimeError("Graph identity appRoles must contain only the project's Application-only MCP invoke role.")
    if roles[0].get("origin", "Application") != "Application":
        raise RuntimeError("Service-principal-local app roles cannot replace the application-owned role.")


def _no_credentials(resource: dict) -> None:
    if resource.get("passwordCredentials") or resource.get("keyCredentials"):
        raise RuntimeError("Existing Graph identity has secret/certificate credentials; refusing reuse.")


def _validate_application(session: AzureSession, app: dict, plan: dict) -> None:
    _owned_graph(app, plan)
    _guid(app.get("id"), "Application object ID")
    client_id = _guid(app.get("appId"), "Application client ID")
    if app.get("uniqueName") != plan["unique_name"] or app.get("signInAudience") != "AzureADMyOrg":
        raise RuntimeError("Application must be the exact single-tenant, target-bound API registration.")
    _no_credentials(app)
    _validate_roles(app, plan)
    api = app.get("api") or {}
    if (api.get("requestedAccessTokenVersion") != 2 or api.get("acceptMappedClaims")
            or api.get("oauth2PermissionScopes") or api.get("preAuthorizedApplications")
            or api.get("knownClientApplications") or app.get("requiredResourceAccess")
            or app.get("isFallbackPublicClient") or app.get("tokenEncryptionKeyId")):
        raise RuntimeError("Application has unsupported token/delegated/client permissions; refusing reuse.")
    web = app.get("web") or {}
    if (any((app.get(key) or {}).get("redirectUris") for key in ("web", "spa", "publicClient"))
            or any((web.get("implicitGrantSettings") or {}).values())):
        raise RuntimeError("Application must not enable user, public-client, or implicit authentication.")
    # A crash after POST /applications can leave this one harmless incomplete field.
    if app.get("identifierUris") not in ([], [f"api://{client_id}"]):
        raise RuntimeError("Application audience must be exactly api://<application-client-id>.")
    if _graph_pages(session, f"applications/{app['id']}/federatedIdentityCredentials"):
        raise RuntimeError("API application must not have federated identity credentials.")


def _validate_sp(sp: dict, app: dict, target: Target, plan: dict) -> None:
    _owned_graph(sp, plan)
    _guid(sp.get("id"), "Service principal ID")
    if (not _same(sp.get("appId"), app["appId"])
            or not _same(sp.get("appOwnerOrganizationId"), target.tenant_id)
            or sp.get("servicePrincipalType") != "Application"):
        raise RuntimeError("Service principal is not this tenant's target-bound API application.")
    if sp.get("appRoleAssignmentRequired") is not True or sp.get("accountEnabled") is not True:
        raise RuntimeError("Service principal must be enabled with appRoleAssignmentRequired=true.")
    _no_credentials(sp)
    _validate_roles(sp, plan)
    if sp.get("oauth2PermissionScopes") or sp.get("replyUrls"):
        raise RuntimeError("Service principal has delegated/user authentication configured; refusing reuse.")


def _assignments(session: AzureSession, sp: dict, principal_id: str, plan: dict) -> list[dict]:
    assignments = _graph_pages(session, f"servicePrincipals/{sp['id']}/appRoleAssignedTo")
    if len(assignments) > 1 or any(
        not _same(item.get("principalId"), principal_id)
        or not _same(item.get("resourceId"), sp["id"])
        or not _same(item.get("appRoleId"), plan["app_role_id"])
        or item.get("principalType") != "ServicePrincipal"
        for item in assignments
    ):
        raise RuntimeError("API role assignments must contain only the exact project's managed-identity caller.")
    if _graph_pages(session, f"servicePrincipals/{sp['id']}/appRoleAssignments"):
        raise RuntimeError("API service principal has outbound application permissions; refusing reuse.")
    if _graph_pages(session, f"servicePrincipals/{sp['id']}/oauth2PermissionGrants"):
        raise RuntimeError("API service principal has delegated permission grants; refusing reuse.")
    query = urlencode({"$filter": f"resourceId eq '{sp['id']}'"})
    if _graph_pages(session, f"oauth2PermissionGrants?{query}"):
        raise RuntimeError("API has incoming delegated/user permission grants; refusing reuse.")
    return assignments


def prepare_mcp_identity(session: AzureSession, target: Target, plan: dict, *, apply: bool = False) -> dict:
    """Read/prepare one Entra API app, SP, and project-MI app-role assignment.

    Every call repeats ARM preflight. Existing mismatches fail rather than being
    overwritten. Graph POST/PATCH is never retried here; rerun after inspecting
    an ambiguous failure. Returned values contain identifiers/status, not tokens.
    """
    if type(apply) is not bool:
        raise ValueError("apply must be an explicit boolean.")
    plan = validate_mcp_plan(target, plan)
    checked = preflight_mcp(session, target, plan)
    principal_id = checked["project_principal_id"]
    caller = _graph(session, "GET", f"servicePrincipals/{principal_id}?$select=id,servicePrincipalType")
    if not _same(caller.get("id"), principal_id) or caller.get("servicePrincipalType") != "ManagedIdentity":
        raise RuntimeError("The ARM project's principalId is not a managed-identity service principal.")
    app = _find(session, "applications", "uniqueName", plan["unique_name"], _APP_SELECT)
    sp = None
    assignments = []
    if app:
        _validate_application(session, app, plan)
        sp = _find(session, "servicePrincipals", "appId", app["appId"], _SP_SELECT)
        if sp:
            _validate_sp(sp, app, target, plan)
            assignments = _assignments(session, sp, principal_id, plan)
    if apply:
        if not app:
            body = {
                "displayName": f"{plan['name']}-api", "uniqueName": plan["unique_name"],
                "tags": [OWNER_TAG, plan["project_tag"]], "signInAudience": "AzureADMyOrg",
                "appRoles": [_role(plan)], "identifierUris": [], "requiredResourceAccess": [],
                "passwordCredentials": [], "keyCredentials": [], "isFallbackPublicClient": False,
                "api": {"requestedAccessTokenVersion": 2, "oauth2PermissionScopes": [],
                        "preAuthorizedApplications": [], "knownClientApplications": []},
                "web": {"redirectUris": [], "implicitGrantSettings": {
                    "enableAccessTokenIssuance": False, "enableIdTokenIssuance": False}},
                "spa": {"redirectUris": []}, "publicClient": {"redirectUris": []},
            }
            created = _graph(session, "POST", "applications", body)
            object_id = _guid(created.get("id"), "Created application object ID")
            app = _graph(session, "GET", f"applications/{object_id}?{urlencode({'$select': _APP_SELECT})}")
            _validate_application(session, app, plan)
        client_id = _guid(app["appId"], "Application client ID")
        if not app["identifierUris"]:
            _graph(session, "PATCH", f"applications/{app['id']}", {"identifierUris": [f"api://{client_id}"]})
            app = _graph(session, "GET", f"applications/{app['id']}?{urlencode({'$select': _APP_SELECT})}")
            _validate_application(session, app, plan)
            if app["identifierUris"] != [f"api://{client_id}"]:
                raise RuntimeError("Graph has not persisted the API audience; inspect and rerun.")
        if not sp:
            created = _graph(session, "POST", "servicePrincipals", {
                "appId": client_id, "tags": [OWNER_TAG, plan["project_tag"]],
                "appRoleAssignmentRequired": True, "accountEnabled": True,
            })
            object_id = _guid(created.get("id"), "Created service principal ID")
            sp = _graph(session, "GET", f"servicePrincipals/{object_id}?{urlencode({'$select': _SP_SELECT})}")
            _validate_sp(sp, app, target, plan)
            assignments = _assignments(session, sp, principal_id, plan)
        # Read again immediately before granting, never replace other callers.
        assignments = _assignments(session, sp, principal_id, plan)
        if not assignments:
            _graph(session, "POST", f"servicePrincipals/{principal_id}/appRoleAssignments", {
                "principalId": principal_id, "resourceId": sp["id"], "appRoleId": plan["app_role_id"],
            })
        app = _graph(session, "GET", f"applications/{app['id']}?{urlencode({'$select': _APP_SELECT})}")
        _validate_application(session, app, plan)
        sp = _graph(session, "GET", f"servicePrincipals/{sp['id']}?{urlencode({'$select': _SP_SELECT})}")
        _validate_sp(sp, app, target, plan)
        assignments = _assignments(session, sp, principal_id, plan)
        if len(assignments) != 1:
            raise RuntimeError("Graph has not persisted the project-only role assignment; inspect and rerun.")
    return {
        "tenant_id": target.tenant_id, "subscription_id": target.subscription_id,
        "project_resource_id": target.project_id, "project_principal_id": principal_id,
        "application_object_id": app["id"] if app else None,
        "application_client_id": app["appId"] if app else None,
        "service_principal_id": sp["id"] if sp else None, "app_role_id": plan["app_role_id"],
        "audience": f"api://{app['appId']}" if app else None,
        "ready": bool(app and sp and assignments and app["identifierUris"]), "applied": apply,
    }


def build_mcp_parameters(target: Target, plan: dict, identity: dict, *,
                         central_dns_zone_by_policy_in_hub: bool) -> dict:
    """Build a standard ARM deployment-parameters JSON document; never deploy."""
    plan = validate_mcp_plan(target, plan)
    if type(central_dns_zone_by_policy_in_hub) is not bool:
        raise ValueError("central_dns_zone_by_policy_in_hub must be an explicit boolean.")
    if not isinstance(identity, dict) or identity.get("ready") is not True or any(
        not _same(identity.get(key), expected) for key, expected in (
            ("tenant_id", target.tenant_id), ("subscription_id", target.subscription_id),
            ("project_resource_id", target.project_id), ("app_role_id", plan["app_role_id"]),
        )
    ):
        raise ValueError("A ready Entra identity bound to this exact project/target is required.")
    client_id = _guid(identity.get("application_client_id"), "Entra application client ID")
    for key in ("project_principal_id", "application_object_id", "service_principal_id"):
        _guid(identity.get(key), key)
    if identity.get("audience") != f"api://{client_id}":
        raise ValueError("Entra audience does not match the application client ID.")
    values = {
        "projectResourceGroup": target.resource_group, "name": plan["name"],
        "location": target.location, "infrastructureSubnetId": plan["infrastructure_subnet_id"],
        "privateEndpointSubnetId": plan["private_endpoint_subnet_id"], "tenantId": target.tenant_id,
        "entraApiApplicationClientId": client_id, "containerImage": plan["image"],
        "allowedTools": list(plan["tools"]), "privateDnsZoneResourceId": plan["private_dns_zone_id"],
        "centralDnsZoneByPolicyInHub": central_dns_zone_by_policy_in_hub,
        "tags": dict(plan["tags"]),
    }
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0", "parameters": {key: {"value": value} for key, value in values.items()},
    }
