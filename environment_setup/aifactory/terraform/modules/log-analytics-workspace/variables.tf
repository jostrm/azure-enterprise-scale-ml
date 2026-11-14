variable "subscription_id" {
  description = "Subscription ID of the deployment resource group."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the workspace and of the Key Vault (the Bicep module's scope)."
  type        = string
}

variable "name" {
  description = "Specifies the name of the log analytics workspace"
  type        = string
}

variable "tags" {
  description = "Specifies a key value pair object that represents the tags applied to log analytics workspace"
  type        = map(string)
}

variable "location" {
  description = "Specifies the location of the log analytics workspace"
  type        = string
}

variable "sku" {
  description = "Service Tier: Free, Standalone, PerNode, or PerGB2018 (azurerm 5.12.0 rejects the legacy 'Free' tier)"
  type        = string
  default     = "PerGB2018"
  validation {
    condition     = contains(["Free", "Standalone", "PerNode", "PerGB2018"], var.sku)
    error_message = "sku must be one of: Free, Standalone, PerNode, PerGB2018."
  }
}

variable "keyvault_name" {
  description = "Key Vault (same resource group) that receives the secret 'aifactory-proj-loganalytics-workspace-key'."
  type        = string
}

variable "log_analytics_wksp_rentation_days" {
  description = "Number of days of retention. Free plans can only have 7 days, Standalone and Log Analytics plans include 30 days for free (azurerm 5.12.0 accepts 30-730 only)"
  type        = number
  default     = 30
  validation {
    condition     = var.log_analytics_wksp_rentation_days >= 7 && var.log_analytics_wksp_rentation_days <= 730
    error_message = "log_analytics_wksp_rentation_days must be between 7 and 730."
  }
}

variable "enable_ampls" {
  description = "true: public network access for ingestion and query is Disabled (Azure Monitor Private Link Scope)."
  type        = bool
  default     = false
}

variable "key_vault_secret_expiry" {
  description = "Expiry of the secret, in Unix epoch seconds (Bicep default: utcNow() + P1Y; computed by the stage)."
  type        = number
}
