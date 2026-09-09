#!/usr/bin/env python3
"""Apply new-scale-set bootstrap answers to AI Factory configuration files."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from typing import Any


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
    if network.prefixlen > 18:
        raise ValueError("The AI Factory vNet must be /18 or larger; /16 is recommended")

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
    return {
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
    update_env(env_path, env_values)
    update_json(json_path, common)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", choices=("ado", "gha"), required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    args = parser.parse_args()

    state = json.loads(args.state_file.read_text(encoding="utf-8"))
    if args.route == "ado":
        apply_ado(args.repo_root, state)
    else:
        apply_gha(args.repo_root, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
