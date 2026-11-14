# Port of environment_setup/aifactory/bicep/modules/virtualMachinePrivate.bicep
# Port of environment_setup/aifactory/bicep/modules/common/vmSecurity.bicep (exported variables only -> locals below)

locals {
  # ---- modules/common/vmSecurity.bicep (Defender for Cloud compute baseline; only exported vars, no resources) ----
  # Windows Server 2022 Datacenter Azure Edition. Generation 2, Trusted Launch capable. Replaces the Gen1-only DSVM image.
  windows_gen2_image = {
    publisher = "MicrosoftWindowsServer"
    offer     = "WindowsServer"
    sku       = "2022-datacenter-azure-edition"
    version   = "latest"
  }
  # Trusted Launch security profile without encryptionAtHost; merged with { encryptionAtHost = <bool> }.
  trusted_launch = {
    securityType = "TrustedLaunch"
    uefiSettings = {
      secureBootEnabled = true
      vTpmEnabled       = true
    }
  }
  # Windows Update installs patches as before; the platform assesses missing updates every 24 hours.
  windows_patch_settings = {
    enableHotpatching = false
    patchMode         = "AutomaticByOS"
    assessmentMode    = "AutomaticByPlatform"
  }
  # (linuxGen2Image and linuxPatchSettings are not imported by virtualMachinePrivate.bicep.)
  # ------------------------------------------------------------------------------------------------------------------

  nic_name   = "${var.vm_name}-nic-${substr(module.unique_vm_name.value, 0, 5)}"
  subnet_ref = "${var.vnet_id}/subnets/${var.subnet_name}"

  resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  vm_resource_id    = "${local.resource_group_id}/providers/Microsoft.Compute/virtualMachines/${var.vm_name}"
  keyvault_id       = "${local.resource_group_id}/providers/Microsoft.KeyVault/vaults/${var.keyvault_name}"
  backup_vault_name = coalesce(var.backup_vault_name, "rsv-${var.vm_name}")

  esml_project_kv_name_user = "esml-dsvm-username${var.kv_secret_name_suffix}"
  esml_project_kv_name_pwd  = "esml-dsvm-password${var.kv_secret_name_suffix}"
}

# uniqueString(vmName)
module "unique_vm_name" {
  source = "../arm-unique-string"
  values = [var.vm_name]
}

# vmExists behaviour: everything below except backup has count = vm_exists ? 0 : 1, and the VM, its NIC and the two
# Key Vault secrets ignore all changes once created, so an existing VM is never PUT again and its password is never
# rotated (Bicep: pipelines pass vmExists = true for an existing VM).
resource "azurerm_network_interface" "n_inter" {
  count               = var.vm_exists ? 0 : 1
  name                = local.nic_name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  ip_configuration {
    name                          = "ipconfig1"
    private_ip_address_allocation = "Dynamic"
    subnet_id                     = local.subnet_ref
  }

  lifecycle {
    ignore_changes = all
  }
}

# azapi: azurerm_windows_virtual_machine cannot create the inline Empty data disk (lun 0) in the VM PUT (it needs a
# separate managed disk + attachment), and requires os_disk caching, which the Bicep leaves to the platform.
resource "azapi_resource" "virtual_machine" {
  count     = var.vm_exists ? 0 : 1
  type      = "Microsoft.Compute/virtualMachines@2024-07-01"
  name      = var.vm_name
  parent_id = local.resource_group_id
  location  = var.location
  tags      = var.tags

  identity {
    type = "SystemAssigned"
  }

  body = {
    properties = {
      hardwareProfile = {
        vmSize = var.vm_size
      }
      licenseType = var.hybrid_benefit == true ? "Windows_Server" : "None" # HB='Windows_Server' & "pay as you go"='None'
      osProfile = {
        computerName  = substr(var.vm_name, 0, 14) # No more than 15 chars are allowed for this field
        adminUsername = var.admin_username
        windowsConfiguration = {
          enableAutomaticUpdates = true
          provisionVMAgent       = true
          patchSettings          = local.windows_patch_settings
        }
      }
      securityProfile = merge(local.trusted_launch, {
        encryptionAtHost = var.enable_encryption_at_host
      })
      storageProfile = {
        # Gen2 + Trusted Launch. The former microsoft-dsvm dsvm-win-2022:winserver-2022 image is Gen1 only.
        imageReference = local.windows_gen2_image
        osDisk = {
          createOption = "FromImage"
          diskSizeGB   = 256
          managedDisk = {
            storageAccountType = var.os_disk_type
          }
        }
        dataDisks = [
          {
            diskSizeGB = var.extra_disk_size_gb
            managedDisk = {
              storageAccountType = var.extra_disk_type
            }
            lun          = 0
            createOption = "Empty"
          }
        ]
      }
      networkProfile = {
        networkInterfaces = [
          {
            id = azurerm_network_interface.n_inter[0].id
          }
        ]
      }
      diagnosticsProfile = {
        bootDiagnostics = {
          enabled = true
        }
      }
    }
  }

  # adminPassword is write-only (never stored in state), merged into the PUT body.
  sensitive_body = {
    properties = {
      osProfile = {
        adminPassword = var.admin_password
      }
    }
  }

  lifecycle {
    ignore_changes = all
  }
}

