# Port of environment_setup/aifactory/bicep/esml-common/main/13-rgLevel.bicep (targetScope subscription).
# Every module call below is a Bicep `module` of the same symbol; its `if` is local.deploy.<symbol>.
# Bicep `existing` references (resource group, vNet, subnets, the CMK identity, the seeding Key Vault) are
# resource ids built like resourceId(), or values the root passes in (cmk_identity, common_sp_*).

locals {
  p   = var.parameters
  sub = var.subscription_id

  common_resource_group_name = module.naming.common_resource_group_name
  vnet_resource_group_name   = module.naming.vnet_resource_group_name
  vnet_name_full             = module.naming.vnet_name_full
  vnet_id                    = module.naming.vnet_id
  names                      = module.naming.names
  unique_in_aif_env          = module.naming.unique_in_aif_env
  cmn_name                   = local.p.commonResourceShortName
  vnet_name_abbreviation     = local.p.vnetNameBase
  default_subnet             = module.naming.default_subnet

  # Scopes of the private DNS zones and of an own access hub (modules/common-scopes, also used by the root
  # to configure the private_dns and own_hub providers).
  bootstrap_managed_private_dns = module.scopes.bootstrap_managed_private_dns
  join_own_hub                  = module.scopes.join_own_hub
  own_hub_vnet_parts            = module.scopes.own_hub_vnet_parts
  priv_dns_resource_group_name  = module.scopes.priv_dns_resource_group_name
  priv_dns_subscription         = module.scopes.priv_dns_subscription

  # CMK identity created by 11-rgCommon ('resourcegroups' lower case, as the working portal template uses).
  cmk_identity_name        = local.names.cmkIdentityName
  cmk_identity_resource_id = "/subscriptions/${local.sub}/resourcegroups/${lower(local.common_resource_group_name)}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${local.cmk_identity_name}"
  cmk_identity_id_string   = local.p.cmk ? local.cmk_identity_resource_id : ""
  cmk_identity_client_id   = local.p.cmk ? try(var.cmk_identity.client_id, "") : ""
  # reference(resourceId(inputKeyvaultSubscription, inputKeyvaultResourcegroup, 'Microsoft.KeyVault/vaults', inputKeyvault)).vaultUri
  input_key_vault_uri = "https://${local.p.inputKeyvault}${var.key_vault_dns_suffix}/"

  # RBAC and IP rules. Bicep replace() is literal: '\\s+' is the two characters \s and +.
  ip_whitelist_array = (local.p.IPwhiteList == "" || local.p.IPwhiteList == "null") ? [] : split(",", replace(local.p.IPwhiteList, "\\s+", ""))
  processed_ip_rules = [for ip in local.ip_whitelist_array : { action = "Allow", value = strcontains(ip, "/") ? ip : "${ip}/32" }]
  kv_ip_rules        = [for ip in local.ip_whitelist_array : { action = "Allow", value = ip }]

  personas_groups_enabled = module.scopes.personas_groups_enabled
  technical_admins_object_ids = local.personas_groups_enabled ? [] : distinct([
    for id in split(",", local.p.technicalAdminsObjectID) : lower(trimspace(id))
    if lower(trimspace(id)) != "" && lower(trimspace(id)) != "null"
  ])

  use_common_sp_oid    = module.scopes.use_common_sp_oid
  use_common_sp_id     = module.scopes.use_common_sp_id
  use_common_sp_secret = module.scopes.use_common_sp_secret

  # Microsoft private DNS zones (2024-09-15: 25 entries). privateDnsZoneName / privateAznbDnsZoneName for AzureCloud.
  storage = var.storage_suffix
  zone_names = {
    blob                 = "privatelink.blob.${local.storage}"
    file                 = "privatelink.file.${local.storage}"
    dfs                  = "privatelink.dfs.${local.storage}"
    queue                = "privatelink.queue.${local.storage}"
    table                = "privatelink.table.${local.storage}"
    registry             = "privatelink.azurecr.io"
    vault                = "privatelink.vaultcore.azure.net"
    amlworkspace         = "privatelink.api.azureml.ms"
    notebooks            = "privatelink.notebooks.azure.net"
    dataFactory          = "privatelink.datafactory.azure.net"
    portal               = "privatelink.adf.azure.com"
    openai               = "privatelink.openai.azure.com"
    searchService        = "privatelink.search.windows.net"
    azurewebapps         = "privatelink.azurewebsites.net"
    cosmosdbnosql        = "privatelink.documents.azure.com"
    cognitiveservices    = "privatelink.cognitiveservices.azure.com"
    azuredatabricks      = "privatelink.azuredatabricks.net"
    namespace            = "privatelink.servicebus.windows.net"
    azureeventgrid       = "privatelink.eventgrid.azure.net"
    azuremonitor         = "privatelink.monitor.azure.com"
    azuremonitoroms      = "privatelink.oms.opinsights.azure.com"
    azuremonitorods      = "privatelink.ods.opinsights.azure.com"
    azuremonitoragentsvc = "privatelink.agentsvc.azure-automation.net"
    servicesai           = "privatelink.services.ai.azure.com"
    azurecontainerapps   = "privatelink.${local.p.location}.azurecontainerapps.io"
    redis                = "privatelink.redis.cache.windows.net"
    redisManaged         = "privatelink.redis.azure.net"
    postgres             = "privatelink.postgres.database.azure.com"
    sql                  = "privatelink.database.windows.net"
    cosmosdbmongo        = "privatelink.mongo.cosmos.azure.com"
    apim                 = "privatelink.azure-api.net"
  }
  # privateLinksDnsZonesArray: same order as the Bicep array.
  zone_order = ["blob", "file", "dfs", "queue", "table", "registry", "vault", "amlworkspace", "notebooks", "dataFactory",
    "portal", "openai", "searchService", "azurewebapps", "cosmosdbnosql", "cognitiveservices", "azuredatabricks",
    "namespace", "azureeventgrid", "azuremonitor", "azuremonitoroms", "azuremonitorods", "azuremonitoragentsvc",
  "servicesai", "azurecontainerapps", "redis", "redisManaged", "postgres", "sql", "cosmosdbmongo", "apim"]
  private_links_dns_zones = {
    for key, name in local.zone_names : key => {
      name = name
      id   = "/subscriptions/${local.priv_dns_subscription}/resourceGroups/${local.priv_dns_resource_group_name}/providers/Microsoft.Network/privateDnsZones/${name}"
    }
  }
  private_links_dns_zones_array = [for key in local.zone_order : local.private_links_dns_zones[key]]

  deploy_only_gw = local.p.deployOnlyAIGatewayNetworking
  central_dns    = local.p.centralDnsZoneByPolicyInHub
  personas       = local.personas_groups_enabled

  deploy = {
    cmkRbac                               = local.p.cmk
    createPrivateDnsZonesIfNotExists      = !local.central_dns && !local.bootstrap_managed_private_dns
    ownHubPeeringHubToSpoke               = local.join_own_hub
    ownHubPeeringSpokeToHub               = local.join_own_hub
    ownHubPrivateDnsLinks                 = local.join_own_hub
    acrCommon                             = !local.deploy_only_gw
    privateDnsContainerRegistryCommon     = !local.central_dns && !local.deploy_only_gw
    logAnalyticsWorkspaceOpInsight        = !local.deploy_only_gw
    wsQueries                             = local.p.enableLogAnalyticsQueries && !local.deploy_only_gw
    logAnalyticsAmpls                     = local.p.enableAMPLS && !local.deploy_only_gw
    adf                                   = !local.deploy_only_gw && local.p.enableDatafactoryCommon
    adfCmkRbac                            = local.p.cmk && !local.deploy_only_gw && local.p.enableDatafactoryCommon
    bastionHost                           = local.p.addBastionHost && !local.deploy_only_gw
    kvCmn                                 = !local.deploy_only_gw
    kvCmnDiagnostics                      = !local.deploy_only_gw
    spDatabricksKvSecretsUser             = !local.personas && local.p.databricksOID != "" && !local.deploy_only_gw
    spCmnKvSecretsUser                    = !local.personas && !local.deploy_only_gw && local.use_common_sp_oid
    adfKvSecretsUser                      = !local.personas && !local.deploy_only_gw && local.p.enableDatafactoryCommon
    kvCmnTechnicalContactSecretsOfficer   = !local.personas && !local.deploy_only_gw
    addSecret                             = !local.deploy_only_gw && local.use_common_sp_id && local.use_common_sp_secret && local.use_common_sp_oid
    kvAdmin                               = !local.deploy_only_gw
    kvAdminDiagnostics                    = !local.deploy_only_gw
    kvAdminTechnicalContactSecretsOfficer = !local.personas && !local.deploy_only_gw
    kvAdminCommonSPSecretsUser            = !local.personas && !local.deploy_only_gw && local.use_common_sp_oid
    kvAdminAdfSecretsUser                 = !local.personas && !local.deploy_only_gw && local.p.enableDatafactoryCommon
    dataLake                              = !local.deploy_only_gw
    vmPrivate                             = local.p.enableAdminVM && !local.deploy_only_gw
    privateDnsDatalake                    = !local.central_dns && !local.deploy_only_gw
    privateDnsKeyVaultCmn                 = !local.central_dns && !local.deploy_only_gw
    privateDnsKeyVaultAdmin               = !local.central_dns && !local.deploy_only_gw
    privateDnsAzureDatafactory            = !local.central_dns && !local.deploy_only_gw && local.p.enableDatafactoryCommon
  }

  key_vault_crypto_service_encryption_user = "e147488a-f6f5-4113-8e2d-b22465e65bf6"
  virtual_network_rules_2_add              = [{ id = "${local.vnet_id}/subnets/${local.default_subnet}", action = "Allow", state = "succeeded" }]
}

