variable "subscription_id" {
  description = "Subscription ID of the deployment (resource group and vnet resource group)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group the Key Vault is deployed to (the Bicep module's scope)."
  type        = string
}

variable "keyvault_name" {
  description = "(Required) Specifies the name of the keyvault that is created"
  type        = string
}

variable "tags" {
  description = "(Required) Specifies the tags that will be associated with keyvault resources"
  type        = map(string)
}

variable "tenant_identity" {
  description = "(Required) Specifies the tenant which the keyvault belongs to"
  type        = string
}

variable "keyvault_network_policy_subnets" {
  description = "(Optional) Subnet resource IDs allowed in the vault firewall (ignoreMissingVnetServiceEndpoint = true)"
  type        = list(string)
  default     = []
}

variable "subnet_name" {
  description = "(Required) Specifies the subnet name that will be associated with the private endpoint"
  type        = string
}

variable "private_endpoint_name" {
  description = "(Required) Specifies the private endpoint name"
  type        = string
}

variable "ip_rules" {
  description = "(Optional) Specifies an array of objects containing ip rules, e.g. [{ action = \"Allow\", value = \"1.2.3.4\" }] (sent as-is)"
  type        = list(map(string))
  default     = []
}

variable "secrets" {
  description = "(Optional) Secrets to create in the Key Vault: objects { name, value, contentType (optional, default 'text/plain'), attributes (optional object, shallow-merged over { enabled = true, exp = key_vault_secret_expiry }) }."
  type        = any
  default     = []
  sensitive   = true
}

variable "soft_delete_days" {
  description = "(Optional) Specifies number of days to keep keyvault if deleted. Retention: 7-30 days. ESML defaults to 7 days"
  type        = number
  default     = 7
}

variable "enable_purge_protection" {
  description = "(Optional) Enable purge protection. softDeleteRetentionInDays is only sent when true."
  type        = bool
  default     = true
}

variable "location" {
  description = "Location"
  type        = string
}

variable "enable_public_access_with_perimeter" {
  type    = bool
  default = false
}

variable "enable_public_gen_ai_access" {
  type    = bool
  default = false
}

variable "allow_public_access_when_behind_vnet" {
  type    = bool
  default = false
}

variable "vnet_name" {
  description = "Virtual network of the private endpoint subnet."
  type        = string
}

variable "vnet_resource_group_name" {
  description = "Resource group of the virtual network."
  type        = string
}

variable "key_vault_secret_expiry" {
  description = "Expiry of every secret this module creates, in Unix epoch seconds (Bicep default: utcNow() + P1Y; computed by the stage)."
  type        = number
}