resource "azurerm_virtual_machine_extension" "ext_aad_login" {
  count                      = var.vm_exists ? 0 : 1
  name                       = "AADLoginForWindows"
  virtual_machine_id         = azapi_resource.virtual_machine[0].id
  publisher                  = "Microsoft.Azure.ActiveDirectory"
  type                       = "AADLoginForWindows"
  type_handler_version       = "1.0"
  auto_upgrade_minor_version = true
}

module "security_extensions" {
  source              = "../vm-security-extensions"
  count               = var.vm_exists ? 0 : 1
  subscription_id     = var.subscription_id
  resource_group_name = var.resource_group_name
  vm_name             = azapi_resource.virtual_machine[0].name
  location            = var.location
  os_type             = "Windows"
  tags                = var.tags

  depends_on = [azurerm_virtual_machine_extension.ext_aad_login]
}

module "backup" {
  source              = "../vm-backup"
  count               = var.enable_vm_backup ? 1 : 0
  subscription_id     = var.subscription_id
  resource_group_name = var.resource_group_name
  vm_name             = var.vm_name
  location            = var.location
  tags                = var.tags
  vault_name          = local.backup_vault_name

  depends_on = [azapi_resource.virtual_machine, module.security_extensions]
}

# Microsoft.DevTestLab/schedules 'shutdown-computevm-<vm>': azurerm names the schedule exactly so.
resource "azurerm_dev_test_global_vm_shutdown_schedule" "automatic_shutdown" {
  count                 = var.vm_exists ? 0 : 1
  virtual_machine_id    = azapi_resource.virtual_machine[0].id
  location              = var.location
  tags                  = var.tags
  enabled               = true # status: 'Enabled', taskType: 'ComputeVmShutdownTask'
  daily_recurrence_time = "0330"
  timezone              = "W. Europe Standard Time"

  # Required by azurerm; the Bicep sets no notificationSettings (platform default: disabled).
  notification_settings {
    enabled = false
  }
}

# Written only with a new VM: on an existing VM the password in Key Vault stays the one the VM uses.
# azapi: control-plane write of Microsoft.KeyVault/vaults/secrets (works behind a private vault); azurerm_key_vault_secret
# writes through the data plane.
resource "azapi_resource" "keyvault_admin_username_secret" {
  count     = var.vm_exists ? 0 : 1
  type      = "Microsoft.KeyVault/vaults/secrets@2019-09-01"
  name      = local.esml_project_kv_name_user
  parent_id = local.keyvault_id
  body = {
    properties = {
      value       = var.admin_username
      contentType = "ESML generated local admin"
      attributes = {
        enabled = true
        exp     = var.expiration_date_default_2025_01_10_epoch
      }
    }
  }

  lifecycle {
    ignore_changes = all
  }
}

resource "azapi_resource" "keyvault_admin_password_secret" {
  count     = var.vm_exists ? 0 : 1
  type      = "Microsoft.KeyVault/vaults/secrets@2019-09-01"
  name      = local.esml_project_kv_name_pwd
  parent_id = local.keyvault_id
  body = {
    properties = {
      contentType = "ESML generated local admin password for username ${var.admin_username} on VM"
      attributes = {
        enabled = true
        exp     = var.expiration_date_default_2025_01_10_epoch
      }
    }
  }

  # The secret value is write-only (never stored in state), merged into the PUT body.
  sensitive_body = {
    properties = {
      value = var.admin_password
    }
  }

  lifecycle {
    ignore_changes = all
  }
}