module "naming" {
  source                            = "../naming"
  subscription_id                   = local.sub
  env                               = local.p.env
  location                          = local.p.location
  location_suffix                   = local.p.locationSuffix
  aifactory_suffix_rg               = local.p.aifactorySuffixRG
  common_rg_name_prefix             = local.p.commonRGNamePrefix
  common_resource_name              = local.p.commonResourceName
  common_resource_suffix            = local.p.commonResourceSuffix
  common_resource_short_name        = local.p.commonResourceShortName
  common_resource_abbreviation      = local.p.commonResourceAbbreviation
  common_resource_group_param       = local.p.commonResourceGroup_param
  vnet_name_base                    = local.p.vnetNameBase
  vnet_resource_group_param         = local.p.vnetResourceGroup_param
  vnet_name_full_param              = local.p.vnetNameFull_param
  network_env                       = local.p.network_env
  common_lake_name_prefix_max8chars = local.p.commonLakeNamePrefixMax8chars
  common_subnet_name                = local.p.common_subnet_name
  byo_subnets                       = local.p.BYO_subnets
  subnet_common                     = local.p.subnetCommon
  subnet_common_scoring             = local.p.subnetCommonScoring
  subnet_common_powerbi_gw          = local.p.subnetCommonPowerbiGw
}

