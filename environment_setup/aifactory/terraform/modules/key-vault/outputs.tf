output "keyvault_id" {
  value = azapi_resource.key_vault.id
}

output "keyvault_name" {
  value = azapi_resource.key_vault.name
}

output "keyvault_uri" {
  value = azapi_resource.key_vault.output.properties.vaultUri
}

output "secrets_created" {
  description = "[{ name, resourceId }] in the order of var.secrets."
  value = [for name in local.secret_names : {
    name       = name
    resourceId = azapi_resource.key_vault_secrets[name].id
  }]
}

output "dns_config" {
  value = [
    {
      name = azurerm_private_endpoint.pend_keyv.name
      type = "vault"
      id   = azapi_resource.key_vault.id
    }
  ]
}
