#!/usr/bin/env python3
"""Apply new-scale-set bootstrap answers to AI Factory configuration files."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from typing import Any


AIF_SIMPLE_MODE_CONTRACT_VERSION = 1
SIMPLE_MODE_PRESET_NAME = "private-ai-foundation-v1"
# These trees must be published together; the launcher must not copy dirty PURPLE
# files into a consumer to make an unpublished feature appear deployable.
SIMPLE_MODE_REQUIRED_SOURCE_PATHS = ("bootstrap", "environment_setup/aifactory")
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


def simple_mode_values(cost_center: str = "123456") -> dict[str, Any]:
    """Canonical secretless Dev foundation without model deployments."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cost_center):
        raise ValueError("Cost center must be 1-64 letters, digits, underscores or hyphens")
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
        "GITHUB_NEW_REPO_VISIBILITY": "private",
    }


def simple_mode_manifest() -> dict[str, Any]:
    """Read-only UI/CLI preview; no credentials, cloud discovery or mutations."""
    return {
        "contractVersion": AIF_SIMPLE_MODE_CONTRACT_VERSION,
        "preset": SIMPLE_MODE_PRESET_NAME,
        "requiredSourcePaths": list(SIMPLE_MODE_REQUIRED_SOURCE_PATHS),
        "environment": "dev",
        "futureEnvironments": ["stage", "prod"],
        "futureSubscriptionReferences": "Dev placeholders only; configure before future use",
        "limitations": [
            "No model deployments; add models only after quota validation",
            "AMPLS is disabled: canonical Application Insights/Log Analytics networking is not private-only",
            "Azure/GitHub sign-in and region availability must be validated before deployment",
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
        "policyIdentityRoles": ["Network Contributor (Dev subscription)"],
    }


def simple_mode_hub_subnets(cidr: str, existing: list[dict[str, Any]]) -> dict[str, str]:
    """Reserve both low-address blocks before either is created; never move subnets."""
    network = ipaddress.ip_network(cidr, strict=True)
    if str(network) != "172.16.0.0/20":
        raise ValueError("Simple Mode contract v1 requires Dev VNet 172.16.0.0/20")
    planned = {"GatewaySubnet": "172.16.1.0/27",
               "snet-dns-private-resolver": "172.16.1.32/28"}
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
        raise ValueError("Published accelerator lacks Simple Mode contract v1; publish PURPLE first")
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
        "GITHUB_NEW_REPO_VISIBILITY": "private",
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
        "enableAIFoundry": "true",
        "enableAFoundryCaphost": "true",
        "enableAIFactoryCreatedDefaultProjectForAIFv2": "true",
        "enableAISearch": "true",
        "enableAISearchSharedPrivateLink": "true",
        "enableCosmosDB": "true",
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
            raise ValueError("Simple Mode contract v1 requires Dev VNet 172.16.0.0/20")
        values.update(simple_mode_values(state.get("cost_center") or "123456"))
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
        "ENABLE_AI_FOUNDRY": "true",
        "ENABLE_FOUNDRY_CAPHOST": "true",
        "ENABLE_AIFACTORY_CREATED_DEFAULT_PROJECT_FOR_AIFV2": "true",
        "ENABLE_AI_SEARCH": "true",
        "ENABLE_AI_SEARCH_SHARED_PRIVATE_LINK": "true",
        "ENABLE_COSMOS_DB": "true",
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
