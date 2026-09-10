#!/usr/bin/env python3
"""Apply new-scale-set bootstrap answers to AI Factory configuration files."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


AIF_SIMPLE_MODE_CONTRACT_VERSION = 2
SIMPLE_MODE_PRESET_NAME = "private-ai-foundation-v2"
# These trees must be published together; the launcher must not copy dirty PURPLE
# files into a consumer to make an unpublished feature appear deployable.
SIMPLE_MODE_REQUIRED_SOURCE_PATHS = ("bootstrap", "environment_setup/aifactory")
SIMPLE_MODE_RESOURCE_CATALOG = {
    "hub": [
        {"id": "virtual-network", "label": "Private virtual network", "description": "Integrated Dev /20 with dedicated access subnets.", "required": True, "default_selected": True, "dependencies": []},
        {"id": "application-gateway", "label": "Application Gateway WAF_v2", "description": "Billable, autoscale 1-2 instances. Private HTTPS frontend, WAF Prevention, TLS 1.2+, no public IP. Requires hostname, private HTTPS backend and existing Key Vault certificate.", "required": True, "default_selected": True, "dependencies": ["virtual-network", "private-dns"]},
        {"id": "vpn-gateway", "label": "VPN Gateway VpnGw1AZ", "description": "Billable Entra-authenticated P2S; Standard public IP for VPN transport only. Manual client connection.", "required": True, "default_selected": True, "dependencies": ["virtual-network"]},
        {"id": "bastion", "label": "Bastion Developer", "description": "No admin VM; region must support Developer, no paid fallback.", "required": True, "default_selected": True, "dependencies": ["virtual-network"]},
        {"id": "private-dns", "label": "Private DNS and DNS Private Resolver", "description": "Zones, links, billable inbound resolver, scoped DNS policy and access IP-group inventory.", "required": True, "default_selected": True, "dependencies": ["virtual-network"]},
    ],
    "common": [
        {"id": "common-storage", "label": "Common Storage Standard_LRS", "description": "Shared foundation storage and private endpoints.", "required": True, "default_selected": True, "dependencies": ["virtual-network"]},
        {"id": "common-key-vault", "label": "Common and seeding Key Vaults", "description": "Standard vaults; no project service-principal password required.", "required": True, "default_selected": True, "dependencies": ["private-dns"]},
        {"id": "common-registry", "label": "Common Container Registry Premium", "description": "Canonical shared registry; Premium is required for Private Link.", "required": True, "default_selected": True, "dependencies": ["virtual-network"]},
        {"id": "log-analytics", "label": "Common Log Analytics PerGB2018", "description": "Shared diagnostic workspace, also required by optional project Application Insights. AMPLS is not enabled.", "required": True, "default_selected": True, "dependencies": []},
        {"id": "deployment-identity", "label": "Deployment managed identity and OIDC", "description": "Federated GitHub deployment identity, Entra team and role assignments.", "required": True, "default_selected": True, "dependencies": []},
    ],
    "project": [
        {"id": "storage", "label": "Project Storage Standard_LRS", "description": "Required project storage accounts and private endpoints.", "required": True, "default_selected": True, "dependencies": ["private-dns"]},
        {"id": "key-vault", "label": "Project Key Vault Standard", "description": "Required project Key Vault and private endpoint.", "required": True, "default_selected": True, "dependencies": ["private-dns"]},
        {"id": "managed-identities", "label": "Project managed identities", "description": "Required project/platform identities and baseline RBAC.", "required": True, "default_selected": True, "dependencies": []},
        {"id": "foundry", "label": "Microsoft Foundry S0", "description": "Required private Foundry account and default project; model deployments remain optional.", "required": True, "default_selected": True, "dependencies": ["storage", "key-vault", "managed-identities"]},
        {"id": "foundry-capability-host", "label": "Foundry capability host", "description": "Required standard private-agent data plane; binds thread, vector-store, and file-storage connections.", "required": True, "default_selected": True, "dependencies": ["foundry", "storage", "ai-search", "cosmos-db"]},
        {"id": "ai-search", "label": "AI Search Standard", "description": "Required capability-host vector-store connection with private networking.", "required": True, "default_selected": True, "dependencies": ["managed-identities", "private-dns"]},
        {"id": "cosmos-db", "label": "Azure Cosmos DB", "description": "Required capability-host thread and agent-history store with a private endpoint.", "required": True, "default_selected": True, "dependencies": ["managed-identities", "private-dns"]},
        {"id": "application-insights", "label": "Application Insights", "description": "Optional workspace-based project telemetry; not private-only without AMPLS.", "required": False, "default_selected": True, "dependencies": ["log-analytics"]},
    ],
}
SIMPLE_MODE_DISABLED = (
    "enableAzureMachineLearning", "addAzureMachineLearning", "enableDatabricks",
    "enableAIFoundryHub", "addAIFoundryHub", "enableAksForAzureML", "enableAKS",
    "cleanFoundryCaphost", "enableDatafactory",
    "enableDatafactoryCommon", "enableAIServices", "enableAzureOpenAI",
    "enableAzureAIVision", "enableAzureSpeech", "enableAIDocIntelligence",
    "enableBing", "enableBingCustomSearch", "enableContentSafety",
    "enablePostgreSQL", "enableRedisCache", "enableSQLDatabase", "enableElasticsearch",
    "enableFunction", "enableWebApp", "enableContainerApps", "enableLogicApps",
    "enableEventHubs", "enableBotService", "enableAppInsightsDashboard",
    "enableDefenderforAISubLevel", "enableDefenderforAIResourceLevel",
    "serviceSettingDeployProjectVM", "enableAdminVM", "addBastionHost",
    "useSelfHostedBuildAgent", "enableDeleteForDisabledResources",
    "deleteAllServicesForProject", "deleteKeyvaultAlso", "deleteAllForProject",
    "deployModel_gpt_X", "deployModel_gpt_4", "deployModel_gpt_4o",
    "deployModel_gpt_54_mini", "deployModel_text_embedding_ada_002",
    "deployModel_text_embedding_3_large", "deployModel_text_embedding_3_small",
    "ENABLE_APIM", "ENABLE_KONG",
)


def simple_mode_enabled(state: dict[str, Any]) -> bool:
    return str(state.get("simple_mode", "false")).lower() == "true"


def simple_mode_project_resources(selection: str | list[str] | None = None) -> list[str]:
    catalog = SIMPLE_MODE_RESOURCE_CATALOG["project"]
    if selection is None:
        selection = [item["id"] for item in catalog if item["default_selected"]]
    elif isinstance(selection, str):
        try:
            selection = json.loads(selection)
        except ValueError as error:
            raise ValueError("Project resources must be a JSON array of resource IDs") from error
    if not isinstance(selection, list) or any(not isinstance(item, str) for item in selection):
        raise ValueError("Project resources must be a JSON array of resource IDs")
    allowed = {item["id"] for item in catalog}
    if set(selection) - allowed:
        raise ValueError("Project resources contain unsupported IDs")
    return [item["id"] for item in catalog if item["required"] or item["id"] in selection]


def simple_mode_gateway_inputs(hostname: str, backend_fqdn: str, certificate_secret_id: str) -> dict[str, str]:
    missing = [name for name, value in (
        ("AIF_APP_GATEWAY_HOSTNAME", hostname), ("AIF_APP_GATEWAY_BACKEND_FQDN", backend_fqdn),
        ("AIF_APP_GATEWAY_CERT_SECRET_ID", certificate_secret_id)) if not value]
    if missing:
        raise ValueError("Private HTTPS Application Gateway requires: " + ", ".join(missing))
    dns = re.compile(r"(?=^.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")
    hostname, backend_fqdn = hostname.lower(), backend_fqdn.lower()
    if not dns.fullmatch(hostname) or hostname.count(".") < 2 or ".privatelink." in hostname:
        raise ValueError("Application Gateway hostname must be a custom FQDN with a host and domain")
    if (not dns.fullmatch(backend_fqdn) or hostname == backend_fqdn
            or backend_fqdn.endswith("." + hostname)):
        raise ValueError("Application Gateway backend must be an HTTPS backend FQDN, not an IP or URL")
    parsed = urlparse(certificate_secret_id)
    if (parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9-]{3,24}\.vault\.azure\.net", parsed.netloc)
            or not re.fullmatch(r"/secrets/[A-Za-z0-9-]{1,127}", parsed.path)
            or parsed.query or parsed.fragment):
        raise ValueError("Certificate must be a versionless https://<vault>.vault.azure.net/secrets/<name> URI")
    if hostname == parsed.netloc:
        raise ValueError("Gateway frontend hostname cannot replace the certificate vault's DNS name")
    return {"hostname": hostname, "backend_fqdn": backend_fqdn, "certificate_secret_id": certificate_secret_id,
            "certificate_vault_name": parsed.netloc.split(".")[0], "certificate_name": parsed.path.split("/")[-1],
            "dns_zone": hostname, "dns_record": "@"}


def validate_simple_gateway_certificate(gateway: dict[str, str], certificate: dict[str, Any]) -> None:
    """Validate metadata only; private certificate/secret values are never requested."""
    policy = certificate.get("policy") or {}
    attributes = certificate.get("attributes") or {}
    names = (policy.get("x509CertificateProperties") or {}).get("subjectAlternativeNames", {}).get("dnsNames") or []
    hostname = gateway["hostname"]
    matches = any(name.lower() == hostname or (
        name.startswith("*.") and hostname.split(".", 1)[1] == name[2:].lower()) for name in names)
    def timestamp(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    now = datetime.now(timezone.utc).timestamp()
    try:
        valid = (attributes.get("enabled") is True and timestamp(attributes["expires"]) > now
                 and (not attributes.get("notBefore") or timestamp(attributes["notBefore"]) <= now))
    except (KeyError, ValueError, TypeError):
        valid = False
    sid = str(certificate.get("sid", ""))
    if (not valid or not matches or not sid.startswith(gateway["certificate_secret_id"] + "/")
            or (policy.get("keyProperties") or {}).get("exportable") is not True
            or (policy.get("secretProperties") or {}).get("contentType") != "application/x-pkcs12"):
        raise ValueError("Gateway certificate must be enabled, valid, exportable PFX and cover the frontend hostname in its DNS SAN metadata")


def simple_mode_gateway_healthy(health: dict[str, Any], backend_fqdn: str) -> bool:
    servers = [server for pool in health.get("backendAddressPools", [])
               for settings in pool.get("backendHttpSettingsCollection", [])
               for server in settings.get("servers", [])]
    private_ranges = [ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    for server in servers:
        if server.get("health") != "Healthy":
            return False
        address = str(server.get("address", ""))
        try:
            if not any(ipaddress.ip_address(address) in network for network in private_ranges):
                return False
        except ValueError:
            if address.rstrip(".").lower() != backend_fqdn.rstrip(".").lower():
                return False
    return bool(servers)


def simple_mode_values(cost_center: str = "123456", project_resources: str | list[str] | None = None,
                       repository_visibility: str = "private") -> dict[str, Any]:
    """Canonical secretless Dev foundation without model deployments."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cost_center):
        raise ValueError("Cost center must be 1-64 letters, digits, underscores or hyphens")
    if repository_visibility not in {"public", "private"}:
        raise ValueError("GitHub repository visibility must be public or private")
    selected = simple_mode_project_resources(project_resources)
    return {
        **{key: "false" for key in SIMPLE_MODE_DISABLED},
        "scaling-mode": "own-subscriptions",
        "centralDnsZoneByPolicyInHub": False,
        "enableAIFactoryHub": True,
        "enablePublicGenAIAccess": "false",
        "allowPublicAccessWhenBehindVnet": "false",
        "enablePublicAccessWithPerimeter": "false",
        "disableLocalAuth": "true",
        "enableAIFoundry": "true",
        "enableAFoundryCaphost": "true",
        "foundryDeploymentType": "2",
        "enableAIFactoryCreatedDefaultProjectForAIFv2": "true",
        "disableAgentNetworkInjection": "false",
        "enableAISearch": "true",
        "enableAISearchSharedPrivateLink": "true",
        "enableCosmosDB": "true",
        "enableApplicationInsights": str("application-insights" in selected).lower(),
        "updateAIFoundry": "false",
        "addAIFoundry": "false",
        "addAISearch": "false",
        "enableAMPLS": "false",
        "cmk": "false",
        "useCommonACR": "true",
        "useCommonACR_override": "true",
        "acr_SKU": "Premium",
        "acr_adminUserEnabled": "false",
        "skuStorageAccountDev": "Standard_LRS",
        "admin_aiSearchTier": "standard",
        "skuAISearchDev": "standard",
        "admin_semanticSearchTier": "free",
        "skuAIServicesDev": "S0",
        "skuOpenAIDev": "S0",
        "project_number_000": "001",
        "tag_costceter_common": cost_center,
        "tag_costcenter": cost_center,
        "common_vnet_cidr": "172.16.XX.0/20",
        "common_subnet_cidr": "172.16.XX.0/26",
        "common_subnet_scoring_cidr": "172.16.XX.64/26",
        "common_pbi_subnet_cidr": "172.16.XX.128/26",
        "common_bastion_subnet_cidr": "172.16.XX.192/26",
        "dev_cidr_range": "0",
        "test_cidr_range": "16",
        "prod_cidr_range": "32",
        "network_env_dev": "dev",
        "network_env_stage": "test",
        "network_env_prod": "prod",
        "GITHUB_NEW_REPO_VISIBILITY": repository_visibility,
    }


