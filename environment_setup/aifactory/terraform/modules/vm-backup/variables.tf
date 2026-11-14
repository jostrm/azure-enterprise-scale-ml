variable "subscription_id" {
  description = "Subscription of the resource group (the Bicep module scope)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the VM and the vault (resourceGroup().name of the Bicep module scope)."
  type        = string
}

variable "vm_name" {
  description = "Name of an existing VM in this resource group."
  type        = string
}

variable "location" {
  description = "Location of the vault: the VM location."
  type        = string
}

variable "tags" {
  description = "Tags for the vault."
  type        = map(string)
  default     = {}
}

variable "vault_name" {
  description = "Recovery Services vault in this resource group. null = 'rsv-<vm_name>' (the Bicep default)."
  type        = string
  default     = null
}

variable "policy_name" {
  description = "Backup policy name in the vault."
  type        = string
  default     = "aif-vm-daily-enhanced"
}

variable "backup_time_utc" {
  description = "Daily backup time (UTC, HH:mm)."
  type        = string
  default     = "01:00"
}

variable "retention_days" {
  description = "Days a daily recovery point is kept."
  type        = number
  default     = 30

  validation {
    condition     = var.retention_days >= 7 && var.retention_days <= 9999
    error_message = "retention_days must be between 7 and 9999."
  }
}
