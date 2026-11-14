output "storage_account_id" {
  value = azapi_resource.lake.id
}

output "virtual_network_rules" {
  description = "lake.properties.networkAcls.virtualNetworkRules as returned by ARM."
  value       = try(azapi_resource.lake.output.properties.networkAcls.virtualNetworkRules, [])
}

output "dns_config" {
  value = [
    {
      name = azurerm_private_endpoint.pend_sacc["blob"].name
      type = "blob"
      id   = azapi_resource.lake.id
    },
    {
      name = var.file_private_endpoint_name
      type = "file"
      id   = azapi_resource.lake.id
    },
    {
      name = var.dfs_private_endpoint_name
      type = "dfs"
      id   = azapi_resource.lake.id
    },
    {
      name = var.queue_private_endpoint_name
      type = "queue"
      id   = azapi_resource.lake.id
    },
    {
      name = var.table_private_endpoint_name
      type = "table"
      id   = azapi_resource.lake.id
    },
  ]
}