def simple_mode_manifest() -> dict[str, Any]:
    """Read-only UI/CLI preview; no credentials, cloud discovery or mutations."""
    return {
        "contractVersion": AIF_SIMPLE_MODE_CONTRACT_VERSION,
        "preset": SIMPLE_MODE_PRESET_NAME,
        "requiredSourcePaths": list(SIMPLE_MODE_REQUIRED_SOURCE_PATHS),
        "sourcePinEnvironment": "AIF_SUBMODULE_REF",
        "sourcePinFormat": "40-character lowercase Git commit SHA",
        "resourceCatalog": SIMPLE_MODE_RESOURCE_CATALOG,
        "appGatewayInputs": {
            "app_gateway_backend_fqdn": "AIF_APP_GATEWAY_BACKEND_FQDN",
            "app_gateway_hostname": "AIF_APP_GATEWAY_HOSTNAME",
            "app_gateway_certificate_secret_id": "AIF_APP_GATEWAY_CERT_SECRET_ID",
        },
        "repositoryVisibility": {"environment": "GITHUB_REPOSITORY_VISIBILITY", "default": "private", "allowed": ["private", "public"]},
        "projectResourcesEnvironment": "AIF_SIMPLE_PROJECT_RESOURCES_JSON",
        "requiredInputs": [
            {"environment": "AIF_APP_GATEWAY_HOSTNAME", "name": "app_gateway_hostname", "description": "Custom HTTPS frontend FQDN covered by the certificate."},
            {"environment": "AIF_APP_GATEWAY_BACKEND_FQDN", "name": "app_gateway_backend_fqdn", "description": "Private RFC1918 HTTPS backend reachable from the new VNet, trusted certificate and GET / returning 200-399."},
            {"environment": "AIF_APP_GATEWAY_CERT_SECRET_ID", "name": "app_gateway_certificate_secret_id", "description": "Existing versionless Key Vault certificate-secret URI; exportable PFX, valid SAN and RBAC vault in Dev subscription."},
        ],
        "stagePrefix": "AIF_SIMPLE_STAGE=",
        "stages": ["preflight", "repository", "identity", "common", "hub", "project", "completed"],
        "environment": "dev",
        "futureEnvironments": ["stage", "prod"],
        "futureSubscriptionReferences": "Dev placeholders only; configure before future use",
        "limitations": [
            "No model deployments; add models only after quota validation",
            "AMPLS is disabled: canonical Application Insights/Log Analytics networking is not private-only",
            "Azure/GitHub sign-in and region availability must be validated before deployment",
            "Private Application Gateway requires an existing certificate/private HTTPS backend and registered EnableApplicationGatewayNetworkIsolation feature",
            "Public GitHub visibility does not enable public Azure services; generated code and non-secret metadata are public",
        ],
        "configuration": simple_mode_values(),
        "services": {
            "Foundry": "S0 account, default project, and required standard-agent capability host",
            "AI Search": "standard capability-host vector store",
            "Cosmos DB": "capability-host thread and agent-history store",
            "Storage": "Standard_LRS capability-host file storage",
            "Key Vault": "standard",
            "Application Insights": "workspace-based",
            "Log Analytics": "PerGB2018",
            "Common Container Registry": "Premium (private-link requirement)",
        },
        "hub": {
            "mode": "standalone-integrated",
            "applicationGateway": "Required WAF_v2, private frontend 172.16.2.10, HTTPS/TLS 1.2+, WAF Prevention; no public IP",
            "vpnGateway": "VpnGw1AZ (billable), Entra-authenticated P2S",
            "bastion": "Developer; fail if unavailable, no paid fallback",
            "adminVM": False,
            "dns": "private zones, links and DNS Private Resolver inbound endpoint (billable)",
            "policy": "private DNS initiative assigned to the Dev subscription",
            "ipGroup": "Dev VNet and VPN client pool; inventory, not firewall enforcement",
            "vpnClient": "profile artifact only; manual install/import/connect",
        },
        "deploymentIdentityRoles": ["Contributor", "User Access Administrator",
                                    "Key Vault Secrets User"],
        "gatewayIdentityRoles": ["Key Vault Secrets User (certificate vault only)"],
        "policyIdentityRoles": ["Network Contributor (Dev subscription)"],
    }


