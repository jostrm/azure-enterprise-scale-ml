from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
YAML_PATH = ROOT / (
    "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/"
    "esml-yaml-pipelines/variables/variables.yaml"
)
ENV_TEMPLATE_PATH = ROOT / (
    "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template"
)

# ADO -> GitHub variable renames. Keys not listed default to their upper-cased name.
ALIASES = {
    "admin_location": "AIFACTORY_LOCATION",
    "admin_locationSuffix": "AIFACTORY_LOCATION_SHORT",
    "admin_aifactoryPrefixRG": "AIFACTORY_PREFIX",
    "admin_aifactorySuffixRG": "AIFACTORY_SUFFIX",
    "admin_aiSearchTier": "ADMIN_AISEARCH_TIER",
    "admin_semanticSearchTier": "AISEARCH_SEMANTIC_TIER",
    "admin_keyvaultSoftDeleteDays": "KEYVAULT_SOFT_DELETE",
    "aifactory_salt": "AIFACTORY_SALT",
    "aifactory_salt_random": "AIFACTORY_SALT_RANDOM",
    "aifactory_version_major": "AIFACTORY_VERSION_MAJOR",
    "aifactory_version_minor": "AIFACTORY_VERSION_MINOR",
    "dev_sub_id": "DEV_SUBSCRIPTION_ID",
    "test_sub_id": "STAGE_SUBSCRIPTION_ID",
    "prod_sub_id": "PROD_SUBSCRIPTION_ID",
    "dev_cidr_range": "DEV_CIDR_RANGE",
    "test_cidr_range": "STAGE_CIDR_RANGE",
    "prod_cidr_range": "PROD_CIDR_RANGE",
    "project_number_000": "PROJECT_NUMBER",
    "project_IP_whitelist": "PROJECT_MEMBERS_IP_ADDRESS",
    "technical_admins_ad_object_id": "PROJECT_MEMBERS",
    "technical_admins_email": "PROJECT_MEMBERS_EMAILS",
    "runNetworkingVar": "RUN_JOB1_NETWORKING",
    "admin_commonResourceSuffix": "ADMIN_COMMON_RESOURCE_SUFFIX",
    "admin_prjResourceSuffix": "ADMIN_PRJ_RESOURCE_SUFFIX",
    "use_ad_groups": "USE_AD_GROUPS",
    "tenantId": "TENANT_ID",
    "azure_machinelearning_sp_oid": "TENANT_AZUREML_OID",
    # Seeding key vault (ADO is per-env, GitHub template is single)
    "dev_admin_bicep_input_keyvault_subscription": "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID",
    "test_admin_bicep_input_keyvault_subscription": "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID",
    "prod_admin_bicep_input_keyvault_subscription": "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID",
    "dev_admin_bicep_kv_fw": "AIFACTORY_SEEDING_KEYVAULT_NAME",
    "test_admin_bicep_kv_fw": "AIFACTORY_SEEDING_KEYVAULT_NAME",
    "prod_admin_bicep_kv_fw": "AIFACTORY_SEEDING_KEYVAULT_NAME",
    "dev_admin_bicep_kv_fw_rg": "AIFACTORY_SEEDING_KEYVAULT_RG",
    "test_admin_bicep_kv_fw_rg": "AIFACTORY_SEEDING_KEYVAULT_RG",
    "prod_admin_bicep_kv_fw_rg": "AIFACTORY_SEEDING_KEYVAULT_RG",
}

