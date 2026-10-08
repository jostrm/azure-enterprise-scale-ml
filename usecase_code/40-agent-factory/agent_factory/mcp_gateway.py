"""Opt-in AI Factory MCP hosting and new-tier AI Gateway integration for project001 Dev.

Flags (exact names) drive one late project-pipeline step:
- enableAIFactoryMCP hosts the governed, read-only AI Factory MCP as a private project Container App.
- enableAIGatewaySKU creates (or adopts an explicitly named) AI Gateway (SKU AIGateway) wired to the
  project Microsoft Foundry account through its managed identity.
- addAIFactoryMCP2AIGatewaySKU registers the MCP as an exact read-only gateway tool server.

False never deletes or detaches anything. Resources are only created or updated when this integration
owns them (tags or a description marker); foreign resources with the derived names are refused. Every
write is a read-before-write PUT/PATCH; nothing here deletes.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol

from .azure import ARM, AzureError

FLAGS = ("enableAIFactoryMCP", "enableAIGatewaySKU", "addAIFactoryMCP2AIGatewaySKU")
PROJECT_NUMBER = "001"
ENVIRONMENT = "dev"
SCOPE_KEY = "project001-dev"
OWNER_TAG = "aifactory-integration"
OWNER_VALUE = "mcp-ai-gateway"
OWNER_TAGS = {OWNER_TAG: OWNER_VALUE, "aifactory-scope": SCOPE_KEY}
MARKER = f"[managed-by: aifactory {OWNER_VALUE} {SCOPE_KEY}]"
READ_ONLY_TOOLS = ("factory_health", "factory_capabilities", "factory_skills")
NAMESPACE = "aifactory"
REQUIRED_ROLE = "AiFactory.Mcp.Read"
API_KEY_SECRET = "factory-api-key"
AZURE_AI_USER_ROLE = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
ACR_PULL_ROLE = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/"
RESOURCES_API = "2021-04-01"
COGNITIVE_API = "2025-06-01"
IDENTITY_API = "2023-01-31"
APP_API = "2024-03-01"
REGISTRY_API = "2023-07-01"
ROLE_API = "2022-04-01"
GATEWAY_API = "2025-09-01-preview"
GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
IMAGE = re.compile(r"^(?P<server>[a-z0-9][a-z0-9.-]*\.azurecr\.io)/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$")
GATEWAY_ID = re.compile(
    r"^/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/]+/providers/Microsoft\.ApiManagement/service/[A-Za-z][A-Za-z0-9-]{0,49}$")
SUBNET_ID = re.compile(
    r"^/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/]+/providers/Microsoft\.Network/virtualNetworks/[^/]+/subnets/[^/]+$")
KNOWLEDGE_INCLUDES = [
    "documentation/v2/**/*.md", "usecase_code/30-machine-learning/**/*.md",
    "usecase_code/20-agent-foundry/**/*.md", "usecase_code/20-agent-foundry/**/*.py",
    "usecase_code/40-agent-factory/readme.md", "usecase_code/40-agent-factory/agent_factory/readme.md",
    "environment_setup/azurefactory-cli/readme.md",
    "environment_setup/install_config_wizard/api-usage-examples/**/*.md",
    "bootstrap/python-sdk/*.py", "RELEASE_*.md",
]
KNOWLEDGE_EXCLUDES = [
    "**/.git/**", "**/.env*", "**/*secret*", "**/*credential*", "**/__pycache__/**", "**/node_modules/**",
    "**/.venv/**", "**/output/**", "**/dist/**", "**/build/**", "**/tests/**", "**/.local/**",
    "**/_legacy/**", "**/*eval*",
]


class ArmPort(Protocol):
    def request(self, method: str, url: str, body: dict | None = None, *, audience: str = ARM,
                headers: dict[str, str] | None = None) -> dict: ...

    def arm(self, method: str, resource_id: str, body: dict | None = None, api_version: str = ...) -> dict: ...

    def pages(self, url: str, *, audience: str = ARM, field: str = "value") -> list[dict]: ...


def flag(value, name: str) -> bool:
    """Accept only the canonical pipeline booleans; unset ADO macros count as false."""
    if value is True or value == "true":
        return True
    if value in (False, "false", None, "") or _unset_macro(value):
        return False
    raise ValueError(f"{name} must be true or false.")


def _unset_macro(value) -> bool:
    return isinstance(value, str) and value.startswith("$(") and value.endswith(")")


def _text(value) -> str:
    return "" if value is None or _unset_macro(value) else str(value).strip()


@dataclass(frozen=True)
class IntegrationRequest:
    enable_mcp: bool
    enable_gateway: bool
    add_mcp_to_gateway: bool
    subscription_id: str
    tenant_id: str
    resource_group: str
    environment: str
    project_number: str
    location: str
    factory_key: str = "aifactory"
    enable_container_apps: bool = False
    enable_ai_foundry: bool = False
    delete_requested: bool = False
    mcp_image: str = ""
    api_image: str = ""
    entra_app_id: str = ""
    container_apps_environment: str = ""
    gateway_resource_id: str = ""
    gateway_subnet_id: str = ""

    @property
    def any_enabled(self) -> bool:
        return self.enable_mcp or self.enable_gateway or self.add_mcp_to_gateway

    @classmethod
    def from_values(cls, values: Mapping[str, object]) -> "IntegrationRequest":
        """Build from pipeline variables (variables.yaml / .env / variables.json names)."""
        get = values.get
        prefix = _text(get("admin_aifactoryPrefixRG"))
        number = _text(get("project_number_000")).zfill(3)
        environment = _text(get("dev_test_prod")).lower()
        group = _text(get("projectResourceGroup")) or (
            f"{prefix}{_text(get('projectPrefix'))}project{number}-{_text(get('admin_locationSuffix'))}"
            f"-{environment}{_text(get('admin_aifactorySuffixRG'))}{_text(get('projectSuffix'))}")
        return cls(
            enable_mcp=flag(get("enableAIFactoryMCP"), "enableAIFactoryMCP"),
            enable_gateway=flag(get("enableAIGatewaySKU"), "enableAIGatewaySKU"),
            add_mcp_to_gateway=flag(get("addAIFactoryMCP2AIGatewaySKU"), "addAIFactoryMCP2AIGatewaySKU"),
            subscription_id=_text(get("dev_test_prod_sub_id")).lower(),
            tenant_id=_text(get("tenantId")).lower(),
            resource_group=group, environment=environment, project_number=number,
            location=_text(get("admin_location")).lower(),
            factory_key=re.sub(r"[^A-Za-z0-9_-]", "", prefix).strip("-_")[:80] or "aifactory",
            enable_container_apps=flag(get("enableContainerApps"), "enableContainerApps"),
            enable_ai_foundry=flag(get("enableAIFoundry"), "enableAIFoundry"),
            delete_requested=any(flag(get(name), name) for name in ("deleteAllServicesForProject", "deleteAllForProject")),
            mcp_image=_text(get("aifactoryMcpImage")), api_image=_text(get("aifactoryMcpApiImage")),
            entra_app_id=_text(get("aifactoryMcpEntraAppId")).lower(),
            container_apps_environment=_text(get("aifactoryMcpContainerAppsEnvironment")),
            gateway_resource_id=_text(get("aiGatewaySkuResourceId")),
            gateway_subnet_id=_text(get("aiGatewaySkuOutboundSubnetId")),
        )


@dataclass
class Decision:
    act: bool
    reason: str


def decide(request: IntegrationRequest) -> Decision:
    """Validate intent offline; invalid combinations raise instead of being ignored."""
    if not request.any_enabled:
        return Decision(False, "All MCP & AI Gateway flags are false: nothing to do; existing resources are untouched.")
    if request.project_number != PROJECT_NUMBER:
        raise ValueError(f"MCP & AI Gateway flags are supported only for project{PROJECT_NUMBER}; "
                         f"this pipeline is project{request.project_number}.")
    if request.environment != ENVIRONMENT:
        return Decision(False, f"MCP & AI Gateway integration runs only in Dev; skipped for '{request.environment}'.")
    problems = []
    if request.delete_requested:
        problems.append("deleteAllServicesForProject/deleteAllForProject conflict with enabled MCP & AI Gateway options")
    if request.add_mcp_to_gateway and not (request.enable_mcp and request.enable_gateway):
        problems.append("addAIFactoryMCP2AIGatewaySKU requires enableAIFactoryMCP=true and enableAIGatewaySKU=true")
    if request.enable_mcp and not (request.enable_container_apps and request.enable_ai_foundry):
        problems.append("enableAIFactoryMCP requires enableContainerApps=true and enableAIFoundry=true")
    if request.enable_gateway and not request.enable_ai_foundry:
        problems.append("enableAIGatewaySKU requires enableAIFoundry=true")
    if request.enable_mcp:
        for name, value in (("aifactoryMcpImage", request.mcp_image), ("aifactoryMcpApiImage", request.api_image)):
            if not IMAGE.fullmatch(value):
                problems.append(f"{name} must be a digest-pinned Azure Container Registry image (<registry>.azurecr.io/<repo>@sha256:<digest>)")
        if not GUID.fullmatch(request.entra_app_id):
            problems.append("aifactoryMcpEntraAppId must be the MCP API app registration client ID (GUID)")
    if request.gateway_resource_id and not GATEWAY_ID.fullmatch(request.gateway_resource_id):
        problems.append("aiGatewaySkuResourceId must be a Microsoft.ApiManagement/service resource ID")
    if request.gateway_subnet_id and not SUBNET_ID.fullmatch(request.gateway_subnet_id):
        problems.append("aiGatewaySkuOutboundSubnetId must be a subnet resource ID")
    for name, value in (("dev_test_prod_sub_id", request.subscription_id), ("tenantId", request.tenant_id)):
        if not GUID.fullmatch(value):
            problems.append(f"{name} must be a GUID")
    if not request.resource_group or not request.location:
        problems.append("the project resource group and admin_location are required")
    if problems:
        raise ValueError("Invalid MCP & AI Gateway configuration: " + "; ".join(problems) + ".")
    return Decision(True, "Validated project001 Dev MCP & AI Gateway request.")


def names(request: IntegrationRequest) -> dict[str, str]:
    group_id = f"/subscriptions/{request.subscription_id}/resourceGroups/{request.resource_group}"
    digest = uuid.uuid5(uuid.NAMESPACE_URL, group_id.lower()).hex[:8]
    gateway_id = request.gateway_resource_id or (
        f"{group_id}/providers/Microsoft.ApiManagement/service/aigw-p{request.project_number}-{request.environment}-{digest}")
    suffix = f"p{request.project_number}-{request.environment}"
    return {
        "group_id": group_id,
        "app_id": f"{group_id}/providers/Microsoft.App/containerApps/aifactory-mcp-{suffix}",
        "identity_id": f"{group_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mi-aifactory-mcp-{suffix}",
        "gateway_id": gateway_id,
        "tool_server": f"aifactory-mcp-{suffix}",
    }


@dataclass
class ProjectTarget:
    account_id: str
    account_name: str
    location: str
    project_name: str
    project_endpoint: str
    project_principal_id: str
    project_client_id: str
    chat: dict
    embedding: str
    search_name: str
    storage_name: str
    insights_name: str
    environment_id: str
    environment_domain: str


@dataclass
class Report:
    mode: str
    actions: list[dict] = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    prerequisites: list[str] = field(default_factory=list)

    def add(self, resource: str, action: str, detail: str = "") -> None:
        self.actions.append({"resource": resource, "action": action, **({"detail": detail} if detail else {})})

    def to_dict(self) -> dict:
        return {"mode": self.mode, "actions": self.actions, "outputs": self.outputs,
                "prerequisites": self.prerequisites, "mutations": self.mode == "apply"}


def _optional(session: ArmPort, resource_id: str, api_version: str) -> dict | None:
    try:
        return session.arm("GET", resource_id, api_version=api_version)
    except AzureError as error:
        if error.status == 404:
            return None
        raise


def _one(items: list[dict], label: str, name: str = "") -> dict:
    candidates = [item for item in items if not name or item["name"].split("/")[-1].lower() == name.lower()]
    if len(candidates) != 1:
        found = ", ".join(sorted(item["name"] for item in candidates)) or "(none)"
        raise ValueError(f"Expected exactly one {label}; found {len(candidates)}: {found}.")
    return candidates[0]


def _system_client_id(session: ArmPort, resource_id: str) -> str:
    identity = session.arm("GET", f"{resource_id}/providers/Microsoft.ManagedIdentity/identities/default",
                           api_version=IDENTITY_API)
    return identity["properties"]["clientId"]


def discover(session: ArmPort, request: IntegrationRequest) -> ProjectTarget:
    """Resolve the project's actual Foundry, data and Container Apps resources (GET only)."""
    group_id = names(request)["group_id"]
    resources = session.pages(f"{ARM}{group_id}/resources?api-version={RESOURCES_API}")

    def of_type(kind: str) -> list[dict]:
        return sorted((item for item in resources if item["type"].lower() == kind.lower()), key=lambda item: item["name"])

    account = _one([item for item in of_type("Microsoft.CognitiveServices/accounts") if item.get("kind") == "AIServices"],
                   "project Foundry (AIServices) account")
    project = _one(session.pages(f"{ARM}{account['id']}/projects?api-version={COGNITIVE_API}"), "Foundry project")
    project = session.arm("GET", project["id"], api_version=COGNITIVE_API)
    principal = (project.get("identity") or {}).get("principalId", "")
    if not GUID.fullmatch(principal or ""):
        raise ValueError("The Foundry project has no system-assigned managed identity.")
    deployments = [item for item in session.pages(f"{ARM}{account['id']}/deployments?api-version={COGNITIVE_API}")
                   if item.get("properties", {}).get("provisioningState") == "Succeeded"]
    chats = sorted((item for item in deployments if item["properties"]["model"].get("format") == "OpenAI"
                    and not item["properties"]["model"]["name"].startswith("text-embedding")),
                   key=lambda item: item["name"])
    if not chats:
        raise ValueError("enableAIFactoryMCP requires a succeeded chat model deployment in the project Foundry account.")
    embeddings = sorted(item["name"].split("/")[-1] for item in deployments
                        if item["properties"]["model"]["name"].startswith("text-embedding"))
    searches = of_type("Microsoft.Search/searchServices")
    if not searches:
        raise ValueError("enableAIFactoryMCP requires the project AI Search service (enableAISearch=true).")
    storages = of_type("Microsoft.Storage/storageAccounts")
    data = [item for item in storages if "2001" in item["name"]] or storages
    if not data:
        raise ValueError("enableAIFactoryMCP requires the project data storage account.")
    environments = of_type("Microsoft.App/managedEnvironments")
    environment = _one(environments, "project Container Apps environment (set aifactoryMcpContainerAppsEnvironment)",
                       request.container_apps_environment)
    environment = session.arm("GET", environment["id"], api_version=APP_API)
    if not (environment.get("properties", {}).get("vnetConfiguration") or {}).get("internal"):
        raise ValueError("The MCP stays private: the selected Container Apps environment must be internal (VNet-integrated).")
    insights = of_type("Microsoft.Insights/components")
    chat = chats[0]
    return ProjectTarget(
        account_id=account["id"], account_name=account["name"], location=account["location"],
        project_name=project["name"].split("/")[-1],
        project_endpoint=project["properties"]["endpoints"]["AI Foundry API"].rstrip("/"),
        project_principal_id=principal.lower(), project_client_id=_system_client_id(session, project["id"]).lower(),
        chat={"name": chat["name"].split("/")[-1], "model": chat["properties"]["model"]["name"],
              "version": chat["properties"]["model"].get("version", ""),
              "sku": (chat.get("sku") or {}).get("name", "DataZoneStandard"),
              "capacity": int((chat.get("sku") or {}).get("capacity") or 10)},
        embedding=embeddings[0] if embeddings else "", search_name=searches[0]["name"],
        storage_name=data[0]["name"], insights_name=insights[0]["name"] if insights else "",
        environment_id=environment["id"], environment_domain=environment["properties"]["defaultDomain"],
    )


