variable "subscription_id" {
  description = "Subscription of the common Key Vault (subscription().subscriptionId); also the esml-subscription-id secret value."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the common Key Vault (the Bicep module scope)."
  type        = string
}

variable "keyvault_name" {
  description = "Common KEYVAULT for ESML coreteam."
  type        = string
}

variable "esml_common_sp_id" {
  description = "Secret name of App ID for service principle."
  type        = string
  default     = "esml-common-sp-id"
}

variable "esml_common_sp_id_secret" {
  description = "Value of service principle ID (Bicep @secure(); from the seeding Key Vault, never stored in state)."
  type        = string
  sensitive   = true
  ephemeral   = true
}

variable "esml_common_sp_oid" {
  description = "Secret name of OBJECT ID for service principle."
  type        = string
  default     = "esml-common-sp-oid"
}

variable "esml_common_sp_oid_value" {
  description = "Value of service principle OBJECT ID (Bicep @secure())."
  type        = string
  sensitive   = true
  ephemeral   = true
}

variable "esml_common_sp_secret" {
  description = "Secret name of the service principle secret."
  type        = string
  default     = "esml-common-sp-secret"
}

variable "esml_common_sp_secret_value" {
  description = "Value of service principle secret (Bicep @secure())."
  type        = string
  sensitive   = true
  ephemeral   = true
}

variable "esml_tenant_id" {
  description = "Secret name of the Tenant ID."
  type        = string
  default     = "esml-tenant-id"
}

variable "esml_tenant_id_secret" {
  description = "Secret value of Tenant ID (Bicep default: subscription().tenantId)."
  type        = string
}

variable "esml_subscription_id" {
  description = "Secret name of the Subscription ID of the current ESML environment."
  type        = string
  default     = "esml-subscription-id"
}

variable "key_vault_secret_expiry" {
  description = "Expiry of every secret this module writes, in Unix epoch seconds (Bicep default utcNow() + 1 year)."
  type        = number
}