# ADO-only keys that have no GitHub equivalent and should not fail the parity check.
KNOWN_MISSING = {
    "dev_service_connection",
    "test_service_connection",
    "prod_service_connection",
    "dev_seeding_kv_service_connection",
    "test_seeding_kv_service_connection",
    "prod_seeding_kv_service_connection",
    # CI-only or ADO-only variables not mirrored in GH .env template
    "admin_ip_fw",
    "aifactory_branch_chosen",
    "tag_costceter_common",
    "tag_repository",
    "tag_repository_branch",
    "tags",
    "cmkKeyName",
    "useCommonACR",
    "admin_hybridBenefit",
    "enableAMPLS",
    "projectPrefix",
    "projectSuffix",
    "vnetNameBase",
    "vnetResourceGroupBase",
    "common_subnet_name",
    "commonLakeNamePrefixMax8chars",
    "lakeContainerName",
    "adminUsername",
    "centralDnsZoneByPolicyInHub",
    "privDnsSubscription_param",
    "privDnsResourceGroup_param",
    "databricksOID",
    "databricksPrivate",
    "AMLStudioUIPrivate",
    "inputCommonSPIDKey",
    "inputCommonSPSecretKey",
    "commonServicePrincipleOIDKey",
    "enablePublicGenAIAccess",
    "allowPublicAccessWhenBehindVnet",
    "enablePublicAccessWithPerimeter",
    "disableContributorAccessForUsers",
    "disableRBACAdminOnRGForUsers",
    "addBastionHost",
    "enableAdminVM",
    "diagnosticSettingLevel",
    "common_vnet_cidr",
    "common_subnet_cidr",
    "common_subnet_scoring_cidr",
    "common_pbi_subnet_name",
    "common_pbi_subnet_cidr",
    "common_bastion_subnet_name",
    "common_bastion_subnet_cidr",
    "project_service_principal_AppID_seeding_kv_name",
    "project_service_principal_OID_seeding_kv_name",
    "project_service_principal_Secret_seeding_kv_name",
    "admin_projectType",
    "tag_costcenter",
    "tagsProject",
    "acr_IP_whitelist",
    "acr_adminUserEnabled",
    "acr_dedicated",
    "acr_SKU",
    "serviceSettingDeployProjectVM",
    "enableDefenderforAISubLevel",
    "enableDefenderforAIResourceLevel",
    "cmkKeyVersion",
    "updateKeyvaultRbac",
    "enableAIServices",
    "enableAIFoundryHub",
    "addAIFoundryHub",
    "enableAIFoundry",
    "updateAIFoundry",
    "addAIFoundry",
    "enableAFoundryCaphost",
    "foundryDeploymentType",
    "enableAIFactoryCreatedDefaultProjectForAIFv2",
    "disableAgentNetworkInjection",
    "enableDatafactory",
    "enableDatafactoryCommon",
    "enableAzureMachineLearning",
    "addAzureMachineLearning",
    "enableAksForAzureML",
    "aksOutboundType",
    "aksPrivateDNSZone",
    "aksAzureFirewallPrivateIp",
    "enableDatabricks",
    "enableAISearch",
    "addAISearch",
    "enableAISearchSharedPrivateLink",
    "enableAzureOpenAI",
    "enableAzureAIVision",
    "enableAzureSpeech",
    "enableAIDocIntelligence",
    "enableBing",
    "enableBingCustomSearch",
    "bingCustomSearchSku",
    "enableContentSafety",
    "enableCosmosDB",
    "cosmosKind",
    "enablePostgreSQL",
    "postGresAdminEmails",
    "enableRedisCache",
    "enableSQLDatabase",
    "enableFunction",
    "functionRuntime",
    "functionVersion",
    "enableWebApp",
    "webAppRuntime",
    "webAppRuntimeVersion",
    "aseSku",
    "aseSkuCode",
    "aseSkuWorkers",
    "enableContainerApps",
    "enableAppInsightsDashboard",
    "enableLogicApps",
    "enableEventHubs",
    "enableBotService",
    "foundryApiManagementResourceId",
    "admin_aks_nodes_testProd_override",
    "admin_aml_cluster_maxNodes_dev_override",
    "admin_aml_cluster_maxNodes_testProd_override",
    "admin_aml_cluster_sku_testProd_override",
    "admin_aml_computeInstance_dev_sku_override",
    "admin_aml_computeInstance_testProd_sku_override",
    "deployModel_gpt_X",
    "modelGPTXName",
    "modelGPTXVersion",
    "modelGPTXSku",
    "modelGPTXCapacity",
    "deployModel_text_embedding_ada_002",
    "deployModel_text_embedding_3_large",
    "deployModel_text_embedding_3_small",
    "deployModel_gpt_4o_mini",
    "deployModel_gpt_4o",
    "vnetResourceGroup_param",
    "vnetNameFull_param",
    "commonResourceGroup_param",
    "datalakeName_param",
    "kvNameFromCOMMON_param",
    "useCommonACR_override",
    "network_env_dev",
    "subnetCommon",
    "subnetCommonScoring",
    "subnetCommonPowerbiGw",
    "subnetProjGenAI",
    "subnetProjAKS",
    "subnetProjAKS2",
    "subnetProjACA",
    "subnetProjACA2",
    "subnetProjDatabricksPublic",
    "subnetProjDatabricksPrivate",
    "byoASEv3",
    "byoAseFullResourceId",
    "byoAseAppServicePlanResourceId",
    "debug_disable_validation_tasks",
    "debug_disable_67_data_ml_platform",
    "debugEnableCleaning",
    "enableRetries",
    "retryMinutes",
    "retryMinutesExtended",
    "maxRetryAttempts",
}