def _owned(resource: dict | None) -> bool:
    return bool(resource) and (resource.get("tags") or {}).get(OWNER_TAG) == OWNER_VALUE


def _wait(session: ArmPort, resource_id: str, api_version: str, sleep: Callable[[float], None],
          timeout_seconds: float = 3600, interval: float = 20) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        current = session.arm("GET", resource_id, api_version=api_version)
        state = current.get("properties", {}).get("provisioningState", "Succeeded")
        if state == "Succeeded":
            return current
        if state in {"Failed", "Canceled"} or time.monotonic() >= deadline:
            raise RuntimeError(f"{resource_id} did not provision (state {state}); nothing was deleted.")
        sleep(interval)


def _ensure_role(session: ArmPort, scope: str, principal_id: str, role: str, report: Report, apply: bool) -> None:
    existing = session.pages(f"{ARM}{scope}/providers/Microsoft.Authorization/roleAssignments"
                             f"?api-version={ROLE_API}&$filter=principalId%20eq%20'{principal_id}'")
    if any(item["properties"]["roleDefinitionId"].lower().endswith(role) for item in existing):
        report.add(f"role {role} for {principal_id} on {scope}", "unchanged")
        return
    if not apply:
        report.add(f"role {role} for {principal_id} on {scope}", "create")
        return
    subscription = scope.split("/")[2]
    name = uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}|{principal_id}|{role}".lower())
    session.arm("PUT", f"{scope}/providers/Microsoft.Authorization/roleAssignments/{name}", {
        "properties": {
            "roleDefinitionId": f"/subscriptions/{subscription}/providers/Microsoft.Authorization/roleDefinitions/{role}",
            "principalId": principal_id, "principalType": "ServicePrincipal",
        }}, api_version=ROLE_API)
    report.add(f"role {role} for {principal_id} on {scope}", "created")


