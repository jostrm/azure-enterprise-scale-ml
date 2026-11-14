output "subnet_id" {
  description = "Resource id of the subnet."
  value       = azapi_resource.snt.id
}

output "name" {
  description = "Bicep snt.name of a resource declared as '<vnet>/<subnet>', i.e. '<virtualNetworkName>/<name>'."
  value       = "${var.virtual_network_name}/${var.name}"
}