def _load_overrides_from_env() -> tuple[dict[str, str], set[str]]:
    """Allow ad-hoc overrides without changing the test file.

    Env vars:
      ENV_PARITY_ALIASES: comma-separated pairs like "src=DEST,foo=BAR"
      ENV_PARITY_KNOWN_MISSING: comma-separated keys to ignore from ADO
    """

    alias_env = {}
    raw_aliases = os.environ.get("ENV_PARITY_ALIASES", "").strip()
    if raw_aliases:
        for part in raw_aliases.split(","):
            if "=" not in part:
                continue
            src, dst = part.split("=", 1)
            if src and dst:
                alias_env[src.strip()] = dst.strip()

    missing_env: set[str] = set()
    raw_missing = os.environ.get("ENV_PARITY_KNOWN_MISSING", "").strip()
    if raw_missing:
        for part in raw_missing.split(","):
            if part.strip():
                missing_env.add(part.strip())

    return alias_env, missing_env


def _parse_yaml_vars(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.startswith("  "):
            continue
        if line.strip().startswith("#"):
            continue
        match = re.match(r"\s{2}([A-Za-z0-9_]+):\s*(.*)", line)
        if not match:
            continue
        key, raw = match.groups()
        raw = raw.split("#", 1)[0].strip()
        data[key] = raw.strip('"')
    return data


def _parse_env_template(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        raw = raw.split("#", 1)[0].strip()
        data[key] = raw.strip('"')
    return data


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return (
        not value
        or "<" in value
        or "todo" in lowered
        or value in {"-"}
    )


class TestADOToGitHubEnvParity(unittest.TestCase):
    def test_variables_yaml_has_env_equivalent(self) -> None:
        yaml_vars = _parse_yaml_vars(YAML_PATH)
        env_vars = _parse_env_template(ENV_TEMPLATE_PATH)

        alias_override, missing_override = _load_overrides_from_env()
        aliases = {**ALIASES, **alias_override}
        known_missing = KNOWN_MISSING | missing_override

        missing = []
        mismatched_defaults = []

        for key, yaml_val in yaml_vars.items():
            if key in known_missing:
                continue

            env_key = aliases.get(key, key.upper())
            if env_key not in env_vars:
                missing.append(f"{key} -> {env_key}")
                continue

            env_val = env_vars[env_key]
            if _is_placeholder(yaml_val) or _is_placeholder(env_val):
                continue

            if yaml_val != env_val:
                mismatched_defaults.append((key, env_key, yaml_val, env_val))

        self.assertFalse(
            missing,
            msg=(
                "Variables in variables.yaml missing from .env.template: "
                + ", ".join(missing)
            ),
        )

        self.assertFalse(
            mismatched_defaults,
            msg=(
                "Default values differ between variables.yaml and .env.template: "
                + "; ".join(
                    f"{src}({dst})='{yval}'!='{eval}'"
                    for src, dst, yval, eval in mismatched_defaults
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
