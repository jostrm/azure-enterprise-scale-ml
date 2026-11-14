output "role_assignment_completed" {
  description = "Role assignment completed successfully"
  value       = true
}

output "role_assignment_id" {
  description = "Role assignment resource ID"
  value       = azurerm_role_assignment.key_vault_role_assignment.id
}

output "key_vault_id" {
  description = "Key Vault resource ID"
  value       = local.key_vault_id
}
