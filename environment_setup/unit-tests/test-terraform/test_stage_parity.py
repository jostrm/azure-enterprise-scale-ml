"""Terraform and Bicep agree on parameters, names and deployment conditions of 11/12/13.

Root scenarios start from the repository's variables.json. The expected side replays the Bicep workflow
(infra-common.yml with use_json_config_override) to get the --parameters of 01/02/03, then evaluates the
compiled Bicep: its name variables and the `if` of every module and resource. The Terraform side evaluates
the root module with `terraform console` (no plan, no credentials): local.p11/p12/p13, the stage `deploy`
maps that drive every count, and the stage name maps.

Stage scenarios call the stage modules directly with Bicep parameters the workflow never sets (AI gateway
networking, AMPLS, preserve-v1 networking ...), so every condition of the three entry files is exercised.
"""
from __future__ import annotations

import copy
import json

import pytest

from harness import (ENTRY_FILES, VARIABLES_JSON, bicep_conditions, bicep_parameters, bicep_variable, compiled,
                     console, replay_bicep_workflow)

SUB = "11111111-2222-4333-8444-555555555555"
TENANT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
SEED_SUB = "99999999-8888-4777-8666-555555555555"
EXPIRY = 1893456000
ENTRY_KEYS = {"11-rgCommon.bicep": "11", "12-networkCommon.bicep": "12", "13-rgLevel.bicep": "13"}

NAME_VARIABLES = {
    "11-rgCommon.bicep": ["commonResourceGroupName", "uniqueInAIFenv", "cmkIdentityName"],
    "12-networkCommon.bicep": ["commonResourceGroupName", "vnetResourceGroupName", "vnetNameFull",
                               "common_vnet_cidr_v", "common_subnet_cidr_v"],
    "13-rgLevel.bicep": ["commonResourceGroupName", "vnetResourceGroupName", "uniqueInAIFenv", "vnetNameFull",
                         "kvNameCommon", "kvNameCommonAdmin", "vnetId", "datalakeName", "cmkIdentityName",
                         "defaultSubnet", "commonSubnetScoring", "commonSubnetPowerBI", "acrCommonName", "laName",
                         "adfName", "common_bastion_host_name", "privDnsResourceGroupName", "privDnsSubscription"],
}


def base_config() -> dict:
    """The repository's variables.json with its <todo> placeholders filled with valid values."""
    config = json.loads(VARIABLES_JSON.read_text(encoding="utf-8"))
    dev = config["dev"]
    for environment in ("dev", "test", "prod"):
        dev[f"{environment}_sub_id"] = SUB
        dev[f"{environment}_admin_bicep_input_keyvault_subscription"] = SEED_SUB
        dev[f"{environment}_admin_bicep_kv_fw"] = f"kv-seed-{environment}"
        dev[f"{environment}_admin_bicep_kv_fw_rg"] = f"rg-seed-{environment}"
    dev["tenantId"] = TENANT
    dev["technical_admins_ad_object_id"] = "00000000-0000-4000-8000-000000000001"
    dev["technical_admins_email"] = "admin@contoso.example"
    dev["cmkKeyName"] = "aifactory-cmk-key"
    return config


def runtime(**overrides) -> dict:
    """GitHub secrets and variables of the Bicep job, and the same values as Terraform variables."""
    values = {
        "secrets": {"TENANT_ID": TENANT, "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID": SEED_SUB,
                    "PROJECT_MEMBERS": "00000000-0000-4000-8000-000000000002", "PROJECT_MEMBERS_IP_ADDRESS": ""},
        "vars": {"AZURE_SUBSCRIPTION_ID": SUB, "AIFACTORY_SEEDING_KEYVAULT_NAME": "kv-seed-runtime",
                 "AIFACTORY_SEEDING_KEYVAULT_RG": "rg-seed-runtime", "CIDR_RANGE": "42",
                 "PROJECT_MEMBERS_EMAILS": "team@contoso.example"},
        "network_env": "",
    }
    for key, value in overrides.items():
        if key in ("secrets", "vars"):
            values[key] = {**values[key], **value}
        else:
            values[key] = value
    return values


