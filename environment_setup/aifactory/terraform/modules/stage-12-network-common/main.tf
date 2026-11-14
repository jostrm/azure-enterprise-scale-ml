# Port of environment_setup/aifactory/bicep/esml-common/main/12-networkCommon.bicep (targetScope subscription).
# Every module call below is a Bicep `module` of the same symbol; its `if` is local.deploy.<symbol>.

locals {
  p   = var.parameters
  sub = var.subscription_id

  common_vnet_cidr_v           = replace(local.p.common_vnet_cidr, "XX", local.p.cidr_range)
  common_subnet_cidr_v         = replace(local.p.common_subnet_cidr, "XX", local.p.cidr_range)
  common_pbi_subnet_cidr_v     = replace(local.p.common_pbi_subnet_cidr, "XX", local.p.cidr_range)
  common_bastion_subnet_cidr_v = replace(local.p.common_bastion_subnet_cidr, "XX", local.p.cidr_range)
  common_subnet_scoring_cidr_v = replace(local.p.common_subnet_scoring_cidr, "XX", local.p.cidr_range)
  ai_gateway_apim_cidr_v       = local.p.deployAIGatewayNetworking ? replace(local.p.ai_gateway_apim_cidr, "XX", local.p.cidr_range) : ""
  ai_gateway_app_cidr_v        = local.p.deployAIGatewayNetworking ? replace(local.p.ai_gateway_app_cidr, "XX", local.p.cidr_range) : ""

  vnet_resource_group_name = module.naming.vnet_resource_group_name_network
  vnet_name_full           = module.naming.vnet_name_full_network

  # Bicep replace() is literal: '\\s+' is the two characters \s and +, not a regular expression.
  ip_whitelist_array_1 = split(",", replace(local.p.IPwhiteList, "\\s+", ""))
  ip_whitelist_array   = (local.p.IPwhiteList == "" || local.p.IPwhiteList == "null" || length(local.p.IPwhiteList) < 5) ? [] : distinct(local.ip_whitelist_array_1)

  legacy       = local.p.commonNetworkProfile == "legacy"
  plan_nsgs    = try(local.p.preservationPlan.createNetworkSecurityGroups, [])
  nsg_common   = "nsg-${local.p.common_subnet_name}"
  nsg_scoring  = "nsg-${local.p.common_subnet_name}-scoring"
  nsg_bastion  = "nsg-${local.p.common_bastion_subnet_name}"
  nsg_pbi      = "nsg-${local.p.common_pbi_subnet_name}"
  byo_vnet     = local.p.vnetNameFull_param != ""
  ai_gw_name   = "ai-gateway"
  flow_logs_on = local.legacy

  deploy = {
    nsgCommon             = local.legacy || contains(local.plan_nsgs, local.nsg_common)
    nsgCommonScoring      = local.legacy || contains(local.plan_nsgs, local.nsg_scoring)
    nsgBastion            = length(local.ip_whitelist_array) > 0 && (local.legacy || contains(local.plan_nsgs, local.nsg_bastion))
    nsgBastionNoWhitelist = length(local.ip_whitelist_array) == 0 && (local.legacy || contains(local.plan_nsgs, local.nsg_bastion))
    nsgPBI                = local.legacy || contains(local.plan_nsgs, local.nsg_pbi)
    vNetCommon            = local.legacy && !local.p.BYO_subnets
    vNetCommonPreserve    = local.p.commonNetworkProfile == "preserve-v1"
    aiGatewayNetworking   = local.legacy && local.p.deployAIGatewayNetworking
  }
}

module "naming" {
  source                       = "../naming"
  subscription_id              = local.sub
  env                          = local.p.env
  location                     = local.p.location
  location_suffix              = local.p.locationSuffix
  aifactory_suffix_rg          = local.p.aifactorySuffixRG
  common_rg_name_prefix        = local.p.commonRGNamePrefix
  common_resource_name         = local.p.commonResourceName
  common_resource_suffix       = local.p.commonResourceSuffix
  common_resource_group_param  = local.p.commonResourceGroup_param
  vnet_name_base               = local.p.vnetNameBase
  vnet_resource_group_param    = local.p.vnetResourceGroup_param
  vnet_name_full_param         = local.p.vnetNameFull_param
  network_env                  = local.p.network_env
  common_subnet_name           = local.p.common_subnet_name
  byo_subnets                  = local.p.BYO_subnets
  subnet_common                = local.p.subnetCommon
  subnet_common_scoring        = local.p.subnetCommonScoring
  subnet_common_powerbi_gw     = local.p.subnetCommonPowerbiGw
  common_resource_short_name   = "cmn"
  common_resource_abbreviation = "esml"
}

module "nsgCommon" {
  source              = "../nsg-common"
  count               = local.deploy.nsgCommon ? 1 : 0
  name                = local.nsg_common
  enable_flow_logs    = local.flow_logs_on
  tags                = local.p.tags
  location            = local.p.location
  bastion_ip_range    = local.common_bastion_subnet_cidr_v
  resource_group_name = local.vnet_resource_group_name
}

