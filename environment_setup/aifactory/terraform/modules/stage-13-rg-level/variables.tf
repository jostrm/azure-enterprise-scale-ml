variable "subscription_id" {
  description = "subscription().subscriptionId: the subscription the stage deploys into."
  type        = string
}

variable "admin_password" {
  description = "Bicep @secure() adminPassword: the admin VM's local admin password (write-only in the VM request)."
  type        = string
  sensitive   = true
  default     = null
}

variable "key_vault_secret_expiry" {
  description = "Bicep keyVaultSecretExpiry: expiry of every secret this stage writes, in Unix epoch seconds."
  type        = number
}

variable "cmk_identity" {
  description = "cmkIdentityExisting: the CMK identity 11-rgCommon created ({ id, client_id, principal_id }); null when cmk is false."
  type = object({
    id           = string
    client_id    = string
    principal_id = string
  })
  default = null
}

variable "common_sp_oid" {
  description = "externalKv.getSecret(commonServicePrincipleOIDKey) for the role assignments: an object id, not a secret."
  type        = string
  default     = ""
}

variable "common_sp_id_secret" {
  description = "externalKv.getSecret(inputCommonSPIDKey), ephemeral: copied into the common vault, never stored in state."
  type        = string
  sensitive   = true
  ephemeral   = true
  default     = null
}

variable "common_sp_secret_value" {
  description = "externalKv.getSecret(inputCommonSPSecretKey), ephemeral."
  type        = string
  sensitive   = true
  ephemeral   = true
  default     = null
}

variable "common_sp_oid_secret" {
  description = "externalKv.getSecret(commonServicePrincipleOIDKey), ephemeral (the copy written into the common vault)."
  type        = string
  sensitive   = true
  ephemeral   = true
  default     = null
}

variable "storage_suffix" {
  description = "environment().suffixes.storage."
  type        = string
  default     = "core.windows.net"
}

variable "key_vault_dns_suffix" {
  description = "environment().suffixes.keyvaultDns."
  type        = string
  default     = ".vault.azure.net"
}