def terraform_variables(config_path, environment: str, run: dict) -> dict:
    secrets, github = run["secrets"], run["vars"]
    return {
        "config_file": config_path.as_posix(),
        "environment": environment,
        "subscription_id": github.get("AZURE_SUBSCRIPTION_ID", ""),
        "tenant_id": secrets.get("TENANT_ID", ""),
        "seeding_keyvault_subscription_id": secrets.get("AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID", ""),
        "seeding_keyvault_name": github.get("AIFACTORY_SEEDING_KEYVAULT_NAME", ""),
        "seeding_keyvault_resource_group": github.get("AIFACTORY_SEEDING_KEYVAULT_RG", ""),
        "cidr_range": github.get("CIDR_RANGE", ""),
        "network_env": run.get("network_env", ""),
        "technical_admins_ad_object_id": secrets.get("PROJECT_MEMBERS", ""),
        "technical_admins_email": github.get("PROJECT_MEMBERS_EMAILS", ""),
        "ip_whitelist": secrets.get("PROJECT_MEMBERS_IP_ADDRESS", ""),
        "admin_vm_exists": False,
        "key_vault_secret_expiry": EXPIRY,
    }


def with_dev(**changes) -> dict:
    config = base_config()
    config["dev"].update(changes)
    return config


ROOT_SCENARIOS = {
    "baseline-dev": (base_config(), "dev", runtime()),
    "everything-on-dev": (with_dev(
        cmk="true", enableAdminVM="true", addBastionHost="true", enableDatafactoryCommon="true",
        enableVmBackup="true", databricksOID="00000000-0000-4000-8000-0000000000db",
        inputCommonSPIDKey="esml-common-sp-id", inputCommonSPSecretKey="esml-common-sp-secret",
        commonServicePrincipleOIDKey="esml-common-sp-oid", technical_admins_ad_object_id="A1, b2 ,null,,A1",
        enableDefenderforAISubLevel="true", admin_hybridBenefit="true", acr_dedicated="false",
        enablePublicAccessWithPerimeter="false", use_ad_groups="false"),
        "dev", runtime(secrets={"PROJECT_MEMBERS_IP_ADDRESS": "10.1.2.3,20.30.40.0/24,10.1.2.3"})),
    "test-stage-prod-sections": (
        {**base_config(), "stage_prod": {"admin_aifactorySuffixRG": "-002", "runNetworkingVar": "false",
                                         "commonResourceGroup_param": "rg-common-<network_env>-fixed",
                                         "vnetResourceGroup_param": "rg-net-<network_env>",
                                         "vnetNameFull_param": "vnet-<network_env>-hub"},
         "test": {"admin_commonResourceSuffix": "-007", "commonLakeNamePrefixMax8chars": "lake"}},
        "test", runtime(network_env="tst-", vars={"CIDR_RANGE": "7"})),
    "prod-byo-subnets-personas-central-dns": (
        {**base_config(), "stage_prod": {
            "BYO_subnets": "true", "subnetCommon": "<network_env>snet-common",
            "subnetCommonScoring": "<network_env>snet-scoring", "subnetCommonPowerbiGw": "<network_env>snet-pbi",
            "vnetResourceGroup_param": "rg-<network_env>-spoke", "vnetNameFull_param": "vnet-<network_env>",
            "centralDnsZoneByPolicyInHub": True, "privDnsSubscription_param": "33333333-3333-4333-8333-333333333333",
            "privDnsResourceGroup_param": "rg-private-dns",
            "tags": json.dumps({"AIF-Persona-Access": "groups-v1", "CostCenter": "42"})}},
        "prod", runtime(network_env="prd-")),
    "own-hub-added-scale-set": (with_dev(
        access_hub_mode="integrated", setup_hub_access="true", admin_aifactorySuffixRG="-002",
        own_hub_vnet_id="/subscriptions/44444444-4444-4444-8444-444444444444/resourceGroups/rg-hub/providers/"
                        "Microsoft.Network/virtualNetworks/vnet-hub-001"),
        "dev", runtime()),
}


