output "deploy" {
  description = "Bicep module symbol -> deployed? (the `if` of each module in 12-networkCommon.bicep)."
  value       = local.deploy
}

output "names" {
  description = "Names 12-networkCommon.bicep deploys."
  value = {
    commonResourceGroupName = module.naming.common_resource_group_name_network
    vnetResourceGroupName   = local.vnet_resource_group_name
    vnetNameFull            = local.vnet_name_full
    nsgCommon               = local.nsg_common
    nsgCommonScoring        = local.nsg_scoring
    nsgBastion              = local.nsg_bastion
    nsgPBI                  = local.nsg_pbi
    common_vnet_cidr_v      = local.common_vnet_cidr_v
    common_subnet_cidr_v    = local.common_subnet_cidr_v
  }
}
