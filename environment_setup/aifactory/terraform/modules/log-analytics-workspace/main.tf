# Port of environment_setup/aifactory/bicep/modules/logAnalyticsWorkspace.bicep

# Resource group scope; the Key Vault (keyvaultName) is in the same resource group (Bicep: scope: resourceGroup()).

locals {
  resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  # Bicep 'existing' keyVault -> keyVault.id, built like resourceId()
  key_vault_id = "${local.resource_group_id}/providers/Microsoft.KeyVault/vaults/${var.keyvault_name}"
}

resource "azurerm_log_analytics_workspace" "alyt" {
  name                           = var.name
  location                       = var.location
  resource_group_name            = var.resource_group_name
  tags                           = var.tags
  sku                            = var.sku
  retention_in_days              = var.log_analytics_wksp_rentation_days
  daily_quota_gb                 = -1 # workspaceCapping.dailyQuotaGb
  internet_ingestion_access_type = var.enable_ampls ? "Disabled" : "Enabled"
  internet_query_access_type     = var.enable_ampls ? "Disabled" : "Enabled"
}

# Key Vault Secret: the workspace primary shared key (Bicep: alyt.listKeys().primarySharedKey).
# azapi through the ARM control plane (exact type + API version of the Bicep): the vault is private
# (publicNetworkAccess Disabled), so a data-plane azurerm_key_vault_secret would fail from a CI runner.
resource "azapi_resource" "key_log_analytics_ws" {
  type      = "Microsoft.KeyVault/vaults/secrets@2023-07-01"
  name      = "aifactory-proj-loganalytics-workspace-key"
  parent_id = local.key_vault_id

  body = {
    properties = {
      value       = azurerm_log_analytics_workspace.alyt.primary_shared_key # sensitive
      contentType = "text/plain"
      attributes = {
        enabled = true
        exp     = var.key_vault_secret_expiry
      }
    }
  }

  # ARM never returns the secret value; do not show it as drift.
  ignore_missing_property = true
}
