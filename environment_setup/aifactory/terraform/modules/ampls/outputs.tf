output "ampls_id" {
  description = "Resource ID of the AMPLS."
  value       = azapi_resource.ampls.id
}

output "ampls_name" {
  description = "Name of the AMPLS."
  value       = azapi_resource.ampls.name
}

output "ampls_resource_id" {
  description = "Resource ID of the AMPLS."
  value       = azapi_resource.ampls.id
}

output "ingestion_access_mode" {
  description = "properties.accessModeSettings.ingestionAccessMode"
  value       = azapi_resource.ampls.output.properties.accessModeSettings.ingestionAccessMode
}

output "query_access_mode" {
  description = "properties.accessModeSettings.queryAccessMode"
  value       = azapi_resource.ampls.output.properties.accessModeSettings.queryAccessMode
}