class McpGatewayIntegration:
    """Dependency-injected orchestration: plan (GET only) or apply (owned writes only)."""

    def __init__(self, session: ArmPort, *, sleep: Callable[[float], None] = time.sleep,
                 token: Callable[[], str] = lambda: secrets.token_urlsafe(48)):
        self.session = session
        self.sleep = sleep
        self.token = token

    def run(self, request: IntegrationRequest, *, apply: bool) -> dict:
        decision = decide(request)
        report = Report("apply" if apply else "plan")
        if not decision.act:
            report.add("mcp-ai-gateway", "skipped", decision.reason)
            report.mode = "skipped"
            return report.to_dict()
        resource_names = names(request)
        target = discover(self.session, request)
        gateway = self._gateway(request, target, resource_names, report, apply) if request.enable_gateway else None
        if request.enable_mcp:
            self._mcp(request, target, resource_names, gateway, report, apply)
        if request.add_mcp_to_gateway:
            self._register(request, target, resource_names, gateway, report, apply)
        return report.to_dict()

    def _gateway(self, request, target, resource_names, report, apply) -> dict | None:
        gateway_id = resource_names["gateway_id"]
        gateway = _optional(self.session, gateway_id, GATEWAY_API)
        adopted = bool(request.gateway_resource_id)
        if gateway is None:
            if adopted:
                raise ValueError("aiGatewaySkuResourceId does not exist; create it or clear the variable to let the pipeline create one.")
            body = {"location": request.location, "sku": {"name": "AIGateway", "capacity": 1},
                    "identity": {"type": "SystemAssigned"}, "tags": dict(OWNER_TAGS), "properties": {}}
            if request.gateway_subnet_id:
                body["properties"] = {"virtualNetworkType": "External",
                                      "virtualNetworkConfiguration": {"subnetResourceId": request.gateway_subnet_id}}
            if not apply:
                report.add(gateway_id, "create", "SKU AIGateway, system-assigned identity")
                report.outputs["gateway_id"] = gateway_id
                return None
            self.session.request("PUT", f"{ARM}{gateway_id}?api-version={GATEWAY_API}", body,
                                 headers={"If-None-Match": "*"})
            gateway = _wait(self.session, gateway_id, GATEWAY_API, self.sleep)
            report.add(gateway_id, "created")
        else:
            if (gateway.get("sku") or {}).get("name") != "AIGateway":
                raise ValueError(f"{gateway_id} is not an AI Gateway SKU service; refusing to use it.")
            if not adopted and not _owned(gateway):
                raise ValueError(f"{gateway_id} exists but is not owned by this integration; refusing to modify it.")
            report.add(gateway_id, "adopted" if adopted else "unchanged")
            configured = (gateway.get("properties", {}).get("virtualNetworkConfiguration") or {}).get("subnetResourceId")
            if request.gateway_subnet_id and not configured:
                if adopted:
                    raise ValueError("The adopted AI Gateway has no outbound VNet integration; configure it on that gateway.")
                patch = {"properties": {"virtualNetworkType": "External",
                                        "virtualNetworkConfiguration": {"subnetResourceId": request.gateway_subnet_id}}}
                if apply:
                    self.session.arm("PATCH", gateway_id, patch, api_version=GATEWAY_API)
                    gateway = _wait(self.session, gateway_id, GATEWAY_API, self.sleep)
                report.add(f"{gateway_id} outbound subnet", "updated" if apply else "update")
        principal = (gateway.get("identity") or {}).get("principalId", "")
        if not GUID.fullmatch(principal or ""):
            raise ValueError("The AI Gateway has no system-assigned managed identity.")
        _ensure_role(self.session, target.account_id, principal.lower(), AZURE_AI_USER_ROLE, report, apply)
        self._model_provider(target, gateway_id, report, apply)
        report.outputs.update(gateway_id=gateway_id, gateway_url=gateway.get("properties", {}).get("gatewayUrl", ""))
        return gateway

    def _model_provider(self, target, gateway_id, report, apply) -> None:
        provider_id = f"{gateway_id}/workspaces/default/modelProviders/{target.account_name}"
        desired = {"properties": {
            "displayName": f"{target.account_name} ({target.location})", "kind": "Foundry",
            "foundry": {"authentication": {"kind": "ManagedIdentity", "managedIdentity": {"resource": COGNITIVE_SCOPE}},
                        "endpoint": f"https://{target.account_name}.cognitiveservices.azure.com/",
                        "resourceIds": [target.account_id]}}}
        current = _optional(self.session, provider_id, GATEWAY_API)
        if current is not None:
            resource_ids = [value.lower() for value in current.get("properties", {}).get("foundry", {}).get("resourceIds", [])]
            if resource_ids != [target.account_id.lower()]:
                raise ValueError(f"{provider_id} points at another Foundry resource; refusing to overwrite it.")
            if current["properties"].get("foundry", {}).get("authentication") == desired["properties"]["foundry"]["authentication"]:
                report.add(provider_id, "unchanged")
                return
        if apply:
            self.session.arm("PUT", provider_id, desired, api_version=GATEWAY_API)
        report.add(provider_id, ("updated" if current else "created") if apply else ("update" if current else "create"))

    def _gateway_identity(self, gateway: dict | None) -> tuple[str, str] | None:
        if not gateway:
            return None
        principal = gateway["identity"]["principalId"].lower()
        return principal, _system_client_id(self.session, gateway["id"]).lower()

    def _mcp(self, request, target, resource_names, gateway, report, apply) -> None:
        identity_id, app_id = resource_names["identity_id"], resource_names["app_id"]
        identity = _optional(self.session, identity_id, IDENTITY_API)
        app = _optional(self.session, app_id, APP_API)
        for resource_id, resource in ((identity_id, identity), (app_id, app)):
            if resource is not None and not _owned(resource):
                raise ValueError(f"{resource_id} exists but is not owned by this integration; refusing to modify it.")
        if not apply:
            report.add(identity_id, "unchanged" if identity else "create")
            report.add(app_id, "update" if app else "create", "private MCP + Factory API containers")
            report.outputs["mcp_url"] = f"https://{app_id.rsplit('/', 1)[1]}.{target.environment_domain}/mcp"
            return
        if identity is None:
            identity = self.session.arm("PUT", identity_id, {"location": target.location, "tags": dict(OWNER_TAGS)},
                                        api_version=IDENTITY_API)
            report.add(identity_id, "created")
        else:
            report.add(identity_id, "unchanged")
        principal, client = identity["properties"]["principalId"].lower(), identity["properties"]["clientId"].lower()
        registries = self._registries(request)
        for registry_id in registries.values():
            _ensure_role(self.session, registry_id, principal, ACR_PULL_ROLE, report, True)
        key = self._api_key(app_id) if app else self.token()
        body = mcp_app_body(request, target, resource_names, identity_id, client, registries,
                            self._gateway_identity(gateway) if request.add_mcp_to_gateway else None, key)
        self.session.arm("PUT", app_id, body, api_version=APP_API)
        current = _wait(self.session, app_id, APP_API, self.sleep)
        fqdn = current["properties"]["configuration"]["ingress"]["fqdn"]
        report.add(app_id, "updated" if app else "created")
        report.outputs.update(mcp_app_id=app_id, mcp_url=f"https://{fqdn}/mcp", mcp_identity_client_id=client)

    def _registries(self, request) -> dict[str, str]:
        servers = {IMAGE.fullmatch(image)["server"] for image in (request.mcp_image, request.api_image)}
        registries = self.session.pages(f"{ARM}/subscriptions/{request.subscription_id}/providers/"
                                        f"Microsoft.ContainerRegistry/registries?api-version={REGISTRY_API}")
        found = {item["properties"]["loginServer"].lower(): item["id"] for item in registries}
        missing = sorted(server for server in servers if server not in found)
        if missing:
            raise ValueError("MCP images must come from a registry in the project subscription; not found: " + ", ".join(missing))
        return {server: found[server] for server in sorted(servers)}

    def _api_key(self, app_id: str) -> str:
        values = self.session.arm("POST", f"{app_id}/listSecrets", api_version=APP_API).get("value", [])
        existing = next((item.get("value") for item in values if item.get("name") == API_KEY_SECRET), "")
        return existing or self.token()

    def _register(self, request, target, resource_names, gateway, report, apply) -> None:
        gateway_id = resource_names["gateway_id"]
        server_id = f"{gateway_id}/workspaces/default/toolServers/{resource_names['tool_server']}"
        if not apply and gateway is None:
            report.add(server_id, "create", "after the gateway and MCP exist")
            return
        if not (gateway.get("properties", {}).get("virtualNetworkConfiguration") or {}).get("subnetResourceId"):
            raise ValueError("Registering the private MCP requires AI Gateway outbound VNet integration; "
                             "set aiGatewaySkuOutboundSubnetId (delegated to Microsoft.Web/serverFarms, /27 or larger).")
        url = report.outputs.get("mcp_url") or ""
        desired = tool_server_body(request.entra_app_id, url)
        current = _optional(self.session, server_id, GATEWAY_API)
        if current is not None and MARKER not in current.get("properties", {}).get("description", ""):
            raise ValueError(f"{server_id} exists but is not owned by this integration; refusing to modify it.")
        principal = gateway["identity"]["principalId"].lower()
        report.prerequisites.append(
            f"One-time Entra admin consent (the pipeline never writes Microsoft Graph): assign app role {REQUIRED_ROLE} "
            f"of the MCP app registration {request.entra_app_id} to the AI Gateway managed identity {principal}, then "
            f"grant callers the 'AI Gateway Tools User' role on the tool server.")
        if current is not None and _same_server(current, desired):
            report.add(server_id, "unchanged")
        else:
            if apply:
                self.session.arm("PUT", server_id, desired, api_version=GATEWAY_API)
            report.add(server_id, ("updated" if current else "created") if apply else ("update" if current else "create"))
        report.outputs["tool_server_url"] = (
            f"{gateway.get('properties', {}).get('gatewayUrl', '').rstrip('/')}/default/toolservers/{resource_names['tool_server']}/mcp")


