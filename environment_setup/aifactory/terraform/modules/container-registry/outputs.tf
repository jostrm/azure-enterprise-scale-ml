output "container_registry_id" {
  value = azapi_resource.container_registry.id
}

output "container_registry_name" {
  value = azapi_resource.container_registry.name
}

output "registry_login_server" {
  value = azapi_resource.container_registry.output.properties.loginServer
}

output "dns_config" {
  value = local.deploy_private_endpoint ? [
    {
      name = azurerm_private_endpoint.pend_acr[0].name
      type = "registry"
      id   = azapi_resource.container_registry.id
    }
  ] : []
}
