output "diagnostic_setting_id" {
  description = "Diagnostic setting resource ID"
  value       = azurerm_monitor_diagnostic_setting.key_vault_diagnostics.id
}