def tool_server_body(entra_app_id: str, mcp_url: str) -> dict:
    return {"properties": {
        "type": "mcp", "accessState": "active", "blocked": [],
        "allowList": [f"{NAMESPACE}_{tool}" for tool in READ_ONLY_TOOLS],
        "displayName": "Enterprise Scale AI Factory (project001 Dev)",
        "description": "Read-only Enterprise Scale AI Factory MCP: API health, capabilities and skill discovery. "
                       f"Factory provisioning and deletion are disabled. {MARKER}",
        "endpoints": [{"kind": "mcp", "namespace": NAMESPACE, "required": True,
                       "credentials": {"type": "managedIdentity", "managedIdentity": {"resource": entra_app_id}},
                       "mcp": {"transport": "streamableHttp", "url": mcp_url}}],
    }}


def _same_server(current: dict, desired: dict) -> bool:
    props, wanted = current.get("properties", {}), desired["properties"]
    endpoint = (props.get("endpoints") or [{}])[0]
    return (props.get("allowList") == wanted["allowList"] and props.get("accessState") == "active"
            and endpoint.get("credentials") == wanted["endpoints"][0]["credentials"]
            and endpoint.get("mcp") == wanted["endpoints"][0]["mcp"] and endpoint.get("namespace") == NAMESPACE)


