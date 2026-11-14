output "dce_id" {
  description = "Resource ID of the Data Collection Endpoint."
  value       = azurerm_monitor_data_collection_endpoint.data_collection_endpoint.id
}

output "dce_name" {
  description = "Name of the Data Collection Endpoint."
  value       = azurerm_monitor_data_collection_endpoint.data_collection_endpoint.name
}

output "dce_resource_id" {
  description = "Resource ID of the Data Collection Endpoint."
  value       = azurerm_monitor_data_collection_endpoint.data_collection_endpoint.id
}

output "logs_ingestion_endpoint" {
  description = "properties.logsIngestion.endpoint"
  value       = azurerm_monitor_data_collection_endpoint.data_collection_endpoint.logs_ingestion_endpoint
}

output "metrics_ingestion_endpoint" {
  description = "properties.metricsIngestion.endpoint"
  value       = azurerm_monitor_data_collection_endpoint.data_collection_endpoint.metrics_ingestion_endpoint
}
