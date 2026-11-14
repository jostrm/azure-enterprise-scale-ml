# Port of environment_setup/aifactory/bicep/modules/diagnostics/keyVaultDiagnostics.bicep

# KEY VAULT DIAGNOSTIC SETTINGS (resource group scope), three tiers:
# - Gold: all metrics and logs (categoryGroup allLogs)
# - Silver: AllMetrics + AuditEvent
# - Bronze: AllMetrics + AuditEvent (same as silver in the Bicep)

locals {
  # Bicep 'existing' keyVault -> keyVault.id, built like resourceId()
  key_vault_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.KeyVault/vaults/${var.key_vault_name}"

  # Bicep default: 'diag-${keyVaultName}'
  diagnostic_setting_name = var.diagnostic_setting_name != null ? var.diagnostic_setting_name : "diag-${var.key_vault_name}"

  gold_metrics   = ["AllMetrics"]
  silver_metrics = ["AllMetrics"]
  bronze_metrics = ["AllMetrics"]

  gold_logs   = [{ category = null, category_group = "allLogs" }]
  silver_logs = [{ category = "AuditEvent", category_group = null }]
  bronze_logs = [{ category = "AuditEvent", category_group = null }]

  selected_metrics = var.diagnostic_setting_level == "gold" ? local.gold_metrics : var.diagnostic_setting_level == "silver" ? local.silver_metrics : local.bronze_metrics
  selected_logs    = var.diagnostic_setting_level == "gold" ? local.gold_logs : var.diagnostic_setting_level == "silver" ? local.silver_logs : local.bronze_logs
}

# Key Vault Diagnostic Settings (every entry of the Bicep has enabled: true)
resource "azurerm_monitor_diagnostic_setting" "key_vault_diagnostics" {
  name                       = local.diagnostic_setting_name
  target_resource_id         = local.key_vault_id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  dynamic "enabled_metric" {
    for_each = local.selected_metrics
    content {
      category = enabled_metric.value
    }
  }

  dynamic "enabled_log" {
    for_each = local.selected_logs
    content {
      category       = enabled_log.value.category
      category_group = enabled_log.value.category_group
    }
  }
}
