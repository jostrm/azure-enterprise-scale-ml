# Port of environment_setup/aifactory/bicep/modules/vmSecurityExtensions.bicep
# Defender for Cloud VM extensions for one existing Trusted Launch VM:
# - Guest Attestation (Microsoft.Azure.Security.WindowsAttestation|LinuxAttestation). Needs Secure Boot + vTPM.
# - Guest Configuration (Microsoft.GuestConfiguration AzurePolicyforWindows|AzurePolicyforLinux). Uses the VM's
#   system-assigned identity.
# The two installs run one after the other: parallel extension operations on one VM can conflict.

locals {
  guest_configuration = {
    Windows = {
      name = "AzurePolicyforWindows"
      type = "ConfigurationforWindows"
    }
    Linux = {
      name = "AzurePolicyforLinux"
      type = "ConfigurationForLinux"
    }
  }

  # vm 'existing' -> ARM resource ID (no plan-time read).
  vm_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.Compute/virtualMachines/${var.vm_name}"
}

resource "azurerm_virtual_machine_extension" "guest_attestation" {
  name                       = "GuestAttestation"
  virtual_machine_id         = local.vm_id
  tags                       = var.tags
  publisher                  = var.os_type == "Windows" ? "Microsoft.Azure.Security.WindowsAttestation" : "Microsoft.Azure.Security.LinuxAttestation"
  type                       = "GuestAttestation"
  type_handler_version       = "1.0"
  auto_upgrade_minor_version = true
  automatic_upgrade_enabled  = true
  settings = jsonencode({
    AttestationConfig = {
      MaaSettings = {
        maaEndpoint   = ""
        maaTenantName = "GuestAttestation"
      }
      AscSettings = {
        ascReportingEndpoint  = ""
        ascReportingFrequency = ""
      }
      useCustomToken = "false"
      disableAlerts  = "false"
    }
  })
}

resource "azurerm_virtual_machine_extension" "guest_configuration_extension" {
  name                       = local.guest_configuration[var.os_type].name
  virtual_machine_id         = local.vm_id
  tags                       = var.tags
  publisher                  = "Microsoft.GuestConfiguration"
  type                       = local.guest_configuration[var.os_type].type
  type_handler_version       = "1.0"
  auto_upgrade_minor_version = true
  automatic_upgrade_enabled  = true
  settings                   = jsonencode({})
  protected_settings         = jsonencode({})

  depends_on = [azurerm_virtual_machine_extension.guest_attestation]
}
