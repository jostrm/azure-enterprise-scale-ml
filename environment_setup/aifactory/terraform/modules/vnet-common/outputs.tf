# Outputs that work for both scenarios (virtualNetwork::subnetN.id is resourceId() of the child = built id)
output "subnet1_resource_id" {
  description = "Id of the common subnet."
  value       = local.byo ? azapi_resource.subnet1_byo[0].id : "${local.vnet_id}/subnets/${var.common_subnet_name}"
}

output "subnet2_resource_id" {
  description = "Id of the Power BI gateway subnet (Bicep: subnet2 = common_pbi_subnet_name / subnet3Byo)."
  value       = local.byo ? azapi_resource.subnet3_byo[0].id : "${local.vnet_id}/subnets/${var.common_pbi_subnet_name}"
}

output "subnet_bastion_id" {
  description = "Id of the Bastion subnet."
  value       = local.byo ? azapi_resource.subnet4_byo[0].id : "${local.vnet_id}/subnets/${var.common_bastion_subnet_name}"
}