def runtime_settings(request: IntegrationRequest, target: ProjectTarget, identity_client_id: str,
                     callers: list[tuple[str, str]]) -> dict:
    """The MCP image's read-only agent Settings document (no secrets)."""
    return {
        "location": target.location,
        "scopes": {SCOPE_KEY: {"tenant_id": request.tenant_id, "subscription_id": request.subscription_id,
                               "resource_group": request.resource_group, "factory": request.factory_key,
                               "project": PROJECT_NUMBER, "environment": ENVIRONMENT}},
        "azure": {
            "foundry_account": target.account_name, "foundry_project": target.project_name,
            "project_endpoint": target.project_endpoint,
            "openai_endpoint": f"https://{target.account_name}.openai.azure.com/openai/v1",
            "model_deployment": target.chat["name"], "model_name": target.chat["model"],
            "model_version": target.chat["version"], "model_sku": target.chat["sku"],
            "model_capacity": target.chat["capacity"], "embedding_deployment": target.embedding,
            "search_endpoint": f"https://{target.search_name}.search.windows.net",
            "search_index": "enterprise-scale-ai-factory-v1",
            "storage_endpoint": f"https://{target.storage_name}.blob.core.windows.net",
            "storage_container": "aifactory-agent", "credential": "managed_identity",
            "managed_identity_client_id": identity_client_id,
            **({"application_insights_name": target.insights_name} if target.insights_name else {}),
        },
        "knowledge": {"top_k": 3, "repository_root": "/opt/repository",
                      "source_base_url": "https://github.com/jostrm/azure-enterprise-scale-ml/blob/main",
                      "includes": list(KNOWLEDGE_INCLUDES), "excludes": list(KNOWLEDGE_EXCLUDES)},
        "factory": {"api_url": "http://127.0.0.1:8765", "folder": "/state/azurefactory", "writes_enabled": False,
                    "allowed_write_environments": [ENVIRONMENT]},
        "actions": {"enabled_skills": []}, "costs": {}, "workloads": {},
        "auth": {"client_id": request.entra_app_id, "audience": request.entra_app_id,
                 "grants": [{"object_id": object_id, "scopes": [SCOPE_KEY], "permissions": ["factory.read"]}
                            for object_id, _ in callers]},
    }