module "scopes" {
  source          = "../common-scopes"
  parameters      = local.p
  subscription_id = local.sub
}

# Assign "Key Vault Crypto Service Encryption User" to the CMK identity (identity created in 11-rgCommon)
module "cmkRbac" {
  source              = "../kv-rbac-single-assignment"
  count               = local.deploy.cmkRbac ? 1 : 0
  subscription_id     = local.p.inputKeyvaultSubscription
  resource_group_name = local.p.inputKeyvaultResourcegroup
  key_vault_name      = local.p.inputKeyvault
  principal_id        = var.cmk_identity.principal_id
  key_vault_role_id   = local.key_vault_crypto_service_encryption_user
  assignment_name     = "cmk-cmnrg-acr-rbac-${local.cmk_identity_name}"
  principal_type      = "ServicePrincipal"
}

module "createPrivateDnsZonesIfNotExists" {
  source                  = "../create-private-dns-zones"
  count                   = local.deploy.createPrivateDnsZonesIfNotExists ? 1 : 0
  priv_dns_subscription   = local.priv_dns_subscription
  priv_dns_resource_group = local.priv_dns_resource_group_name
  private_links_dns_zones = local.private_links_dns_zones_array
  v_net_name              = local.vnet_name_full
  v_net_resource_group    = local.vnet_resource_group_name
  location                = local.p.location
  all_global              = local.p.privateDnsAndVnetLinkAllGlobalLocation

  providers = {
    azurerm = azurerm.private_dns
  }
}

