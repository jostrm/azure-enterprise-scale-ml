output "private_endpoint_id" {
  description = "Resource ID of the private endpoint."
  value       = azurerm_private_endpoint.private_endpoint.id
}

output "private_endpoint_name" {
  description = "Name of the private endpoint."
  value       = azurerm_private_endpoint.private_endpoint.name
}

output "private_endpoint_ip_addresses" {
  description = "properties.customDnsConfigs of the private endpoint (ARM shape: fqdn, ipAddresses)."
  value = [
    for c in azurerm_private_endpoint.private_endpoint.custom_dns_configs : {
      fqdn        = c.fqdn
      ipAddresses = c.ip_addresses
    }
  ]
}
