variable "subscription_id" {
  description = "Subscription of the resource group (the Bicep module scope)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the VM, its NIC, the admin Key Vault and the backup vault (the Bicep module scope)."
  type        = string
}

variable "kv_secret_name_suffix" {
  description = "default is -001 such as esml-dsvm-username-001 as secret name in keyvault Ex: creating multipe VM -001, -002,-003"
  type        = string
  default     = "-001"
}

variable "admin_password" {
  description = "Specifies a secure string used as password new local admin user"
  type        = string
  sensitive   = true
}

variable "admin_username" {
  description = "Specifies the name of the local admin user"
  type        = string
}

variable "vm_size" {
  description = "Size of the virtual machine. Must support Generation 2, Trusted Launch and (unless enable_encryption_at_host is false) encryption at host."
  type        = string
  default     = "Standard_D2s_v5"
}

variable "location" {
  description = "location for all resources"
  type        = string
}

variable "vm_name" {
  description = "Specifies the name of the virtual machine"
  type        = string
}

variable "subnet_name" {
  description = "Specifies the subnet that the virtual machine should be connected to"
  type        = string
}

variable "vnet_id" {
  description = "Specift the virtual network id used for network interface"
  type        = string
}

variable "tags" {
  description = "The tags that should be applied on virtual machine resources"
  type        = map(string)
}

variable "keyvault_name" {
  description = "(Required) speficies the keyvault (in this resource group) used to save local admin credentials"
  type        = string
}

variable "hybrid_benefit" {
  description = "(Required) true if Hybrid benefits for Windows server VMs, else FALSE for Pay-as-you-go"
  type        = bool
  default     = true
}

variable "expiration_date_default_2025_01_10_epoch" {
  description = "default keyvault secret expiration date in inteter, EPOC, seconds after 1970"
  type        = number
  default     = 1736467877
}

variable "os_disk_type" {
  description = "default StandardSSD_LRS as demo mode, recommended for production purpose is to upgrade to Premium_LRS. Never HDD (Standard_LRS)."
  type        = string
  default     = "StandardSSD_LRS"

  validation {
    condition     = contains(["StandardSSD_LRS", "StandardSSD_ZRS", "Premium_LRS", "Premium_ZRS"], var.os_disk_type)
    error_message = "os_disk_type must be one of: StandardSSD_LRS, StandardSSD_ZRS, Premium_LRS, Premium_ZRS."
  }
}

variable "extra_disk_type" {
  description = "default StandardSSD_LRS as demo mode, recommended is to upgrade to Premium_LRS for productional purpose. Never HDD (Standard_LRS)."
  type        = string
  default     = "StandardSSD_LRS"

  validation {
    condition     = contains(["StandardSSD_LRS", "StandardSSD_ZRS", "Premium_LRS", "Premium_ZRS"], var.extra_disk_type)
    error_message = "extra_disk_type must be one of: StandardSSD_LRS, StandardSSD_ZRS, Premium_LRS, Premium_ZRS."
  }
}

variable "extra_disk_size_gb" {
  description = "default is 128GB, change to bigger, 1024, GB if much local data"
  type        = number
  default     = 128
}

variable "enable_encryption_at_host" {
  description = "Defender for Cloud: encrypt temp disk and caches on the host. Needs the subscription feature Microsoft.Compute/EncryptionAtHost (the bootstrap registers it). Set false to opt out."
  type        = bool
  default     = true
}

variable "vm_exists" {
  description = "true when this VM already exists outside this Terraform state (pipelines detect it with scripts/admin-vm-exists.sh). An existing VM is never PUT again: image, Trusted Launch and encryption at host cannot change in place (Gen1 DSVMs must be recreated), and the local admin password is not rotated. Only opt-in backup is applied. Do not set it to true for a VM this state created: that would plan its destroy (a VM this state created is never updated anyway, see lifecycle)."
  type        = bool
  default     = false
}

variable "enable_vm_backup" {
  description = "Opt-in Azure Backup: Recovery Services vault + daily Enhanced policy, protecting this VM."
  type        = bool
  default     = false
}

variable "backup_vault_name" {
  description = "Recovery Services vault used when enable_vm_backup is true. null = 'rsv-<vm_name>' (the Bicep default)."
  type        = string
  default     = null
}
