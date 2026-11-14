variable "subscription_id" {
  description = "Subscription of the Key Vault (the Bicep module's scope subscription; subscriptionResourceId() of the role uses it)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the Key Vault (the Bicep module's scope)."
  type        = string
}

variable "assignment_name" {
  description = "Optional deterministic suffix. Leave empty to derive from scope + principal + role."
  type        = string
  default     = ""
}

variable "key_vault_name" {
  description = "The name of the Key Vault"
  type        = string
}

variable "principal_id" {
  description = "Principal ID (user, service principal, or managed identity)"
  type        = string
}

variable "key_vault_role_id" {
  description = "Key Vault role ID (role definition GUID) to assign"
  type        = string
}

variable "principal_type" {
  description = "Principal type"
  type        = string
  default     = "ServicePrincipal"
  validation {
    condition     = contains(["User", "Group", "ServicePrincipal"], var.principal_type)
    error_message = "principal_type must be one of: User, Group, ServicePrincipal."
  }
}

variable "role_description" {
  description = "Optional description for the role assignment"
  type        = string
  default     = ""
}
