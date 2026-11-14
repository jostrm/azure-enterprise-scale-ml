"""Pure preparation for a separate, governed Factory MCP project connection.

No Azure client, credentials, discovery, deployment, or execution path is present.
The operator supplies the *new* API application's client ID; this module cannot
prove its ownership, endpoint readiness, or absence of an existing connection.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from .policy import (
    APPLICATION_READ_ROLE as REQUIRED_ROLE,
    DEFAULT_APPLICATION_TOOLS as DEFAULT_ALLOWED_TOOLS,
    COST_APPLICATION_TOOLS as COST_TOOLS,
    GRAPH_APPLICATION_TOOLS as GRAPH_TOOLS,
    READ_ONLY_APPLICATION_TOOLS as READ_ONLY_TOOLS,
)
_PROTECTED_NAMES = frozenset({"aif-azure-mcp", "aif-mcp-project001-dev"})
_DNS_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,62}[A-Za-z0-9])?"
_UPDATE_POLICY = (
    "append only after reviewing existing agent tools/version; never replace existing connections"
)


def _uuid(value: UUID | str, field: str) -> UUID:
    if isinstance(value, UUID):
        result = value
    elif isinstance(value, str) and re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value,
    ):
        result = UUID(value)
    else:
        raise ValueError(f"{field} requires an explicit UUID.")
    if not result.int:
        raise ValueError(f"{field} requires a nonzero UUID.")
    return result


def _safe_name(value: str, field: str, pattern: str = _NAME) -> None:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"{field} must be a safe literal identifier.")


def _not_protected(value: str) -> None:
    if any(name in value.casefold() for name in _PROTECTED_NAMES):
        raise ValueError("The existing Microsoft Azure MCP service and connection are protected.")


def _mcp_url(value: str) -> None:
    message = "mcp_url must be an exact canonical HTTPS DNS URL ending /mcp, without credentials or URL modifiers."
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(ord(char) < 33 or ord(char) > 126 for char in value)
            or any(char in value for char in "\\%?#")):
        raise ValueError(message)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.netloc != host
                or not re.fullmatch(rf"{_DNS_LABEL}(?:\.{_DNS_LABEL})+", host)
                or len(host) > 253 or host.endswith(".localhost")
                or parsed.username is not None or parsed.password is not None
                or parsed.port is not None
                or value != f"https://{host}{parsed.path}"):
            raise ValueError(message)
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError(message)
        parts = parsed.path.split("/")
        if (parts[0] != "" or parts[-1] != "mcp"
                or any(not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", part) for part in parts[1:])):
            raise ValueError(message)
    except (ValueError, TypeError):
        raise ValueError(message) from None
    _not_protected(value)


def _tools(value: tuple[str, ...]) -> tuple[str, ...]:
    if (not isinstance(value, (list, tuple)) or not value
            or any(not isinstance(tool, str) or tool not in READ_ONLY_TOOLS for tool in value)
            or len(set(value)) != len(value)):
        raise ValueError("allowed_tools must be a nonempty, unique list of explicitly supported read-only tools.")
    return tuple(value)


@dataclass(frozen=True)
class RegistrationTarget:
    """Explicit operator input, normalized once and immutable thereafter."""

    subscription_id: UUID
    tenant_id: UUID
    resource_group: str
    foundry_account: str
    foundry_project: str
    project_principal_id: UUID
    project_client_id: UUID
    mcp_application_id: UUID
    mcp_url: str
    connection_name: str = "aifactory-governed-mcp"
    server_label: str = "aifactory-governed"
    service_name: str = "aifactory-governed-mcp"
    allowed_tools: tuple[str, ...] = DEFAULT_ALLOWED_TOOLS

    def __post_init__(self) -> None:
        for field in (
            "subscription_id", "tenant_id", "project_principal_id", "project_client_id", "mcp_application_id",
        ):
            object.__setattr__(self, field, _uuid(getattr(self, field), field))
        _safe_name(self.resource_group, "resource_group", r"[A-Za-z0-9_()][A-Za-z0-9_.()-]{0,89}")
        if self.resource_group.endswith("."):
            raise ValueError("resource_group cannot end with a period.")
        for field in ("foundry_account", "foundry_project", "connection_name", "server_label"):
            _safe_name(getattr(self, field), field)
        _safe_name(self.service_name, "service_name", _DNS_LABEL)
        for value in (self.connection_name, self.server_label, self.service_name):
            _not_protected(value)
        _mcp_url(self.mcp_url)
        object.__setattr__(self, "allowed_tools", _tools(self.allowed_tools))
        if len({self.mcp_application_id, self.project_principal_id, self.project_client_id}) != 3:
            raise ValueError("The new MCP application ID, project principal ID and project client ID must be distinct.")

    @property
    def project_resource_id(self) -> str:
        return (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{self.foundry_account}"
            f"/projects/{self.foundry_project}"
        )

    @property
    def connection_resource_id(self) -> str:
        return f"{self.project_resource_id}/connections/{self.connection_name}"


@dataclass(frozen=True)
class ApplicationRole:
    """An operator-reviewed existing role, not an arbitrary permission grant."""

    id: UUID
    value: str = REQUIRED_ROLE
    allowed_member_types: tuple[str, ...] = ("Application",)
    is_enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _uuid(self.id, "Application role ID"))
        if (self.value != REQUIRED_ROLE or self.is_enabled is not True
                or not isinstance(self.allowed_member_types, (tuple, list))
                or tuple(self.allowed_member_types) != ("Application",)):
            raise ValueError("An existing role must be enabled and grant only AiFactory.Mcp.Read to Application.")
        object.__setattr__(self, "allowed_member_types", tuple(self.allowed_member_types))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "allowedMemberTypes": list(self.allowed_member_types),
            "value": self.value,
            "displayName": "AI Factory MCP read",
            "description": "Read explicitly allowed AI Factory MCP tools as an application.",
            "isEnabled": self.is_enabled,
        }


def build_registration_plan(
    target: RegistrationTarget,
    *,
    scope_key: str,
    existing_application_role: ApplicationRole | None = None,
) -> dict[str, Any]:
    """Return a deterministic JSON-compatible preview; never read or write Azure.

    ``scope_key`` must identify an existing operator-approved agent scope. The
    resulting auth/grant objects are merge proposals, never replacement settings.
    An optional existing role must have been verified for this new API app.
    """
    if not isinstance(target, RegistrationTarget):
        raise ValueError("A validated RegistrationTarget is required.")
    _safe_name(scope_key, "scope_key", r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
    if existing_application_role is not None and not isinstance(existing_application_role, ApplicationRole):
        raise ValueError("A validated ApplicationRole is required.")
    role = existing_application_role or ApplicationRole(id=uuid5(target.mcp_application_id, REQUIRED_ROLE))
    target_json = {
        key: str(value) if isinstance(value, UUID) else list(value) if isinstance(value, tuple) else value
        for key, value in asdict(target).items()
    }
    target_json["project_resource_id"] = target.project_resource_id
    plan: dict[str, Any] = {
        "mode": "plan-only",
        "target": target_json,
        "scope_key": scope_key,
        "application_auth": {
            "audience": str(target.mcp_application_id),
            "required_role": REQUIRED_ROLE,
            "identities": [{
                "object_id": str(target.project_principal_id),
                "client_id": str(target.project_client_id),
                "scope_keys": [scope_key],
                "allowed_tools": list(target.allowed_tools),
            }],
        },
        "required_agent_grant": {
            "object_id": str(target.project_principal_id),
            "scopes": [scope_key],
            "permissions": (
                ["factory.read"]
                + (["cost.read"] if COST_TOOLS.intersection(target.allowed_tools) else [])
                + (["graph.read"] if GRAPH_TOOLS.intersection(target.allowed_tools) else [])
            ),
        },
        "entra_app_template": {
            "applicationId": str(target.mcp_application_id),
            "requiredApplicationRole": role.to_dict(),
            "api": {"requestedAccessTokenVersion": 2},
            "optionalClaims": {"accessToken": [{"name": "idtyp", "essential": True}]},
            "servicePrincipalRequirements": {"appRoleAssignmentRequired": True},
        },
        "required_app_role_assignment": {
            "principalId": str(target.project_principal_id),
            "resourceApplicationId": str(target.mcp_application_id),
            "appRoleId": str(role.id),
        },
        "connection_request": {
            "method": "PUT",
            "resource_id": target.connection_resource_id,
            "url": (
                f"https://management.azure.com{target.connection_resource_id}"
                "?api-version=2025-10-01-preview"
            ),
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
                    "aifactory.project_id": target.project_resource_id,
                },
            }},
        },
        "agent_tool": {
            "type": "mcp",
            "server_label": target.server_label,
            "server_url": target.mcp_url,
            "allowed_tools": list(target.allowed_tools),
            "require_approval": "always",
            # Foundry's project-local connection selector is the name, not its ARM resource ID.
            "project_connection_id": target.connection_name,
        },
        "updatePolicy": _UPDATE_POLICY,
        "token_routing": (
            "Keep the existing delegated audience and user-token validation separate from this new MCP "
            "application audience. Require app-only idtyp=app, the exact tenant, caller IDs and read role."
        ),
        "review_required": [
            "Verify the new API application, project identity and exact configured scope belong to this target.",
            "Merge auth identities and the required agent grant only after reviewing existing configuration.",
            "Resolve the API service principal before assigning the application role; no operator token fallback.",
            "Verify the separately named MCP endpoint, TLS and private connectivity; none have been probed.",
            "Read the named connection before creation; abort if it exists, including on a conditional-write conflict.",
            "Preserve existing prompt, model, connections and tools; append this tool only to a reviewed agent version.",
            "Infrastructure scaffolding, deployment, Entra changes and registration need separate approval.",
            "Graph tools require separately enabled, exact-scope graph configuration and a reviewed snapshot; "
            "advertising tools or this plan grants no corpus access.",
        ],
    }
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    plan["plan_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return plan