def application_auth(request: IntegrationRequest, callers: list[tuple[str, str]]) -> dict:
    return {"audience": request.entra_app_id, "required_role": REQUIRED_ROLE,
            "identities": [{"object_id": object_id, "client_id": client_id, "scope_keys": [SCOPE_KEY],
                            "allowed_tools": list(READ_ONLY_TOOLS)} for object_id, client_id in callers]}


def mcp_app_body(request: IntegrationRequest, target: ProjectTarget, resource_names: dict, identity_id: str,
                 identity_client_id: str, registries: dict[str, str], gateway_identity: tuple[str, str] | None,
                 api_key: str) -> dict:
    callers = [(target.project_principal_id, target.project_client_id)]
    if gateway_identity:
        callers.append(gateway_identity)
    app_name = resource_names["app_id"].rsplit("/", 1)[1]
    secret = {"name": "AIFACTORY_API_KEY", "secretRef": API_KEY_SECRET}
    resources = {"cpu": 0.5, "memory": "1Gi"}
    probe = {"httpGet": {"path": "/health/live", "port": 8080, "scheme": "HTTP"}, "periodSeconds": 10, "timeoutSeconds": 3}
    return {
        "location": target.location, "tags": dict(OWNER_TAGS),
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {identity_id: {}}},
        "properties": {
            "environmentId": target.environment_id,
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {"external": True, "targetPort": 8080, "transport": "auto", "allowInsecure": False},
                "registries": [{"server": server, "identity": identity_id} for server in registries],
                "secrets": [{"name": API_KEY_SECRET, "value": api_key}],
            },
            "template": {
                "containers": [
                    {"name": "mcp", "image": request.mcp_image, "resources": resources, "env": [
                        {"name": "AIFACTORY_PILOT_CONFIG_JSON",
                         "value": json.dumps(runtime_settings(request, target, identity_client_id, callers), separators=(",", ":"))},
                        {"name": "AIFACTORY_APPLICATION_AUTH_JSON",
                         "value": json.dumps(application_auth(request, callers), separators=(",", ":"))},
                        {"name": "AIFACTORY_MCP_SCOPE", "value": SCOPE_KEY},
                        {"name": "AIFACTORY_MCP_RESOURCE_URL", "value": f"https://{app_name}.{target.environment_domain}/mcp"},
                        {"name": "AZURE_CLIENT_ID", "value": identity_client_id},
                        secret, {"name": "PYTHONUNBUFFERED", "value": "1"},
                    ], "probes": [
                        {**probe, "type": "Liveness", "initialDelaySeconds": 10, "failureThreshold": 3},
                        {**probe, "type": "Readiness", "initialDelaySeconds": 5, "failureThreshold": 6,
                         "httpGet": {**probe["httpGet"], "path": "/health/ready"}},
                        {**probe, "type": "Startup", "initialDelaySeconds": 2, "failureThreshold": 30},
                    ]},
                    {"name": "factory-api", "image": request.api_image, "resources": resources,
                     "env": [secret, {"name": "PYTHONUNBUFFERED", "value": "1"}]},
                ],
                "scale": {"minReplicas": 1, "maxReplicas": 1},
            },
        },
    }
