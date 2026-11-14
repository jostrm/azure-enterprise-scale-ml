output "id" {
  description = "Resource id of the route table."
  value       = azurerm_route_table.apim_route_table.id
}

output "name" {
  description = "Name of the route table."
  value       = azurerm_route_table.apim_route_table.name
}
