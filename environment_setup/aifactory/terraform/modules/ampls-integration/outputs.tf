output "ampls_info" {
  description = "AMPLS deployment information"
  value       = module.ampls_deployment.ampls
}

output "dce_info" {
  description = "Data Collection Endpoint information"
  value       = module.ampls_deployment.data_collection_endpoint
}

output "private_endpoint_info" {
  description = "Private Endpoint information"
  value       = module.ampls_deployment.private_endpoint
}

output "ampls_resource_group" {
  description = "AMPLS Resource Group"
  value       = local.target_resource_group
}

output "ampls_subscription" {
  description = "AMPLS Subscription"
  value       = local.target_subscription
}

output "integration_complete" {
  description = "AMPLS integration completed"
  value       = module.ampls_deployment.deployment_complete
}