# Own access hub, added scale set: join the bootstrap's hub. Peering and link names are deterministic.
module "unique_vnet_id" {
  source = "../arm-unique-string"
  values = [local.vnet_id]
}

module "unique_own_hub_vnet_id" {
  source = "../arm-unique-string"
  values = [local.p.own_hub_vnet_id]
}

module "ownHubPeeringHubToSpoke" {
  source                = "../vnet-peering"
  count                 = local.deploy.ownHubPeeringHubToSpoke ? 1 : 0
  resource_group_name   = module.scopes.own_hub_resource_group_name
  vnet_name             = local.own_hub_vnet_parts[8]
  peering_name          = substr("peer-${local.vnet_name_full}-${module.unique_vnet_id.value}", 0, 80)
  remote_vnet_id        = local.vnet_id
  allow_gateway_transit = true
  use_remote_gateways   = false

  providers = {
    azurerm = azurerm.own_hub
  }
}

module "ownHubPeeringSpokeToHub" {
  source                = "../vnet-peering"
  count                 = local.deploy.ownHubPeeringSpokeToHub ? 1 : 0
  resource_group_name   = local.vnet_resource_group_name
  vnet_name             = local.vnet_name_full
  peering_name          = substr("peer-${local.own_hub_vnet_parts[8]}-${module.unique_own_hub_vnet_id.value}", 0, 80)
  remote_vnet_id        = local.p.own_hub_vnet_id
  allow_gateway_transit = false
  use_remote_gateways   = true

  depends_on = [module.ownHubPeeringHubToSpoke]
}

module "ownHubPrivateDnsLinks" {
  source                  = "../private-dns-zone-vnet-links"
  count                   = local.deploy.ownHubPrivateDnsLinks ? 1 : 0
  subscription_id         = local.priv_dns_subscription
  resource_group_name     = local.priv_dns_resource_group_name
  private_links_dns_zones = local.private_links_dns_zones_array
  vnet_id                 = local.vnet_id
  location                = local.p.location
  all_global              = local.p.privateDnsAndVnetLinkAllGlobalLocation

  providers = {
    azurerm = azurerm.private_dns
  }
}

module "acrCommon" {
  source                               = "../container-registry"
  count                                = local.deploy.acrCommon ? 1 : 0
  subscription_id                      = local.sub
  resource_group_name                  = local.common_resource_group_name
  container_registry_name              = local.names.acrCommonName
  sku_name                             = local.p.containerRegistrySkuName
  vnet_name                            = local.vnet_name_full
  vnet_resource_group_name             = local.vnet_resource_group_name
  subnet_name                          = local.default_subnet
  private_endpoint_name                = "pend-acr-${local.cmn_name}${local.p.locationSuffix}-containerreg-to-${local.vnet_name_abbreviation}"
  tags                                 = local.p.tags
  location                             = local.p.location
  enable_public_access_with_perimeter  = local.p.enablePublicAccessWithPerimeter
  allow_public_access_when_behind_vnet = local.p.allowPublicAccessWhenBehindVnet
  ip_rules                             = local.processed_ip_rules
  admin_user_enabled                   = local.p.acr_adminUserEnabled
  dedicated_data_point                 = local.p.acr_dedicated
  cmk                                  = local.p.cmk
  cmk_identity_id                      = local.p.cmk ? local.cmk_identity_id_string : ""
  cmk_identity_client_id               = local.p.cmk ? local.cmk_identity_client_id : ""
  cmk_key_name                         = local.p.cmk ? local.p.cmkKeyName : ""
  cmk_key_vault_uri                    = local.p.cmk ? local.input_key_vault_uri : ""

  depends_on = [module.cmkRbac]
}

module "privateDnsContainerRegistryCommon" {
  source                  = "../private-dns"
  count                   = local.deploy.privateDnsContainerRegistryCommon ? 1 : 0
  subscription_id         = local.sub
  resource_group_name     = local.common_resource_group_name
  dns_config              = module.acrCommon[0].dns_config
  private_links_dns_zones = local.private_links_dns_zones

  depends_on = [module.createPrivateDnsZonesIfNotExists, module.acrCommon]
}

