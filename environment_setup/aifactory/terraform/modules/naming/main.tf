# The AI Factory common naming convention, as the Bicep entry files compute it:
#   environment_setup/aifactory/bicep/esml-common/main/11-rgCommon.bicep
#   environment_setup/aifactory/bicep/esml-common/main/12-networkCommon.bicep
#   environment_setup/aifactory/bicep/esml-common/main/13-rgLevel.bicep
# One place for every name; the stage modules only read these outputs. Where the three Bicep files disagree
# (12 ignores commonResourceGroup_param and does not replace <network_env> in vnetNameFull_param), both
# variants are kept and named after the stage that uses them, so the deployed names stay identical.

locals {
  # 11-rgCommon (esmlCommonOverride) and 13-rgLevel (commonResourceName): commonResourceGroup_param wins.
  common_resource_group_name = var.common_resource_group_param != "" ? var.common_resource_group_param : "${var.common_rg_name_prefix}${var.common_resource_name}-${var.location_suffix}-${var.env}${var.aifactory_suffix_rg}"
  # 12-networkCommon: always the convention.
  common_resource_group_name_network = "${var.common_rg_name_prefix}${var.common_resource_name}-${var.location_suffix}-${var.env}${var.aifactory_suffix_rg}"

  common_resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${local.common_resource_group_name}"

  vnet_resource_group_name         = var.vnet_resource_group_param != "" ? replace(var.vnet_resource_group_param, "<network_env>", var.network_env) : local.common_resource_group_name
  vnet_resource_group_name_network = var.vnet_resource_group_param != "" ? replace(var.vnet_resource_group_param, "<network_env>", var.network_env) : local.common_resource_group_name_network

  vnet_name_full         = var.vnet_name_full_param != "" ? replace(var.vnet_name_full_param, "<network_env>", var.network_env) : "${var.vnet_name_base}-${var.location_suffix}-${var.env}${var.common_resource_suffix}"
  vnet_name_full_network = var.vnet_name_full_param != "" ? var.vnet_name_full_param : "${var.vnet_name_base}-${var.location_suffix}-${var.env}${var.common_resource_suffix}"

  vnet_id = "/subscriptions/${var.subscription_id}/resourceGroups/${local.vnet_resource_group_name}/providers/Microsoft.Network/virtualNetworks/${local.vnet_name_full}"

  # var uniqueInAIFenv = substring(uniqueString(esmlCommonResourceGroup.id), 0, 5)
  unique_in_aif_env = substr(module.unique_common_rg.value, 0, 5)

  cmn            = var.common_resource_short_name
  env            = var.env
  u              = local.unique_in_aif_env
  sfx            = var.common_resource_suffix
  vnet_abbrev    = var.vnet_name_base
  kv_name_common = "kv-${local.cmn}${local.env}-${local.u}${local.sfx}"
  kv_name_admin  = "kv-${local.cmn}adm${local.env}-${local.u}${local.sfx}"
  datalake_name  = "${var.common_lake_name_prefix_max8chars}${local.u}${var.common_resource_abbreviation}${replace(local.sfx, "-", "")}${local.env}"

  default_subnet         = var.byo_subnets ? replace(var.subnet_common, "<network_env>", var.network_env) : var.common_subnet_name
  common_subnet_scoring  = var.byo_subnets ? replace(var.subnet_common_scoring, "<network_env>", var.network_env) : "${var.common_subnet_name}-scoring"
  common_subnet_power_bi = var.byo_subnets ? replace(var.subnet_common_powerbi_gw, "<network_env>", var.network_env) : "snet-${var.common_resource_abbreviation}-${var.common_resource_short_name}-pbi-001"
}

module "unique_common_rg" {
  source = "../arm-unique-string"
  values = [local.common_resource_group_id]
}
