variable "subscription_id" {
  description = "Subscription of the Key Vault (subscriptionResourceId() of the role definition uses it too)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the Key Vault (the Bicep module's scope)."
  type        = string
}

variable "key_vault_resource_name" {
  description = "Name of the Key Vault resource ex. kv-myservice."
  type        = string
}

variable "principal_id" {
  description = "Object ID of the main principal (Managed Identity, Service Principal or user). Empty, placeholder (<todo>, <optional>_ObjectID) and other non-GUID values are skipped."
  type        = string
  sensitive   = true
}

variable "additional_principal_ids" {
  description = "Optional additional object IDs that get the same role. Non-GUID values are skipped."
  type        = list(string)
}

variable "key_vault_role" {
  description = "Built-in Key Vault data role, by name in common/keyVaultDefaults.json."
  type        = string
  validation {
    condition     = contains(["secretsUser", "secretsOfficer", "cryptoUser", "cryptoServiceEncryptionUser", "certificatesOfficer", "administrator"], var.key_vault_role)
    error_message = "key_vault_role must be one of: secretsUser, secretsOfficer, cryptoUser, cryptoServiceEncryptionUser, certificatesOfficer, administrator."
  }
}

variable "principal_type" {
  description = "Principal type of every principal. Empty lets Azure resolve it, for lists that mix users and groups."
  type        = string
  default     = ""
  validation {
    condition     = contains(["", "User", "Group", "ServicePrincipal"], var.principal_type)
    error_message = "principal_type must be one of: '', User, Group, ServicePrincipal."
  }
}

variable "principal_is_managed_identity" {
  description = "Terraform only: principal_id is a managed identity's object id (always a GUID) that may be unknown until apply. It is then assigned without the GUID filter, so for_each keys stay known at plan time."
  type        = bool
  default     = false
}