# Log analytics WORKSPACE (dev,test,prod - 3 in the AI Factory, one per landing zone/environment)
module "logAnalyticsWorkspaceOpInsight" {
  source                  = "../log-analytics-workspace"
  count                   = local.deploy.logAnalyticsWorkspaceOpInsight ? 1 : 0
  subscription_id         = local.sub
  resource_group_name     = local.common_resource_group_name
  key_vault_secret_expiry = var.key_vault_secret_expiry
  name                    = local.names.laName
  tags                    = local.p.tags
  location                = local.p.location
  keyvault_name           = local.names.kvNameCommon
  enable_ampls            = local.p.enableAMPLS

  depends_on = [module.kvCmn]
}

module "wsQueries" {
  source              = "../log-analytics-queries"
  count               = local.deploy.wsQueries ? 1 : 0
  subscription_id     = local.sub
  resource_group_name = local.common_resource_group_name
  log_analytics_name  = local.names.laName
  deployment_name     = "logAnalyticsCmnQs${local.unique_in_aif_env}"

  depends_on = [module.logAnalyticsWorkspaceOpInsight]
}

# AMPLS integration (hub/spoke): attaches the workspace privately.
module "logAnalyticsAmpls" {
  source                  = "../ampls-integration"
  count                   = local.deploy.logAnalyticsAmpls ? 1 : 0
  subscription_id         = local.sub
  resource_group_name     = local.common_resource_group_name
  env                     = local.p.env
  location                = local.p.location
  location_suffix         = local.p.locationSuffix
  common_resource_suffix  = local.p.commonResourceSuffix
  tags                    = local.p.tags
  priv_dns_subscription   = local.priv_dns_subscription
  priv_dns_resource_group = local.priv_dns_resource_group_name
  hub_vnet_name           = local.vnet_name_full
  hub_vnet_resource_group = local.vnet_resource_group_name
  monitoring_subnet_name  = local.p.hubMonitoringSubnetName
  # Bicep union(existing, [workspace]): concat keeps the list length known at plan time.
  existing_log_analytics_workspace_ids = concat(local.p.existingAmplsLogAnalyticsWorkspaceIds, [module.logAnalyticsWorkspaceOpInsight[0].log_analytics_wksp_id])
  existing_application_insights_ids    = local.p.existingAmplsApplicationInsightsIds

  providers = {
    azurerm = azurerm.private_dns
  }
}

module "adf" {
  source                              = "../data-factory"
  count                               = local.deploy.adf ? 1 : 0
  name                                = local.names.adfName
  resource_group_name                 = local.common_resource_group_name
  location                            = local.p.location
  vnet_id                             = local.vnet_id
  subnet_name                         = local.default_subnet
  portal_private_endpoint_name        = "pend-${local.cmn_name}-${local.p.env}-${local.unique_in_aif_env}-adfportal-to-${local.vnet_name_abbreviation}"
  runtime_private_endpoint_name       = "pend-${local.cmn_name}-${local.p.env}-${local.unique_in_aif_env}-adfruntime-to-${local.vnet_name_abbreviation}"
  tags                                = local.p.tags
  enable_public_access_with_perimeter = local.p.enablePublicAccessWithPerimeter
  cmk                                 = local.p.cmk
  cmk_key_name                        = local.p.cmk ? local.p.cmkKeyName : ""
  key_vault_uri                       = local.p.cmk ? local.input_key_vault_uri : ""
  managed_identities = {
    system_assigned            = true
    user_assigned_resource_ids = local.p.cmk ? [local.cmk_identity_id_string] : []
  }
}

# Grant the Data Factory system-assigned identity access to the input Key Vault for CMK
module "adfCmkRbac" {
  source              = "../kv-rbac-single-assignment"
  count               = local.deploy.adfCmkRbac ? 1 : 0
  subscription_id     = local.p.inputKeyvaultSubscription
  resource_group_name = local.p.inputKeyvaultResourcegroup
  key_vault_name      = local.p.inputKeyvault
  principal_id        = module.adf[0].principal_id
  key_vault_role_id   = local.key_vault_crypto_service_encryption_user
  assignment_name     = "cmk-adf-rbac-${local.names.adfName}"
  principal_type      = "ServicePrincipal"
  role_description    = "Data Factory CMK access to Key Vault"