def write_json(path, payload) -> object:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def typed(entry: str, passed: dict) -> dict:
    template = compiled(entry)
    converted = bicep_parameters(template, passed)
    return {key: converted[key] for key in passed}


def full_parameters(entry: str, passed: dict) -> dict:
    template = compiled(entry)
    values = bicep_parameters(template, passed)
    if entry == "13-rgLevel.bicep":
        values["keyVaultSecretExpiry"] = EXPIRY
        values.setdefault("adminPassword", "not-a-secret-0")
    return values


def compare_names(entry: str, parameters: dict, terraform_names: dict) -> None:
    for variable in NAME_VARIABLES[entry]:
        assert variable in terraform_names, f"{entry}: Terraform names lack {variable}"
        expected = bicep_variable(entry, variable, parameters, SUB)
        assert terraform_names[variable] == expected, (entry, variable)


@pytest.mark.parametrize("scenario", sorted(ROOT_SCENARIOS))
def test_root_matches_the_bicep_workflow(scenario, terraform_copy, tmp_path):
    config, environment, run = ROOT_SCENARIOS[scenario]
    config_path = write_json(tmp_path / "variables.json", config)
    var_file = write_json(tmp_path / "terraform.tfvars.json", terraform_variables(config_path, environment, run))
    actual = console(terraform_copy["root"], """{
      p11 = local.p11, p12 = local.p12, p13 = local.p13, run = local.run_networking,
      deploy = { "11" = module.stage_11.deploy, "12" = try(module.stage_12[0].deploy, {}), "13" = module.stage_13.deploy },
      names  = { "11" = module.stage_11.names, "12" = try(module.stage_12[0].names, {}), "13" = module.stage_13.names }
    }""", var_file)
    replay = replay_bicep_workflow(config, environment, run)
    assert actual["run"] == replay["run_networking"]
    for entry in ENTRY_FILES:
        key = ENTRY_KEYS[entry]
        terraform_parameters = dict(actual[f"p{key}"])
        if entry == "13-rgLevel.bicep":
            assert terraform_parameters.pop("adminVmExists") is False
        assert terraform_parameters == typed(entry, replay[entry]), f"{entry} parameters differ"
        if entry == "12-networkCommon.bicep" and not replay["run_networking"]:
            assert actual["deploy"]["12"] == {} and actual["names"]["12"] == {}
            continue
        parameters = full_parameters(entry, replay[entry])
        if entry == "13-rgLevel.bicep":
            parameters["adminVmExists"] = False
        assert actual["deploy"][key] == bicep_conditions(entry, parameters, SUB), f"{entry} conditions differ"
        compare_names(entry, parameters, actual["names"][key])


def stage_base() -> dict:
    config, environment, run = ROOT_SCENARIOS["baseline-dev"]
    replay = replay_bicep_workflow(config, environment, run)
    return {entry: typed(entry, replay[entry]) for entry in ENTRY_FILES}


