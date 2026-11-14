output "ampls" {
  description = "Azure Monitor Private Link Scope information"
  value = {
    id                  = module.azure_monitor_private_link_scope.ampls_id
    name                = module.azure_monitor_private_link_scope.ampls_name
    resourceId          = module.azure_monitor_private_link_scope.ampls_resource_id
    ingestionAccessMode = module.azure_monitor_private_link_scope.ingestion_access_mode
    queryAccessMode     = module.azure_monitor_private_link_scope.query_access_mode
  }
}

output "data_collection_endpoint" {
  description = "Data Collection Endpoint information"
  value = {
    id                       = module.data_collection_endpoint.dce_id
    name                     = module.data_collection_endpoint.dce_name
    resourceId               = module.data_collection_endpoint.dce_resource_id
    logsIngestionEndpoint    = module.data_collection_endpoint.logs_ingestion_endpoint
    metricsIngestionEndpoint = module.data_collection_endpoint.metrics_ingestion_endpoint
  }
}

output "private_endpoint" {
  description = "Private Endpoint information"
  value = {
    id          = module.ampls_private_endpoint.private_endpoint_id
    name        = module.ampls_private_endpoint.private_endpoint_name
    ipAddresses = module.ampls_private_endpoint.private_endpoint_ip_addresses
  }
}

output "deployment_complete" {
  description = "AMPLS deployment completed successfully"
  value       = true
}
