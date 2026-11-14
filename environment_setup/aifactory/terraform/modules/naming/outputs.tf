output "common_resource_group_name" {
  description = "Common resource group (11-rgCommon, 13-rgLevel)."
  value       = local.common_resource_group_name
}

output "common_resource_group_name_network" {
  description = "Common resource group as 12-networkCommon computes it (ignores commonResourceGroup_param)."
  value       = local.common_resource_group_name_network
}

output "common_resource_group_id" {
  value = local.common_resource_group_id
}

output "unique_in_aif_env" {
  description = "uniqueInAIFenv: substring(uniqueString(common resource group id), 0, 5)."
  value       = local.unique_in_aif_env
}

output "vnet_resource_group_name" {
  description = "vNet resource group (13-rgLevel)."
  value       = local.vnet_resource_group_name
}

output "vnet_resource_group_name_network" {
  description = "vNet resource group (12-networkCommon)."
  value       = local.vnet_resource_group_name_network
}

output "vnet_name_full" {
  description = "vNet name (13-rgLevel)."
  value       = local.vnet_name_full
}

output "vnet_name_full_network" {
  description = "vNet name (12-networkCommon)."
  value       = local.vnet_name_full_network
}

output "vnet_id" {
  value = local.vnet_id
}

output "default_subnet" {
  value = local.default_subnet
}

output "common_subnet_scoring" {
  value = local.common_subnet_scoring
}

output "common_subnet_power_bi" {
  value = local.common_subnet_power_bi
}

output "names" {
  description = "Names of the common resources, keyed by the Bicep variable that holds them."
  value = {
    commonResourceGroupName  = local.common_resource_group_name
    uniqueInAIFenv           = local.unique_in_aif_env
    cmkIdentityName          = "id-cmn-cmk-${local.env}-${local.u}${local.sfx}"
    kvNameCommon             = local.kv_name_common
    kvNameCommonAdmin        = local.kv_name_admin
    datalakeName             = local.datalake_name
    acrCommonName            = "acrcommon${local.u}${var.location_suffix}${local.sfx}${local.env}"
    laName                   = "la-${local.cmn}-${var.location_suffix}-${local.env}-${local.u}${local.sfx}"
    adfName                  = "adf-${local.cmn}-${var.location_suffix}-${local.env}-${local.u}${local.sfx}"
    common_bastion_host_name = "bastion-${var.location_suffix}-${local.env}${local.sfx}"
    vmName                   = "dsvm-${local.cmn}-${var.location_suffix}-${local.env}${local.sfx}"
    vnetNameFull             = local.vnet_name_full
    vnetResourceGroupName    = local.vnet_resource_group_name
    vnetId                   = local.vnet_id
    defaultSubnet            = local.default_subnet
    commonSubnetScoring      = local.common_subnet_scoring
    commonSubnetPowerBI      = local.common_subnet_power_bi
    acrPrivateEndpointName   = "pend-acr-${local.cmn}${var.location_suffix}-containerreg-to-${local.vnet_abbrev}"
    kvPrivateEndpointName    = "pend-${local.kv_name_common}-to-${local.vnet_abbrev}"
    kvAdminPrivateEndpoint   = "pend-${local.kv_name_admin}-to-${local.vnet_abbrev}"
    lakeBlobPrivateEndpoint  = "pend-${local.datalake_name}-blob-to-${local.vnet_abbrev}"
    lakeFilePrivateEndpoint  = "pend-${local.datalake_name}-file-to-${local.vnet_abbrev}"
    lakeDfsPrivateEndpoint   = "pend-${local.datalake_name}-dfs-to-${local.vnet_abbrev}"
    lakeQueuePrivateEndpoint = "pend-${local.datalake_name}-queue-to-${local.vnet_abbrev}"
    lakeTablePrivateEndpoint = "pend-${local.datalake_name}-table-to-${local.vnet_abbrev}"
    adfPortalPrivateEndpoint = "pend-${local.cmn}-${local.env}-${local.u}-adfportal-to-${local.vnet_abbrev}"
    adfRuntimePrivateEndpnt  = "pend-${local.cmn}-${local.env}-${local.u}-adfruntime-to-${local.vnet_abbrev}"
  }
}
