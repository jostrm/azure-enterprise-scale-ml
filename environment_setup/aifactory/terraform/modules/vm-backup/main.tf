# Port of environment_setup/aifactory/bicep/modules/vmBackup.bicep
# Opt-in Azure Backup for one existing VM (enableVmBackup, default false). Creates the Recovery Services vault and
# its daily policy, then protects the VM. Trusted Launch VMs can only be protected by an Enhanced (V2) policy, so the
# policy is V2. Soft delete stays at the platform default (enabled).

locals {
  vault_name = coalesce(var.vault_name, "rsv-${var.vm_name}")

  # vm 'existing' -> ARM resource ID (no plan-time read).
  vm_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.Compute/virtualMachines/${var.vm_name}"
}

resource "azurerm_recovery_services_vault" "vault" {
  name                = local.vault_name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
  sku                 = "RS0" # sku { name: 'RS0', tier: 'Standard' }
  # properties: {} -> platform defaults (no soft delete / storage / public access overrides here).
}

resource "azurerm_backup_policy_vm" "policy" {
  name                           = var.policy_name
  resource_group_name            = var.resource_group_name
  recovery_vault_name            = azurerm_recovery_services_vault.vault.name
  policy_type                    = "V2" # backupManagementType AzureIaasVM, SimpleSchedulePolicyV2
  instant_restore_retention_days = 7
  timezone                       = "UTC"

  backup {
    frequency = "Daily"
    time      = var.backup_time_utc # Bicep scheduleRunTimes '2026-01-01T<time>:00Z' (only the time is used)
  }

  # LongTermRetentionPolicy, dailySchedule at the same time, retentionDuration Days
  retention_daily {
    count = var.retention_days
  }
}

# Protected item 'Azure/iaasvmcontainer;iaasvmcontainerv2;<rg>;<vm>/vm;iaasvmcontainerv2;<rg>;<vm>': azurerm builds
# the same container and item names from the VM ID.
resource "azurerm_backup_protected_vm" "protected_item" {
  resource_group_name = var.resource_group_name
  recovery_vault_name = azurerm_recovery_services_vault.vault.name
  source_vm_id        = local.vm_id
  backup_policy_id    = azurerm_backup_policy_vm.policy.id
}