  depends_on = [module.cmkRbac]
}

module "bastionHost" {
  source              = "../bastion-host-common"
  count               = local.deploy.bastionHost ? 1 : 0
  name                = local.names.common_bastion_host_name
  resource_group_name = local.common_resource_group_name
  location            = local.p.location
  subnet_id           = "${local.vnet_id}/subnets/AzureBastionSubnet"
  tags                = local.p.tags
}

module "kvCmn" {
  source                          = "../key-vault"
  count                           = local.deploy.kvCmn ? 1 : 0
  subscription_id                 = local.sub
  resource_group_name             = local.common_resource_group_name
  key_vault_secret_expiry         = var.key_vault_secret_expiry
  keyvault_name                   = local.names.kvNameCommon
  location                        = local.p.location
  tags                            = local.p.tags
  tenant_identity                 = local.p.tenantId
  enable_purge_protection         = local.p.enablePurgeProtection
  soft_delete_days                = local.p.keyvaultSoftDeleteDays
  vnet_name                       = local.vnet_name_full
  vnet_resource_group_name        = local.vnet_resource_group_name
  subnet_name                     = local.default_subnet
  private_endpoint_name           = "pend-${local.names.kvNameCommon}-to-${local.vnet_name_abbreviation}"
  keyvault_network_policy_subnets = ["${local.vnet_id}/subnets/${local.default_subnet}"]
  ip_rules                        = local.kv_ip_rules

  depends_on = [module.dataLake]
}

# Resource logs (AuditEvent) of the common vault to the common Log Analytics workspace.
module "kvCmnDiagnostics" {
  source                     = "../key-vault-diagnostics"
  count                      = local.deploy.kvCmnDiagnostics ? 1 : 0
  subscription_id            = local.sub
  resource_group_name        = local.common_resource_group_name
  key_vault_name             = local.names.kvNameCommon
  log_analytics_workspace_id = module.logAnalyticsWorkspaceOpInsight[0].log_analytics_wksp_id

  depends_on = [module.kvCmn]
}

# Key Vault access is Azure RBAC (kv-rbac-principals).
module "spDatabricksKvSecretsUser" {
  source                   = "../kv-rbac-principals"
  count                    = local.deploy.spDatabricksKvSecretsUser ? 1 : 0
  subscription_id          = local.sub
  resource_group_name      = local.common_resource_group_name
  key_vault_role           = "secretsUser"
  principal_type           = "ServicePrincipal"
  key_vault_resource_name  = local.names.kvNameCommon
  principal_id             = local.p.databricksOID
  additional_principal_ids = []

  depends_on = [module.kvCmn]
}

module "spCmnKvSecretsUser" {
  source                   = "../kv-rbac-principals"
  count                    = local.deploy.spCmnKvSecretsUser ? 1 : 0
  subscription_id          = local.sub
  resource_group_name      = local.common_resource_group_name
  key_vault_role           = "secretsUser"
  principal_type           = "ServicePrincipal"
  key_vault_resource_name  = local.names.kvNameCommon
  principal_id             = var.common_sp_oid # externalKv.getSecret(commonServicePrincipleOIDKey)
  additional_principal_ids = []

  depends_on = [module.kvCmn]
}

module "adfKvSecretsUser" {
  source                        = "../kv-rbac-principals"
  count                         = local.deploy.adfKvSecretsUser ? 1 : 0
  subscription_id               = local.sub
  resource_group_name           = local.common_resource_group_name
  key_vault_role                = "secretsUser"
  principal_type                = "ServicePrincipal"
  key_vault_resource_name       = local.names.kvNameCommon
  principal_id                  = module.adf[0].principal_id
  principal_is_managed_identity = true
  additional_principal_ids      = []

  depends_on = [module.kvCmn, module.adf]
}

module "kvCmnTechnicalContactSecretsOfficer" {
  source                   = "../kv-rbac-principals"
  count                    = local.deploy.kvCmnTechnicalContactSecretsOfficer ? 1 : 0
  subscription_id          = local.sub
  resource_group_name      = local.common_resource_group_name
  key_vault_role           = "secretsOfficer"
  key_vault_resource_name  = local.names.kvNameCommon
  principal_id             = local.p.technicalContactId
  additional_principal_ids = local.technical_admins_object_ids

