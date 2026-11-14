# Reads the AI Factory variables.json once and builds the parameters of the three stages exactly as
# bicep/copy_to_local_settings/github-actions/infra-common.yml builds the --parameters of
#   01_az_bicep_common_rg          -> 11-rgCommon.bicep      -> local.p11
#   02_az_bicep_private_networking -> 12-networkCommon.bicep -> local.p12
#   03_az_bicep_deploy_resources   -> 13-rgLevel.bicep       -> local.p13
# This is the only mapping from configuration keys to deployment parameters in the Terraform port. The test
# suite (environment_setup/unit-tests/test-terraform) replays the Bicep workflow on the same variables.json and
# checks that local.p11/p12/p13 equal the parameters the Bicep deployments receive.

locals {
  config = jsondecode(file(var.config_file))

  # apply-json-config-overrides.py: the "dev" section is the baseline; test/prod add "stage_prod", then their
  # own section. Obsolete alias keys fill their canonical key when that is absent.
  aliases = {
    acrIpWhitelist          = "acr_IP_whitelist"
    admin_username          = "adminUsername"
    ENABLEPERSONAS          = "enablePersonas"
    ENABLE_PERSONAS         = "enablePersonas"
    PERSONA_ACCESS_MODE     = "persona_access_mode"
    PERSONA_ACCESS_MANIFEST = "persona_access_manifest"
  }
  sections = {
    for section in ["dev", "stage_prod", "test", "prod"] : section => merge(
      { for key, value in try(local.config[section], {}) : key => value if !contains(keys(local.aliases), key) },
      {
        for alias, canonical in local.aliases : canonical => local.config[section][alias]
        if contains(keys(try(local.config[section], {})), alias) && !contains(keys(try(local.config[section], {})), canonical)
      },
    )
  }
  values = var.environment == "dev" ? local.sections.dev : merge(local.sections.dev, local.sections.stage_prod, local.sections[var.environment])

  # Every value as the string the workflow passes on the command line (booleans lower case, objects as JSON).
  json = { for key, value in local.values : key => value == null ? "" : (can(tostring(value)) ? tostring(value) : jsonencode(value)) }

  # The job environment of infra-common.yml after the JSON override: a configuration key of the same name
  # wins, then a key bound through the GitHub variable the job reads, then the job's default or the runtime
  # value the Terraform workflow passes from the same GitHub secret or variable.
  env_name = var.environment
  gh = {
    admin_aifactorySuffixRG               = lookup(local.json, "admin_aifactorySuffixRG", "")
    admin_aifactoryPrefixRG               = lookup(local.json, "admin_aifactoryPrefixRG", "")
    admin_location                        = lookup(local.json, "admin_location", "")
    admin_locationSuffix                  = lookup(local.json, "admin_locationSuffix", "")
    admin_commonResourceSuffix            = lookup(local.json, "admin_commonResourceSuffix", "-001")
    admin_prjResourceSuffix               = lookup(local.json, "admin_prjResourceSuffix", "-001")
    admin_keyvaultSoftDeleteDays          = lookup(local.json, "admin_keyvaultSoftDeleteDays", "")
    admin_hybridBenefit                   = lookup(local.json, "admin_hybridBenefit", "")
    vnetResourceGroupBase                 = lookup(local.json, "vnetResourceGroupBase", "esml-common")
    vnetNameBase                          = lookup(local.json, "vnetNameBase", "vnt-esmlcmn")
    commonResourceGroup_param             = lookup(local.json, "commonResourceGroup_param", "")
    vnetResourceGroup_param               = lookup(local.json, "vnetResourceGroup_param", "")
    vnetNameFull_param                    = lookup(local.json, "vnetNameFull_param", "")
    datalakeName_param                    = lookup(local.json, "datalakeName_param", "")
    kvNameFromCOMMON_param                = lookup(local.json, "kvNameFromCOMMON_param", "")
    useCommonACR_override                 = lookup(local.json, "useCommonACR_override", "")
    tags                                  = lookup(local.json, "tags", "") == "" ? "{}" : local.json["tags"]
    enableAdminVM                         = lookup(local.json, "enableAdminVM", "")
    adminVMSize                           = lookup(local.json, "adminVMSize", "Standard_D2s_v5")
    enableEncryptionAtHost                = lookup(local.json, "enableEncryptionAtHost", "true")
    enableVmBackup                        = lookup(local.json, "enableVmBackup", "false")
    addBastionHost                        = lookup(local.json, "addBastionHost", "")
    adminUsername                         = lookup(local.json, "adminUsername", "")
    cmk                                   = lookup(local.json, "cmk", "false")
    cmkKeyName                            = lookup(local.json, "cmkKeyName", "esml-cmk-key")
    useAdGroups                           = lookup(local.json, "useAdGroups", lookup(local.json, "use_ad_groups", ""))
    enableDefenderforAISubLevel           = lookup(local.json, "enableDefenderforAISubLevel", "false")
    enableDefenderforAIResourceLevel      = lookup(local.json, "enableDefenderforAIResourceLevel", "false")
    technical_admins_ad_object_id         = lookup(local.json, "technical_admins_ad_object_id", var.technical_admins_ad_object_id)
    technical_admins_email                = lookup(local.json, "technical_admins_email", var.technical_admins_email)
    tenantId                              = lookup(local.json, "tenantId", var.tenant_id)
    BYO_subnets                           = lookup(local.json, "BYO_subnets", "false")
    runNetworkingVar                      = lookup(local.json, "runNetworkingVar", "true")
    common_subnet_name                    = lookup(local.json, "common_subnet_name", "snet-esml-cmn-001")
    common_vnet_cidr                      = lookup(local.json, "common_vnet_cidr", "")
    common_subnet_cidr                    = lookup(local.json, "common_subnet_cidr", "")
    common_subnet_scoring_cidr            = lookup(local.json, "common_subnet_scoring_cidr", "")
    common_pbi_subnet_name                = lookup(local.json, "common_pbi_subnet_name", "")
    common_pbi_subnet_cidr                = lookup(local.json, "common_pbi_subnet_cidr", "")
    common_bastion_subnet_cidr            = lookup(local.json, "common_bastion_subnet_cidr", "")
    subnetCommon                          = lookup(local.json, "subnetCommon", "")
    subnetCommonScoring                   = lookup(local.json, "subnetCommonScoring", "")
    subnetCommonPowerbiGw                 = lookup(local.json, "subnetCommonPowerbiGw", "")
    subnetProjGenAI                       = lookup(local.json, "subnetProjGenAI", "")
    subnetProjAKS                         = lookup(local.json, "subnetProjAKS", "")
    subnetProjACA                         = lookup(local.json, "subnetProjACA", "")
    subnetProjDatabricksPublic            = lookup(local.json, "subnetProjDatabricksPublic", "")
    subnetProjDatabricksPrivate           = lookup(local.json, "subnetProjDatabricksPrivate", "")
    byoASEv3                              = lookup(local.json, "byoASEv3", "false")
    byoAseFullResourceId                  = lookup(local.json, "byoAseFullResourceId", "")
    byoAseAppServicePlanResourceId        = lookup(local.json, "byoAseAppServicePlanResourceId", "")
    centralDnsZoneByPolicyInHub           = lookup(local.json, "centralDnsZoneByPolicyInHub", "")
    access_hub_mode                       = lookup(local.json, "access_hub_mode", "")
    setup_hub_access                      = lookup(local.json, "setup_hub_access", "") == "" ? "false" : local.json["setup_hub_access"]
    privDnsSubscription_param             = lookup(local.json, "privDnsSubscription_param", "")
    privDnsResourceGroup_param            = lookup(local.json, "privDnsResourceGroup_param", "")
    own_hub_vnet_id                       = lookup(local.json, "own_hub_vnet_id", "")
    own_hub_private_dns_resource_group_id = lookup(local.json, "own_hub_private_dns_resource_group_id", "")
    databricksOID                         = lookup(local.json, "databricksOID", "")
    inputCommonSPIDKey                    = lookup(local.json, "inputCommonSPIDKey", "")
    inputCommonSPSecretKey                = lookup(local.json, "inputCommonSPSecretKey", "")
    commonServicePrincipleOIDKey          = lookup(local.json, "commonServicePrincipleOIDKey", "")
    enableDatafactoryCommon               = lookup(local.json, "enableDatafactoryCommon", "false")
    acr_adminUserEnabled                  = lookup(local.json, "acr_adminUserEnabled", "")
    acr_dedicated                         = lookup(local.json, "acr_dedicated", "")
    acr_SKU                               = lookup(local.json, "acr_SKU", "Premium")
    enablePublicAccessWithPerimeter       = lookup(local.json, "enablePublicAccessWithPerimeter", "")
    commonLakeNamePrefixMax8chars         = lookup(local.json, "commonLakeNamePrefixMax8chars", "")
    lakeContainerName                     = lookup(local.json, "lakeContainerName", "")

    # Runtime values: GitHub secrets/variables in the Bicep workflow, Terraform variables here.
    dev_test_prod                           = local.env_name
    dev_test_prod_sub_id                    = var.subscription_id != "" ? var.subscription_id : lookup(local.json, "${local.env_name}_sub_id", "")
    admin_bicep_input_keyvault_subscription = var.seeding_keyvault_subscription_id != "" ? var.seeding_keyvault_subscription_id : lookup(local.json, "${local.env_name}_admin_bicep_input_keyvault_subscription", "")
    admin_bicep_kv_fw                       = var.seeding_keyvault_name != "" ? var.seeding_keyvault_name : lookup(local.json, "${local.env_name}_admin_bicep_kv_fw", "")
    admin_bicep_kv_fw_rg                    = var.seeding_keyvault_resource_group != "" ? var.seeding_keyvault_resource_group : lookup(local.json, "${local.env_name}_admin_bicep_kv_fw_rg", "")
    cidr_range                              = var.cidr_range != "" ? var.cidr_range : lookup(local.json, "${local.env_name}_cidr_range", "")
    network_env                             = var.network_env != "" ? var.network_env : local.env_name
    technical_admins_bastion_IP_whitelist   = var.ip_whitelist == "-" ? "" : var.ip_whitelist
  }

  is_true = { for key, value in local.gh : key => lower(value) == "true" }

  # Workflow step conditions.
  run_networking = local.gh.runNetworkingVar != "false" && local.gh.BYO_subnets != "true"

  # 01_az_bicep_common_rg
  p11 = {
    enableAdminVM                    = local.is_true.enableAdminVM
    aifactorySuffixRG                = local.gh.admin_aifactorySuffixRG
    commonRGNamePrefix               = local.gh.admin_aifactoryPrefixRG
    esmlCommonOverride               = local.gh.vnetResourceGroupBase
    commonResourceGroup_param        = local.gh.commonResourceGroup_param
    locationSuffix                   = local.gh.admin_locationSuffix
    location                         = local.gh.admin_location
    tags                             = jsondecode(local.gh.tags)
    inputKeyvault                    = local.gh.admin_bicep_kv_fw
    inputKeyvaultSubscription        = local.gh.admin_bicep_input_keyvault_subscription
    inputKeyvaultResourcegroup       = local.gh.admin_bicep_kv_fw_rg
    cmk                              = local.is_true.cmk
    cmkKeyName                       = local.gh.cmkKeyName
    commonResourceSuffix             = local.gh.admin_commonResourceSuffix
    env                              = local.gh.dev_test_prod
    technicalAdminsObjectID          = local.gh.technical_admins_ad_object_id
    useAdGroups                      = local.is_true.useAdGroups
    enableDefenderforAISubLevel      = local.is_true.enableDefenderforAISubLevel
    enableDefenderforAIResourceLevel = local.is_true.enableDefenderforAIResourceLevel
    technicalAdminsEmail             = local.gh.technical_admins_email
  }

  # 02_az_bicep_private_networking
  p12 = {
    aifactorySuffixRG              = local.gh.admin_aifactorySuffixRG
    commonRGNamePrefix             = local.gh.admin_aifactoryPrefixRG
    locationSuffix                 = local.gh.admin_locationSuffix
    location                       = local.gh.admin_location
    tags                           = jsondecode(local.gh.tags)
    commonResourceSuffix           = local.gh.admin_commonResourceSuffix
    vnetNameBase                   = local.gh.vnetNameBase
    commonResourceName             = local.gh.vnetResourceGroupBase
    common_subnet_name             = local.gh.common_subnet_name
    vnetResourceGroup_param        = local.gh.vnetResourceGroup_param
    vnetNameFull_param             = local.gh.vnetNameFull_param
    commonResourceGroup_param      = local.gh.commonResourceGroup_param
    datalakeName_param             = local.gh.datalakeName_param
    kvNameFromCOMMON_param         = local.gh.kvNameFromCOMMON_param
    useCommonACR                   = local.is_true.useCommonACR_override
    subnetCommon                   = local.gh.subnetCommon
    subnetCommonScoring            = local.gh.subnetCommonScoring
    subnetCommonPowerbiGw          = local.gh.subnetCommonPowerbiGw
    subnetProjGenAI                = local.gh.subnetProjGenAI
    subnetProjAKS                  = local.gh.subnetProjAKS
    subnetProjACA                  = local.gh.subnetProjACA
    subnetProjDatabricksPublic     = local.gh.subnetProjDatabricksPublic
    subnetProjDatabricksPrivate    = local.gh.subnetProjDatabricksPrivate
    byoASEv3                       = local.is_true.byoASEv3
    byoAseFullResourceId           = local.gh.byoAseFullResourceId
    byoAseAppServicePlanResourceId = local.gh.byoAseAppServicePlanResourceId
    common_vnet_cidr               = local.gh.common_vnet_cidr
    common_subnet_cidr             = local.gh.common_subnet_cidr
    common_subnet_scoring_cidr     = local.gh.common_subnet_scoring_cidr
    common_pbi_subnet_name         = local.gh.common_pbi_subnet_name
    common_pbi_subnet_cidr         = local.gh.common_pbi_subnet_cidr
    common_bastion_subnet_name     = "AzureBastionSubnet"
    common_bastion_subnet_cidr     = local.gh.common_bastion_subnet_cidr
    env                            = local.gh.dev_test_prod
    network_env                    = local.gh.network_env
    cidr_range                     = local.gh.cidr_range
    IPwhiteList                    = local.gh.technical_admins_bastion_IP_whitelist
  }

  # 03_az_bicep_deploy_resources (adminPassword and keyVaultSecretExpiry are separate stage variables)
  p13 = {
    aifactorySuffixRG                     = local.gh.admin_aifactorySuffixRG
    commonRGNamePrefix                    = local.gh.admin_aifactoryPrefixRG
    locationSuffix                        = local.gh.admin_locationSuffix
    location                              = local.gh.admin_location
    tags                                  = jsondecode(local.gh.tags)
    commonResourceSuffix                  = local.gh.admin_commonResourceSuffix
    vnetNameBase                          = local.gh.vnetNameBase
    common_subnet_name                    = local.gh.common_subnet_name
    resourceSuffix                        = local.gh.admin_prjResourceSuffix
    commonLakeNamePrefixMax8chars         = local.gh.commonLakeNamePrefixMax8chars
    hybridBenefit                         = local.is_true.admin_hybridBenefit
    addBastionHost                        = local.is_true.addBastionHost
    lakeContainerName                     = local.gh.lakeContainerName
    adminUsername                         = local.gh.adminUsername
    IPwhiteList                           = local.gh.technical_admins_bastion_IP_whitelist
    centralDnsZoneByPolicyInHub           = local.is_true.centralDnsZoneByPolicyInHub
    access_hub_mode                       = local.gh.access_hub_mode
    setup_hub_access                      = local.is_true.setup_hub_access
    privDnsSubscription_param             = local.gh.privDnsSubscription_param
    privDnsResourceGroup_param            = local.gh.privDnsResourceGroup_param
    own_hub_vnet_id                       = local.gh.own_hub_vnet_id
    own_hub_private_dns_resource_group_id = local.gh.own_hub_private_dns_resource_group_id
    tenantId                              = local.gh.tenantId
    databricksOID                         = local.gh.databricksOID
    enableAdminVM                         = local.is_true.enableAdminVM
    adminVMSize                           = local.gh.adminVMSize
    adminVmExists                         = var.admin_vm_exists
    enableEncryptionAtHost                = local.is_true.enableEncryptionAtHost
    enableVmBackup                        = local.is_true.enableVmBackup
    vnetResourceGroup_param               = local.gh.vnetResourceGroup_param
    vnetNameFull_param                    = local.gh.vnetNameFull_param
    commonResourceGroup_param             = local.gh.commonResourceGroup_param
    datalakeName_param                    = local.gh.datalakeName_param
    kvNameFromCOMMON_param                = local.gh.kvNameFromCOMMON_param
    useCommonACR                          = local.is_true.useCommonACR_override
    subnetCommon                          = local.gh.subnetCommon
    subnetCommonScoring                   = local.gh.subnetCommonScoring
    subnetCommonPowerbiGw                 = local.gh.subnetCommonPowerbiGw
    subnetProjGenAI                       = local.gh.subnetProjGenAI
    subnetProjAKS                         = local.gh.subnetProjAKS
    subnetProjACA                         = local.gh.subnetProjACA
    subnetProjDatabricksPublic            = local.gh.subnetProjDatabricksPublic
    subnetProjDatabricksPrivate           = local.gh.subnetProjDatabricksPrivate
    byoASEv3                              = local.is_true.byoASEv3
    byoAseFullResourceId                  = local.gh.byoAseFullResourceId
    byoAseAppServicePlanResourceId        = local.gh.byoAseAppServicePlanResourceId
    inputKeyvault                         = local.gh.admin_bicep_kv_fw
    inputKeyvaultSubscription             = local.gh.admin_bicep_input_keyvault_subscription
    inputKeyvaultResourcegroup            = local.gh.admin_bicep_kv_fw_rg
    cmk                                   = local.is_true.cmk
    cmkKeyName                            = local.gh.cmkKeyName
    inputCommonSPIDKey                    = local.gh.inputCommonSPIDKey
    inputCommonSPSecretKey                = local.gh.inputCommonSPSecretKey
    commonServicePrincipleOIDKey          = local.gh.commonServicePrincipleOIDKey
    env                                   = local.gh.dev_test_prod
    technicalAdminsObjectID               = local.gh.technical_admins_ad_object_id
    technicalAdminsEmail                  = local.gh.technical_admins_email
    keyvaultSoftDeleteDays                = tonumber(local.gh.admin_keyvaultSoftDeleteDays)
    BYO_subnets                           = local.is_true.BYO_subnets
    acr_adminUserEnabled                  = local.is_true.acr_adminUserEnabled
    acr_dedicated                         = local.is_true.acr_dedicated
    containerRegistrySkuName              = local.gh.acr_SKU
    network_env                           = local.gh.network_env
    enablePublicAccessWithPerimeter       = local.is_true.enablePublicAccessWithPerimeter
    enableDatafactoryCommon               = local.is_true.enableDatafactoryCommon
    commonResourceName                    = local.gh.vnetResourceGroupBase
  }

  subscription_id = local.gh.dev_test_prod_sub_id
}