STAGE_SCENARIOS = {
    "ai-gateway-networking-only": {
        "12-networkCommon.bicep": {"deployAIGatewayNetworking": True, "deployOnlyAIGatewayNetworking": True,
                                   "ai_gateway_apim_cidr": "172.16.XX.128/27", "ai_gateway_app_cidr": "172.16.XX.160/27"},
        "13-rgLevel.bicep": {"deployOnlyAIGatewayNetworking": True, "addBastionHost": True, "enableAdminVM": True},
    },
    "ampls-and-no-queries": {
        "13-rgLevel.bicep": {"enableAMPLS": True, "enableLogAnalyticsQueries": False,
                             "existingAmplsLogAnalyticsWorkspaceIds": ["/subscriptions/x/resourceGroups/y/providers/"
                                                                       "Microsoft.OperationalInsights/workspaces/z"]},
    },
    "preserve-v1-networking": {
        "12-networkCommon.bicep": {"commonNetworkProfile": "preserve-v1", "IPwhiteList": "1.2.3.4",
                                   "preservationPlan": {"createVnet": True, "addressPrefixes": ["10.0.0.0/16"],
                                                        "createSubnets": [],
                                                        "createNetworkSecurityGroups": ["nsg-snet-esml-cmn-001-scoring",
                                                                                        "nsg-AzureBastionSubnet"]}},
    },
    "preserve-v1-common-nsg-only": {
        "12-networkCommon.bicep": {"commonNetworkProfile": "preserve-v1",
                                   "preservationPlan": {"createVnet": False, "addressPrefixes": [], "createSubnets": [],
                                                        "createNetworkSecurityGroups": ["nsg-snet-esml-cmn-001"]}},
    },
    "cmk-datafactory-vm-backup": {
        "11-rgCommon.bicep": {"cmk": True, "enableAdminVM": True, "enableDefenderforAISubLevel": True},
        "13-rgLevel.bicep": {"cmk": True, "enableDatafactoryCommon": True, "enableAdminVM": True,
                             "enableVmBackup": True, "adminVmExists": True, "centralDnsZoneByPolicyInHub": False,
                             "databricksOID": "00000000-0000-4000-8000-0000000000db"},
    },
}


@pytest.mark.parametrize("scenario", sorted(STAGE_SCENARIOS))
def test_stage_modules_match_the_bicep_conditions_and_names(scenario, terraform_copy, tmp_path):
    parameters = stage_base()
    for entry, changes in STAGE_SCENARIOS[scenario].items():
        parameters[entry] = {**copy.deepcopy(parameters[entry]), **changes}
    variables = {"p11": parameters["11-rgCommon.bicep"], "p12": parameters["12-networkCommon.bicep"],
                 "p13": parameters["13-rgLevel.bicep"], "subscription_id": SUB}
    var_file = write_json(tmp_path / "stages.tfvars.json", variables)
    actual = console(terraform_copy["wrapper"], """{
      deploy = { "11" = module.stage_11.deploy, "12" = module.stage_12.deploy, "13" = module.stage_13.deploy },
      names  = { "11" = module.stage_11.names, "12" = module.stage_12.names, "13" = module.stage_13.names }
    }""", var_file)
    for entry in ENTRY_FILES:
        key = ENTRY_KEYS[entry]
        values = full_parameters(entry, parameters[entry])
        assert actual["deploy"][key] == bicep_conditions(entry, values, SUB), f"{entry} conditions differ"
        compare_names(entry, values, actual["names"][key])


def test_scenarios_cover_every_condition_both_ways():
    """Across all scenarios every conditional Bicep module/resource is evaluated true at least once and false
    at least once, so no condition goes untested."""
    seen: dict[tuple[str, str], set[bool]] = {}
    base = stage_base()
    cases = []
    for config, environment, run in ROOT_SCENARIOS.values():
        replay = replay_bicep_workflow(config, environment, run)
        cases.append({entry: replay[entry] for entry in ENTRY_FILES})
    for changes in STAGE_SCENARIOS.values():
        case = {entry: {**base[entry], **changes.get(entry, {})} for entry in ENTRY_FILES}
        cases.append(case)
    for case in cases:
        for entry in ENTRY_FILES:
            values = full_parameters(entry, case[entry])
            for symbol, deployed in bicep_conditions(entry, values, SUB).items():
                seen.setdefault((entry, symbol), set()).add(deployed)
    conditional = {key for key in seen
                   if "condition" in compiled(key[0])["resources"][key[1]]}
    one_sided = sorted(f"{entry}:{symbol}={sorted(seen[(entry, symbol)])}" for entry, symbol in conditional
                       if seen[(entry, symbol)] != {True, False})
    assert not one_sided, "conditions never evaluated both ways: " + ", ".join(one_sided)