def simple_mode_manifest_sha256() -> str:
    payload = json.dumps(simple_mode_manifest(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def simple_mode_source_sha256(root: Path | None = None) -> str:
    """Stable cross-platform digest of the same source trees checked at launch."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    files = [path for tree in SIMPLE_MODE_REQUIRED_SOURCE_PATHS
             for path in (root / tree).rglob("*")
             if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"]
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def simple_mode_hub_subnets(cidr: str, existing: list[dict[str, Any]]) -> dict[str, str]:
    """Reserve the access blocks before creation; never move existing subnets."""
    network = ipaddress.ip_network(cidr, strict=True)
    if str(network) != "172.16.0.0/20":
        raise ValueError("Simple Mode contract v2 requires Dev VNet 172.16.0.0/20")
    planned = {"GatewaySubnet": "172.16.1.0/27",
               "snet-dns-private-resolver": "172.16.1.32/28",
               "snet-application-gateway": "172.16.2.0/24"}
    for subnet in existing:
        name = subnet["name"]
        prefixes = subnet.get("addressPrefixes") or [subnet.get("addressPrefix")]
        if name in planned and prefixes != [planned[name]]:
            raise ValueError(f"{name} already has another range; use Advanced Mode or a fresh scale set")
        for prefix in prefixes:
            allocated = ipaddress.ip_network(prefix, strict=True)
            if not allocated.subnet_of(network):
                raise ValueError("Existing subnet is outside the Simple Mode Dev VNet")
            for planned_name, planned_prefix in planned.items():
                if name != planned_name and allocated.overlaps(ipaddress.ip_network(planned_prefix)):
                    raise ValueError(f"{name} overlaps reserved {planned_name}; use a fresh scale set")
    occupied = [ipaddress.ip_network(value) for value in planned.values()]
    occupied.extend(ipaddress.ip_network(prefix) for subnet in existing
                    for prefix in (subnet.get("addressPrefixes") or [subnet.get("addressPrefix")]))
    cursor = max(int(subnet.broadcast_address) for subnet in occupied) + 1
    # subnetCalc_v2 appends largest-first after the highest subnet. Account for
    # alignment, not just the total address budget.
    for prefix in (23, 23, 24, 25, 26, 26, 26, 27):
        size = 1 << (32 - prefix)
        cursor = ((cursor + size - 1) // size) * size + size
    if cursor - 1 > int(network.broadcast_address):
        raise ValueError("Existing subnets leave no room for the full Simple Mode project; use a fresh scale set")
    return planned


def verify_simple_mode_source(expected_root: Path, checkout_root: Path) -> None:
    """Reject an old or divergent checkout before any Azure resources are changed."""
    relative_helper = Path("bootstrap/lib/aifactory_scaleset_config.py")
    helper = checkout_root / relative_helper
    if not helper.is_file() or not re.search(
        rf"^AIF_SIMPLE_MODE_CONTRACT_VERSION = {AIF_SIMPLE_MODE_CONTRACT_VERSION}$",
        helper.read_text(encoding="utf-8-sig"), re.MULTILINE,
    ):
        raise ValueError("Published accelerator lacks Simple Mode contract v2; publish PURPLE first")
    for relative_tree in SIMPLE_MODE_REQUIRED_SOURCE_PATHS:
        for source in (expected_root / relative_tree).rglob("*"):
            if not source.is_file() or "__pycache__" in source.parts or source.suffix == ".pyc":
                continue
            relative = source.relative_to(expected_root)
            target = checkout_root / relative
            if not target.is_file() or source.read_bytes().replace(b"\r\n", b"\n") != target.read_bytes().replace(b"\r\n", b"\n"):
                raise ValueError(f"Published accelerator differs at {relative}; publish required PURPLE source first")


def simple_mode_env_values(values: dict[str, Any]) -> dict[str, Any]:
    """Reuse the authoritative workflow bindings rather than invent casing aliases."""
    source_root = Path(__file__).resolve().parents[2]
    workflow_root = source_root / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions"
    aliases: dict[str, set[str]] = {}
    for name in ("infra-common.yml", "infra-project-phase.yml"):
        for line in (workflow_root / name).read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"^\s{6}(\w+):\s+[\"']?\$\{\{", line)
            if match:
                aliases.setdefault(match[1], set()).update(re.findall(r"vars\.([A-Z][A-Z0-9_]*)", line))
    result = {alias: value for key, value in values.items() for alias in aliases.get(key, ())}
    result.update({
        "SCALING_MODE": values["scaling-mode"],
        "ENABLE_AI_FACTORY_HUB": values["enableAIFactoryHub"],
        "TAG_COSTCETER_COMMON": values["tag_costceter_common"],
        "TAG_COSTCENTER": values["tag_costcenter"],
        "AISEARCH_SEMANTIC_TIER": values["admin_semanticSearchTier"],
        "ADMIN_SEMANTIC_SEARCH_TIER": values["admin_semanticSearchTier"],
        "ENABLE_AMPLS": values["enableAMPLS"],
        "ENABLE_APIM": "false", "ENABLE_KONG": "false",
        "SERVICE_SETTING_DEPLOY_PROJECT_VM": "false",
        "DEV_CIDR_RANGE": values["dev_cidr_range"],
        "STAGE_CIDR_RANGE": values["test_cidr_range"],
        "PROD_CIDR_RANGE": values["prod_cidr_range"],
        "DEV_NETWORK_ENV": "dev", "STAGE_NETWORK_ENV": "test", "PROD_NETWORK_ENV": "prod",
        "GITHUB_NEW_REPO_VISIBILITY": values["GITHUB_NEW_REPO_VISIBILITY"],
    })
    return result


YAML_ASSIGNMENT = re.compile(
    r"^(?P<indent>\s{2})(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?P<spacing>\s*)(?P<rest>.*)$"
)
ENV_ASSIGNMENT = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<spacing>\s*)=(?P<rest>.*)$"
)


def split_comment(value: str) -> tuple[str, str]:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip(), value[index:].rstrip()
    return value.rstrip(), ""


def quote(value: Any) -> str:
    if isinstance(value, bool):
        value = "true" if value else "false"
    return json.dumps(str(value), ensure_ascii=True)


def update_yaml(path: Path, values: dict[str, Any]) -> None:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    found: set[str] = set()
    result: list[str] = []
    for line in lines:
        match = YAML_ASSIGNMENT.match(line)
        if not match or match.group("key") not in values:
            result.append(line)
            continue
        key = match.group("key")
        _, comment = split_comment(match.group("rest"))
        suffix = f" {comment}" if comment else ""
        spacing = match.group("spacing") or " "
        result.append(f"{match.group('indent')}{key}:{spacing}{quote(values[key])}{suffix}")
        found.add(key)

    missing = sorted(set(values) - found)
    if missing:
        result.extend(["", "  # Values added by create-new-aifactory-scaleset"])
        result.extend(f"  {key}: {quote(values[key])}" for key in missing)
    path.write_text("\n".join(result) + "\n", encoding="utf-8")


def update_env(path: Path, values: dict[str, Any]) -> None:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    found: set[str] = set()
    result: list[str] = []
    for line in lines:
        match = ENV_ASSIGNMENT.match(line)
        if not match or match.group("key") not in values:
            result.append(line)
            continue
        key = match.group("key")
        _, comment = split_comment(match.group("rest"))
        suffix = f" {comment}" if comment else ""
        result.append(
            f"{match.group('prefix')}{key}{match.group('spacing')}={quote(values[key])}{suffix}"
        )
        found.add(key)

    missing = sorted(set(values) - found)
    if missing:
        result.extend(["", "# Values added by create-new-aifactory-scaleset"])
        result.extend(f"{key}={quote(values[key])}" for key in missing)
    path.write_text("\n".join(result) + "\n", encoding="utf-8")


def update_json(path: Path, values: dict[str, Any]) -> None:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    dev = document.setdefault("dev", {})
    if not isinstance(dev, dict):
        raise ValueError(f"{path}: dev must be an object")
    for key, value in values.items():
        dev[key] = value
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def merge_yaml_template(template_path: Path, active_path: Path) -> None:
    active_values: dict[str, str] = {}
    active_lines: dict[str, str] = {}
    for line in active_path.read_text(encoding="utf-8-sig").splitlines():
        match = YAML_ASSIGNMENT.match(line)
        if match:
            value, _ = split_comment(match.group("rest"))
            active_values[match.group("key")] = value
            active_lines[match.group("key")] = line

    used: set[str] = set()
    result: list[str] = []
    for line in template_path.read_text(encoding="utf-8-sig").splitlines():
        match = YAML_ASSIGNMENT.match(line)
        if not match or match.group("key") not in active_values:
            result.append(line)
            continue
        key = match.group("key")
        _, comment = split_comment(match.group("rest"))
        suffix = f" {comment}" if comment else ""
        spacing = match.group("spacing") or " "
        result.append(
            f"{match.group('indent')}{key}:{spacing}{active_values[key]}{suffix}"
        )
        used.add(key)

    legacy = [key for key in active_values if key not in used]
    if legacy:
        result.extend(["", "  # Legacy values preserved from the previous variables.yaml"])
        result.extend(active_lines[key] for key in legacy)
    active_path.write_text("\n".join(result) + "\n", encoding="utf-8")


def merge_env_template(template_path: Path, active_path: Path) -> None:
    aliases = {
        "DEV_NETWORK_ENV": ("NETWORK_ENV_DEV",),
        "STAGE_NETWORK_ENV": ("NETWORK_ENV_STAGE",),
        "PROD_NETWORK_ENV": ("NETWORK_ENV_PROD",),
        "DISABLE_CONTRIBUTOR_ACCESS_FORUSERS": (
            "DISABLE_CONTRIBUTOR_ACCESS_FOR_USERS",
        ),
        "DISABLE_RBAC_ADMIN_ON_RG_FORUSERS": (
            "DISABLE_RBAC_ADMIN_ON_RG_FOR_USERS",
        ),
    }
    active_values: dict[str, str] = {}
    for line in active_path.read_text(encoding="utf-8-sig").splitlines():
        match = ENV_ASSIGNMENT.match(line)
        if match:
            value, _ = split_comment(match.group("rest"))
            active_values[match.group("key")] = value

    used: set[str] = set()
    result: list[str] = []
    for line in template_path.read_text(encoding="utf-8-sig").splitlines():
        match = ENV_ASSIGNMENT.match(line)
        if not match:
            result.append(line)
            continue
        key = match.group("key")
        source_key = key if key in active_values else next(
            (alias for alias in aliases.get(key, ()) if alias in active_values),
            None,
        )
        if source_key is None:
            result.append(line)
            continue
        _, comment = split_comment(match.group("rest"))
        suffix = f" {comment}" if comment else ""
        result.append(
            f"{match.group('prefix')}{key}{match.group('spacing')}="
            f"{active_values[source_key]}{suffix}"
        )
        used.add(source_key)

    legacy = [key for key in active_values if key not in used]
    if legacy:
        result.extend(["", "# Legacy values preserved from the previous .env"])
        result.extend(f"{key}={active_values[key]}" for key in legacy)
    active_path.write_text("\n".join(result) + "\n", encoding="utf-8")


def merge_json_template(template_path: Path, active_path: Path) -> None:
    template = json.loads(template_path.read_text(encoding="utf-8-sig"))
    active = json.loads(active_path.read_text(encoding="utf-8-sig"))

    def merge(template_value: Any, active_value: Any) -> Any:
        if isinstance(template_value, dict) and isinstance(active_value, dict):
            merged = {
                key: merge(value, active_value[key])
                if key in active_value
                else value
                for key, value in template_value.items()
            }
            merged.update(
                {key: value for key, value in active_value.items() if key not in merged}
            )
            return merged
        return active_value

    active_path.write_text(
        json.dumps(merge(template, active), indent=2) + "\n",
        encoding="utf-8",
    )


def subnet_plan(cidr: str) -> dict[str, str]:
    network = ipaddress.ip_network(cidr, strict=True)
    if network.version != 4:
        raise ValueError("Only IPv4 CIDR ranges are supported")
    if network.prefixlen > 20:
        raise ValueError("The AI Factory vNet must be /20 or larger; /16 is recommended")

    subnets = list(network.subnets(new_prefix=26))
    if len(subnets) < 4:
        raise ValueError(f"{cidr} does not contain the four required /26 common subnets")
    return {
        "common_vnet_cidr": str(network),
        "common_subnet_cidr": str(subnets[0]),
        "common_subnet_scoring_cidr": str(subnets[1]),
        "common_pbi_subnet_cidr": str(subnets[2]),
        "common_bastion_subnet_cidr": str(subnets[3]),
        "cidr_selector": str(subnets[0].network_address).split(".")[2],
    }


def common_values(state: dict[str, Any]) -> dict[str, Any]:
    plan = subnet_plan(state["dev_vnet_cidr"])
    group_id = state["team_group_id"]
    project_sp = state.get("project_sp_secret_names") or {}
    hub = state["topology"] == "hs" or state.get("access_hub_mode") == "external"
    self_hosted = state.get("runner_mode") == "self-hosted"
    enable_admin_vm = self_hosted or state["add_bastion"] == "true"
    lake_prefix = re.sub(r"[^a-z0-9]", "", state["prefix"].lower())[:8]
    values = {
        "admin_location": state["location"],
        "admin_locationSuffix": state["location_short"],
        "admin_aifactoryPrefixRG": state["prefix"],
        "admin_aifactorySuffixRG": state["scaleset_suffix"],
        "dev_admin_bicep_input_keyvault_subscription": state["seeding_subscription_id"],
        "dev_admin_bicep_kv_fw_rg": state["seeding_resource_group"],
        "dev_admin_bicep_kv_fw": state["seeding_keyvault_name"],
        "test_admin_bicep_input_keyvault_subscription": state["stage_subscription_id"],
        "test_admin_bicep_kv_fw_rg": state["seeding_resource_group"],
        "test_admin_bicep_kv_fw": state["seeding_keyvault_name"],
        "prod_admin_bicep_input_keyvault_subscription": state["prod_subscription_id"],
        "prod_admin_bicep_kv_fw_rg": state["seeding_resource_group"],
        "prod_admin_bicep_kv_fw": state["seeding_keyvault_name"],
        "azure_machinelearning_sp_oid": state.get("azure_ml_principal_id", ""),
        "databricksOID": state.get("databricks_principal_id", ""),
        "use_ad_groups": "true",
        "centralDnsZoneByPolicyInHub": "true" if hub else "false",
        "privDnsSubscription_param": state.get("hub_subscription_id", ""),
        "privDnsResourceGroup_param": state.get("hub_resource_group", ""),
        "tenantId": state["tenant_id"],
        "inputCommonSPIDKey": "",
        "inputCommonSPSecretKey": "",
        "commonServicePrincipleOIDKey": "",
        "enablePublicGenAIAccess": state["enable_public_genai_access"],
        "allowPublicAccessWhenBehindVnet": state["allow_public_access_behind_vnet"],
        "enablePublicAccessWithPerimeter": state["enable_public_perimeter"],
        "addBastionHost": state["add_bastion"],
        "enableAdminVM": "true" if enable_admin_vm else "false",
        "adminVMSize": state.get("admin_vm_size", "Standard_D2s_v5"),
        "useSelfHostedBuildAgent": "true" if self_hosted else "false",
        "adminVMBuildAgentPool": state.get("ado_agent_pool", "Default"),
        "adminVMBuildAgentName": state.get("ado_agent_name", ""),
        "disable_whitelisting_for_build_agents": "true" if self_hosted else "false",
        "BYO_subnets": "false",
        "vnetResourceGroup_param": "",
        "vnetNameFull_param": "",
        "commonResourceGroup_param": "",
        "commonLakeNamePrefixMax8chars": lake_prefix or "aifactory",
        "dev_sub_id": state["dev_subscription_id"],
        "test_sub_id": state["stage_subscription_id"],
        "prod_sub_id": state["prod_subscription_id"],
        **{key: value for key, value in plan.items() if key != "cidr_selector"},
        "dev_cidr_range": plan["cidr_selector"],
        "test_cidr_range": plan["cidr_selector"],
        "prod_cidr_range": plan["cidr_selector"],
        "project_number_000": state["project_number"],
        "project_IP_whitelist": state.get("ip_allowlist", ""),
        "technical_admins_ad_object_id": group_id,
        "technical_admins_email": state["team_group_name"],
        "project_service_principal_AppID_seeding_kv_name": project_sp.get("app_id", ""),
        "project_service_principal_OID_seeding_kv_name": project_sp.get("object_id", ""),
        "project_service_principal_Secret_seeding_kv_name": project_sp.get("secret", ""),
        "groups_project_members_genai_1": ",".join([group_id] * 5),
        "groups_coreteam_members": ",".join([group_id] * 3),
    }
    if state.get("cost_center"):
        values.update({"tag_costceter_common": state["cost_center"], "tag_costcenter": state["cost_center"]})
    if simple_mode_enabled(state):
        if state["dev_vnet_cidr"] != "172.16.0.0/20":
            raise ValueError("Simple Mode contract v2 requires Dev VNet 172.16.0.0/20")
        values.update(simple_mode_values(
            state.get("cost_center") or "123456", state.get("simple_project_resources_json"),
            state.get("github_repository_visibility") or "private"))
        values["technical_admins_email"] = state.get("team_member_email") or state["team_group_name"]
        # GHA passes tags directly to ARM, so resolve the cost center rather than
        # exporting ADO's $(...) expressions into GitHub Actions.
        tags = {"CostCenter": values["tag_costcenter"], "AIF-Scaleset": state["scaleset_suffix"],
                "AIF-Environment": "dev", "AIF-Project Owners": values["technical_admins_email"]}
        values["tags"] = json.dumps({**tags, "Description": "AI Factory common"})
        values["tagsProject"] = json.dumps({**tags, "AIFactory project": "001"})
    return values


def apply_ado(repo_root: Path, state: dict[str, Any]) -> None:
    yaml_path = (
        repo_root
        / "aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"
    )
    json_path = repo_root / "aifactory/variables.json"
    yaml_template_path = yaml_path.with_name("variables-template.yaml")
    json_template_path = repo_root / "aifactory/variables-template.json"
    if yaml_template_path.is_file():
        merge_yaml_template(yaml_template_path, yaml_path)
        yaml_template_path.unlink()
    if json_template_path.is_file():
        merge_json_template(json_template_path, json_path)
        json_template_path.unlink()
    values = common_values(state)
    values.update(
        {
            "azureDevOpsTenantId": state["ado_tenant_id"],
            "dev_service_connection": state["dev_service_connection"],
            "test_service_connection": state["stage_service_connection"],
            "prod_service_connection": state["prod_service_connection"],
            "dev_seeding_kv_service_connection": state["dev_service_connection"],
            "test_seeding_kv_service_connection": state["stage_service_connection"],
            "prod_seeding_kv_service_connection": state["prod_service_connection"],
        }
    )
    update_yaml(yaml_path, values)
    update_json(json_path, values)


def apply_gha(repo_root: Path, state: dict[str, Any]) -> None:
    env_path = repo_root / ".env"
    json_path = repo_root / "aifactory/variables.json"
    env_template_path = repo_root / ".env.template"
    json_template_path = repo_root / "aifactory/variables-template.json"
    if env_template_path.is_file():
        merge_env_template(env_template_path, env_path)
        env_template_path.unlink()
    if json_template_path.is_file():
        merge_json_template(json_template_path, json_path)
        json_template_path.unlink()
    common = common_values(state)
    project_sp = state.get("project_sp_secret_names") or {}
    plan = subnet_plan(state["dev_vnet_cidr"])
    hub = state["topology"] == "hs" or state.get("access_hub_mode") == "external"
    self_hosted = state.get("runner_mode") == "self-hosted"
    enable_admin_vm = self_hosted or state["add_bastion"] == "true"
    env_values = {
        "GITHUB_USERNAME": state["github_repository"].split("/", maxsplit=1)[0],
        "GITHUB_NEW_REPO": state["github_repository"],
        "TENANT_ID": state["tenant_id"],
        "AZURE_CLIENT_ID": state.get("oidc_client_id", ""),
        "AIFACTORY_LOCATION": state["location"],
        "AIFACTORY_LOCATION_SHORT": state["location_short"],
        "AIFACTORY_PREFIX": state["prefix"],
        "AIFACTORY_SUFFIX": state["scaleset_suffix"],
        "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID": state[
            "seeding_subscription_id"
        ],
        "AIFACTORY_SEEDING_KEYVAULT_NAME": state["seeding_keyvault_name"],
        "AIFACTORY_SEEDING_KEYVAULT_RG": state["seeding_resource_group"],
        "TENANT_AZUREML_OID": state.get("azure_ml_principal_id", ""),
        "DATABRICKS_OID": state.get("databricks_principal_id", ""),
        "USE_AD_GROUPS": "true",
        "DEV_SUBSCRIPTION_ID": state["dev_subscription_id"],
        "STAGE_SUBSCRIPTION_ID": state["stage_subscription_id"],
        "PROD_SUBSCRIPTION_ID": state["prod_subscription_id"],
        "DEV_CIDR_RANGE": plan["cidr_selector"],
        "STAGE_CIDR_RANGE": plan["cidr_selector"],
        "PROD_CIDR_RANGE": plan["cidr_selector"],
        "CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB": "true" if hub else "false",
        "PRIV_DNS_SUBSCRIPTION_PARAM": state.get("hub_subscription_id", ""),
        "PRIV_DNS_RESOURCE_GROUP_PARAM": state.get("hub_resource_group", ""),
        "ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET": state[
            "allow_public_access_behind_vnet"
        ],
        "ALLOW_PUBLIC_ACCESS_WHEN_BEHIND_VNET": state[
            "allow_public_access_behind_vnet"
        ],
        "ENABLE_PUBLIC_GENAI_ACCESS": state["enable_public_genai_access"],
        "ENABLE_PUBLIC_ACCESS_WITH_PERIMETER": state["enable_public_perimeter"],
        "ADD_BASTION_HOST": state["add_bastion"],
        "ENABLE_ADMIN_VM": "true" if enable_admin_vm else "false",
        "ADMIN_VM_SIZE": state.get("admin_vm_size", "Standard_D2s_v5"),
        "USE_SELF_HOSTED_BUILD_AGENT": "true" if self_hosted else "false",
        "DISABLE_WHITELISTING_FOR_BUILD_AGENTS": "true" if self_hosted else "false",
        "BYO_SUBNETS": "false",
        "VNET_RESOURCE_GROUP_PARAM": "",
        "VNET_NAME_FULL_PARAM": "",
        "COMMON_RESOURCE_GROUP_PARAM": "",
        "PROJECT_NUMBER": state["project_number"],
        "PROJECT_MEMBERS": state["team_group_id"],
        "PROJECT_MEMBERS_EMAILS": state["team_group_name"],
        "PROJECT_MEMBERS_IP_ADDRESS": state.get("ip_allowlist") or "-",
        "COMMON_SERVICE_PRINCIPAL_KV_S_NAME_APPID": "",
        "COMMON_SERVICE_PRINCIPAL_KV_S_NAME_SECRET": "",
        "INPUT_COMMON_SPID_KEY": "",
        "INPUT_COMMON_SP_SECRET_KEY": "",
        "COMMON_SERVICE_PRINCIPLE_OID_KEY": "",
        "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID": project_sp.get("app_id", ""),
        "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID": project_sp.get("object_id", ""),
        "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S": project_sp.get("secret", ""),
        "GROUPS_PROJECT_MEMBERS_GENAI_1": ",".join(
            [state["team_group_id"]] * 5
        ),
        "GROUPS_CORETEAM_MEMBERS": ",".join([state["team_group_id"]] * 3),
        "COMMON_VNET_CIDR": plan["common_vnet_cidr"],
        "COMMON_SUBNET_CIDR": plan["common_subnet_cidr"],
        "COMMON_SUBNET_SCORING_CIDR": plan["common_subnet_scoring_cidr"],
        "COMMON_PBI_SUBNET_CIDR": plan["common_pbi_subnet_cidr"],
        "COMMON_BASTION_SUBNET_CIDR": plan["common_bastion_subnet_cidr"],
    }
    if simple_mode_enabled(state):
        env_values.update(simple_mode_env_values(common))
        env_values["TAGS"] = common["tags"]
        env_values["TAGS_PROJECT"] = common["tagsProject"]
        env_values["PROJECT_MEMBERS_EMAILS"] = common["technical_admins_email"]
    update_env(env_path, env_values)
    update_json(json_path, common)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simple-mode-manifest", action="store_true")
    parser.add_argument("--verify-simple-mode-source", type=Path)
    parser.add_argument("--simple-mode-hub-subnets", type=Path)
    parser.add_argument("--simple-gateway-inputs", action="store_true")
    parser.add_argument("--project-resources")
    parser.add_argument("--repository-visibility", default="private")
    parser.add_argument("--app-gateway-hostname", default="")
    parser.add_argument("--app-gateway-backend-fqdn", default="")
    parser.add_argument("--app-gateway-certificate-secret-id", default="")
    parser.add_argument("--certificate-metadata", type=Path)
    parser.add_argument("--gateway-health", type=Path)
    parser.add_argument("--route", choices=("ado", "gha"))
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()

    if args.simple_mode_manifest:
        print(json.dumps(simple_mode_manifest(), indent=2))
        return 0
    if args.verify_simple_mode_source:
        verify_simple_mode_source(Path(__file__).resolve().parents[2], args.verify_simple_mode_source)
        return 0
    if args.simple_mode_hub_subnets:
        existing = json.loads(args.simple_mode_hub_subnets.read_text(encoding="utf-8-sig"))
        print(json.dumps(simple_mode_hub_subnets("172.16.0.0/20", existing)))
        return 0
    if args.simple_gateway_inputs:
        simple_mode_values(project_resources=args.project_resources, repository_visibility=args.repository_visibility)
        gateway = simple_mode_gateway_inputs(args.app_gateway_hostname, args.app_gateway_backend_fqdn,
                                             args.app_gateway_certificate_secret_id)
        if args.certificate_metadata:
            validate_simple_gateway_certificate(gateway, json.loads(args.certificate_metadata.read_text(encoding="utf-8-sig")))
        print(json.dumps(gateway))
        return 0
    if args.gateway_health:
        health = json.loads(args.gateway_health.read_text(encoding="utf-8-sig"))
        return 0 if simple_mode_gateway_healthy(health, args.app_gateway_backend_fqdn) else 1
    if not all((args.route, args.repo_root, args.state_file)):
        parser.error("--route, --repo-root and --state-file are required")
    state = json.loads(args.state_file.read_text(encoding="utf-8"))
    if args.route == "ado":
        apply_ado(args.repo_root, state)
    else:
        apply_gha(args.repo_root, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