  depends_on = [module.kvCmn]
}

module "addSecret" {
  source                      = "../kv-secrets-cmn"
  count                       = local.deploy.addSecret ? 1 : 0
  subscription_id             = local.sub
  resource_group_name         = local.common_resource_group_name
  keyvault_name               = local.names.kvNameCommon
  key_vault_secret_expiry     = var.key_vault_secret_expiry
  esml_common_sp_id_secret    = var.common_sp_id_secret
  esml_common_sp_secret_value = var.common_sp_secret_value
  esml_common_sp_oid_value    = var.common_sp_oid_secret
  esml_tenant_id_secret       = local.p.tenantId

  depends_on = [module.kvCmn]
}

module "kvAdmin" {
  source                          = "../key-vault"
  count                           = local.deploy.kvAdmin ? 1 : 0
  subscription_id                 = local.sub
  resource_group_name             = local.common_resource_group_name
  key_vault_secret_expiry         = var.key_vault_secret_expiry
  keyvault_name                   = local.names.kvNameCommonAdmin
  location                        = local.p.location
  tags                            = local.p.tags
  tenant_identity                 = local.p.tenantId
  vnet_name                       = local.vnet_name_full
  vnet_resource_group_name        = local.vnet_resource_group_name
  subnet_name                     = local.default_subnet
  enable_purge_protection         = local.p.enablePurgeProtection
  soft_delete_days                = local.p.keyvaultSoftDeleteDays
  private_endpoint_name           = "pend-${local.names.kvNameCommonAdmin}-to-${local.vnet_name_abbreviation}"
  keyvault_network_policy_subnets = ["${local.vnet_id}/subnets/${local.default_subnet}"]
  ip_rules                        = local.kv_ip_rules
}

module "kvAdminDiagnostics" {
  source                     = "../key-vault-diagnostics"
  count                      = local.deploy.kvAdminDiagnostics ? 1 : 0
  subscription_id            = local.sub
  resource_group_name        = local.common_resource_group_name
  key_vault_name             = local.names.kvNameCommonAdmin
  log_analytics_workspace_id = module.logAnalyticsWorkspaceOpInsight[0].log_analytics_wksp_id

  depends_on = [module.kvAdmin]
}

module "kvAdminTechnicalContactSecretsOfficer" {
  source                   = "../kv-rbac-principals"
  count                    = local.deploy.kvAdminTechnicalContactSecretsOfficer ? 1 : 0
  subscription_id          = local.sub
  resource_group_name      = local.common_resource_group_name
  key_vault_role           = "secretsOfficer"
  key_vault_resource_name  = local.names.kvNameCommonAdmin
  principal_id             = local.p.technicalContactId
  additional_principal_ids = local.technical_admins_object_ids

  depends_on = [module.kvAdmin]
}

module "kvAdminCommonSPSecretsUser" {
  source                   = "../kv-rbac-principals"
  count                    = local.deploy.kvAdminCommonSPSecretsUser ? 1 : 0
  subscription_id          = local.sub
  resource_group_name      = local.common_resource_group_name
  key_vault_role           = "secretsUser"
  principal_type           = "ServicePrincipal"
  key_vault_resource_name  = local.names.kvNameCommonAdmin
  principal_id             = var.common_sp_oid # externalKv.getSecret(commonServicePrincipleOIDKey)
  additional_principal_ids = []

  depends_on = [module.kvAdmin]
}

module "kvAdminAdfSecretsUser" {
  source                        = "../kv-rbac-principals"
  count                         = local.deploy.kvAdminAdfSecretsUser ? 1 : 0
  subscription_id               = local.sub
  resource_group_name           = local.common_resource_group_name
  key_vault_role                = "secretsUser"
  principal_type                = "ServicePrincipal"
  key_vault_resource_name       = local.names.kvNameCommonAdmin
  principal_id                  = module.adf[0].principal_id
  principal_is_managed_identity = true
  additional_principal_ids      = []

  depends_on = [module.kvAdmin, module.adf]
}

