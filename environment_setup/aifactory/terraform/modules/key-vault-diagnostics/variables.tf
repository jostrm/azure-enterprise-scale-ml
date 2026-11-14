variable "subscription_id" {
  description = "Subscription of the Key Vault."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the Key Vault (the Bicep module's scope)."
  type        = string
}

variable "key_vault_name" {
  description = "The name of the Key Vault resource"
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "The resource ID of the Log Analytics workspace for diagnostics"
  type        = string
}

variable "diagnostic_setting_level" {
  description = "Diagnostic setting level - determines metrics and logs collected"
  type        = string
  default     = "silver"
  validation {
    condition     = contains(["gold", "silver", "bronze"], var.diagnostic_setting_level)
    error_message = "diagnostic_setting_level must be one of: gold, silver, bronze."
  }
}

variable "diagnostic_setting_name" {
  description = "Optional. Name of the diagnostic setting. null = 'diag-<key_vault_name>' (the Bicep default)."
  type        = string
  default     = null
}
