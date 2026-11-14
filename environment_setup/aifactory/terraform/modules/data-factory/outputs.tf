output "adf_id" {
  description = "Resource ID of the Data Factory."
  value       = azurerm_data_factory.adf.id
}

output "adf_name" {
  description = "Name of the Data Factory."
  value       = azurerm_data_factory.adf.name
}

output "principal_id" {
  description = "Principal ID of the system-assigned identity (null when the factory has none)."
  value       = try(azurerm_data_factory.adf.identity[0].principal_id, null)
}

output "subnet_reference" {
  description = "Debug output to see the actual subnet reference being used"
  value       = local.subnet_ref
}

output "dns_config" {
  description = "Private endpoints for the private-dns module: { name, type, id, groupid }."
  value = [
    {
      name    = !var.enable_public_access_with_perimeter ? azurerm_private_endpoint.pend_adf["portal"].name : ""
      type    = "portal"
      id      = azurerm_data_factory.adf.id
      groupid = local.group_ids[0].gid
    },
    {
      name    = !var.enable_public_access_with_perimeter ? azurerm_private_endpoint.pend_adf["dataFactory"].name : ""
      type    = "dataFactory"
      id      = azurerm_data_factory.adf.id
      groupid = local.group_ids[1].gid
    },
  ]
}

# Managed private endpoints created on the factory's managed VNet. These are in 'Pending' state and must be approved
# on each TARGET resource, e.g.:
#   az network private-endpoint-connection approve --id <connId> --description 'Approved by pipeline'
output "managed_vnet_enabled" {
  description = "true when the managed VNet is enabled."
  value       = var.enable_managed_vnet
}

output "managed_private_endpoints" {
  description = "Managed private endpoints to approve on the targets: { name, targetResourceId, groupId }."
  value = var.enable_managed_vnet ? concat(
    var.managed_pe_key_vault_resource_id != "" ? [{ name = "mpe_keyvault", targetResourceId = var.managed_pe_key_vault_resource_id, groupId = "vault" }] : [],
    var.managed_pe_storage_resource_id != "" ? [{ name = "mpe_storage_lake", targetResourceId = var.managed_pe_storage_resource_id, groupId = "dfs" }] : [],
    var.managed_pe_cosmos_resource_id != "" ? [{ name = "mpe_cosmosdb", targetResourceId = var.managed_pe_cosmos_resource_id, groupId = "Sql" }] : [],
    (var.enable_function_linked_service && var.managed_pe_function_resource_id != "") ? [{ name = "mpe_function", targetResourceId = var.managed_pe_function_resource_id, groupId = "sites" }] : [],
  ) : []
}