module "dataLake" {
  source                      = "../data-lake"
  count                       = local.deploy.dataLake ? 1 : 0
  subscription_id             = local.sub
  resource_group_name         = local.common_resource_group_name
  storage_account_name        = local.names.datalakeName
  container_name              = local.p.lakeContainerName
  sku_name                    = local.p.skuNameStorage
  location                    = local.p.location
  vnet_name                   = local.vnet_name_full
  vnet_resource_group_name    = local.vnet_resource_group_name
  subnet_name                 = local.default_subnet
  blob_private_endpoint_name  = "pend-${local.names.datalakeName}-blob-to-${local.vnet_name_abbreviation}"
  file_private_endpoint_name  = "pend-${local.names.datalakeName}-file-to-${local.vnet_name_abbreviation}"
  dfs_private_endpoint_name   = "pend-${local.names.datalakeName}-dfs-to-${local.vnet_name_abbreviation}"
  queue_private_endpoint_name = "pend-${local.names.datalakeName}-queue-to-${local.vnet_name_abbreviation}"
  table_private_endpoint_name = "pend-${local.names.datalakeName}-table-to-${local.vnet_name_abbreviation}"
  tags                        = local.p.tags
  virtual_network_rules       = local.virtual_network_rules_2_add
  ip_whitelist_array          = local.ip_whitelist_array
  cmk                         = local.p.cmk
  cmk_identity_id             = local.p.cmk ? local.cmk_identity_id_string : ""
  cmk_key_name                = local.p.cmk ? local.p.cmkKeyName : ""
  cmk_key_vault_uri           = local.p.cmk ? local.input_key_vault_uri : ""

  # Must wait for the CMK identity to have Key Vault permissions before storage configures CMK encryption.
  depends_on = [module.cmkRbac]
}

module "vmPrivate" {
  source                    = "../virtual-machine-private"
  count                     = local.deploy.vmPrivate ? 1 : 0
  subscription_id           = local.sub
  resource_group_name       = local.common_resource_group_name
  admin_username            = local.p.adminUsername
  admin_password            = var.admin_password
  hybrid_benefit            = local.p.hybridBenefit
  vm_size                   = local.p.adminVMSize
  location                  = local.p.location
  vm_name                   = local.names.vmName
  subnet_name               = local.default_subnet
  vnet_id                   = local.vnet_id
  tags                      = local.p.tags
  keyvault_name             = module.kvAdmin[0].keyvault_name
  vm_exists                 = local.p.adminVmExists
  enable_encryption_at_host = local.p.enableEncryptionAtHost
  enable_vm_backup          = local.p.enableVmBackup

  depends_on = [module.kvAdmin]
}

module "privateDnsDatalake" {
  source                  = "../private-dns"
  count                   = local.deploy.privateDnsDatalake ? 1 : 0
  subscription_id         = local.sub
  resource_group_name     = local.common_resource_group_name
  dns_config              = module.dataLake[0].dns_config
  private_links_dns_zones = local.private_links_dns_zones

  depends_on = [module.createPrivateDnsZonesIfNotExists, module.dataLake]
}

module "privateDnsKeyVaultCmn" {
  source                  = "../private-dns"
  count                   = local.deploy.privateDnsKeyVaultCmn ? 1 : 0
  subscription_id         = local.sub
  resource_group_name     = local.common_resource_group_name
  dns_config              = module.kvCmn[0].dns_config
  private_links_dns_zones = local.private_links_dns_zones

  depends_on = [module.createPrivateDnsZonesIfNotExists, module.kvCmn]
}

module "privateDnsKeyVaultAdmin" {
  source                  = "../private-dns"
  count                   = local.deploy.privateDnsKeyVaultAdmin ? 1 : 0
  subscription_id         = local.sub
  resource_group_name     = local.common_resource_group_name
  dns_config              = module.kvAdmin[0].dns_config
  private_links_dns_zones = local.private_links_dns_zones

  depends_on = [module.createPrivateDnsZonesIfNotExists, module.kvAdmin]
}

module "privateDnsAzureDatafactory" {
  source                  = "../private-dns"
  count                   = local.deploy.privateDnsAzureDatafactory ? 1 : 0
  subscription_id         = local.sub
  resource_group_name     = local.common_resource_group_name
  dns_config              = module.adf[0].dns_config
  private_links_dns_zones = local.private_links_dns_zones

  depends_on = [module.createPrivateDnsZonesIfNotExists, module.adf]
}