module "nsgCommonScoring" {
  source              = "../nsg-common-scoring"
  count               = local.deploy.nsgCommonScoring ? 1 : 0
  name                = local.nsg_scoring
  enable_flow_logs    = local.flow_logs_on
  tags                = local.p.tags
  location            = local.p.location
  bastion_ip_range    = local.common_bastion_subnet_cidr_v
  resource_group_name = local.vnet_resource_group_name

  depends_on = [module.nsgCommon]
}

module "nsgBastion" {
  source              = "../nsg-bastion"
  count               = local.deploy.nsgBastion ? 1 : 0
  name                = local.nsg_bastion
  enable_flow_logs    = local.flow_logs_on
  tags                = local.p.tags
  location            = local.p.location
  ip_whitelist_array  = local.ip_whitelist_array
  resource_group_name = local.vnet_resource_group_name

  depends_on = [module.nsgCommonScoring]
}

module "nsgBastionNoWhitelist" {
  source              = "../nsg-bastion-no-whitelist"
  count               = local.deploy.nsgBastionNoWhitelist ? 1 : 0
  name                = local.nsg_bastion
  enable_flow_logs    = local.flow_logs_on
  tags                = local.p.tags
  location            = local.p.location
  ip_whitelist_array  = local.ip_whitelist_array
  resource_group_name = local.vnet_resource_group_name

  depends_on = [module.nsgCommonScoring]
}

module "nsgPBI" {
  source              = "../nsg-power-bi"
  count               = local.deploy.nsgPBI ? 1 : 0
  name                = local.nsg_pbi
  enable_flow_logs    = local.flow_logs_on
  tags                = local.p.tags
  location            = local.p.location
  resource_group_name = local.vnet_resource_group_name

  # The Bicep waits for whichever bastion NSG path is active; both are listed (the inactive one has no instance).
  depends_on = [module.nsgBastion, module.nsgBastionNoWhitelist]
}

module "vNetCommon" {
  source                            = "../vnet-common"
  count                             = local.deploy.vNetCommon ? 1 : 0
  location                          = local.p.location
  common_pbi_subnet_cidr            = local.common_pbi_subnet_cidr_v
  common_pbi_subnet_name            = local.p.common_pbi_subnet_name
  common_subnet_cidr                = local.common_subnet_cidr_v
  common_subnet_scoring_cidr        = local.common_subnet_scoring_cidr_v
  common_subnet_name                = local.p.common_subnet_name
  common_vnet_cidr                  = local.common_vnet_cidr_v
  common_bastion_subnet_name        = local.p.common_bastion_subnet_name
  common_bastion_subnet_cidr        = local.common_bastion_subnet_cidr_v
  tags                              = local.p.tags
  vnet_name_full                    = local.vnet_name_full
  central_dns_zone_by_policy_in_hub = local.p.centralDnsZoneByPolicyInHub
  deploy_only_ai_gateway_networking = local.p.deployOnlyAIGatewayNetworking
  byo_subnet                        = local.p.BYO_subnets
  byo_vnet                          = local.byo_vnet
  subscription_id                   = local.sub
  resource_group_name               = local.vnet_resource_group_name

  depends_on = [module.nsgCommon, module.nsgBastion, module.nsgPBI, module.nsgCommonScoring]
}

module "vNetCommonPreserve" {
  source              = "../vnet-common-preserve"
  count               = local.deploy.vNetCommonPreserve ? 1 : 0
  location            = local.p.location
  tags                = local.p.tags
  vnet_name_full      = local.vnet_name_full
  plan                = local.p.preservationPlan
  subscription_id     = local.sub
  resource_group_name = local.vnet_resource_group_name

  depends_on = [module.nsgCommon, module.nsgCommonScoring, module.nsgBastion, module.nsgBastionNoWhitelist, module.nsgPBI]
}

module "aiGatewayNetworking" {
  source                            = "../ai-gateway-networking"
  count                             = local.deploy.aiGatewayNetworking ? 1 : 0
  name                              = local.ai_gw_name
  location                          = local.p.location
  tags                              = local.p.tags
  aifactory_suffix_rg               = local.p.aifactorySuffixRG
  common_resource_suffix            = local.p.commonResourceSuffix
  common_rg_name_prefix             = local.p.commonRGNamePrefix
  env                               = local.p.env
  location_suffix                   = local.p.locationSuffix
  subscription_id_dev_test_prod     = local.sub
  vnet_name                         = local.vnet_name_full
  vnet_name_base                    = local.p.vnetNameBase
  network_env                       = local.p.network_env
  vnet_name_full_param              = local.p.vnetNameFull_param
  vnet_resource_group_param         = local.p.vnetResourceGroup_param
  central_dns_zone_by_policy_in_hub = local.p.centralDnsZoneByPolicyInHub
  cidr_apim                         = local.ai_gateway_apim_cidr_v
  cidr_function_app                 = local.ai_gateway_app_cidr_v
  resource_group_name               = local.vnet_resource_group_name

  # Bicep: dependsOn vNetCommon only when no vNet is brought (empty(vnetNameFull_param)).
  depends_on = [module.vNetCommon]
}
