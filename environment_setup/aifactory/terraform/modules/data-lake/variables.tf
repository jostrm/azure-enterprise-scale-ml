variable "subscription_id" {
  description = "Subscription ID of the deployment (resource group and vnet resource group)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group the storage account is deployed to (the Bicep module's scope)."
  type        = string
}

variable "virtual_network_rules" {
  description = "Array of merged virtualNetworkRules, subnets, to allow in the storage accounts firewall. Not used by the Bicep body (kept for parity)."
  type        = any
  default     = []
}

variable "container_name" {
  description = "Specifies the containerName of the datalake gen2 storage. Not used by the Bicep body (containers is used); kept for parity."
  type        = string
  default     = ""
}

variable "storage_account_name" {
  description = "Specifies the name of the storage"
  type        = string
  validation {
    condition     = length(var.storage_account_name) >= 3 && length(var.storage_account_name) <= 24
    error_message = "storage_account_name must be 3-24 characters."
  }
}

variable "sku_name" {
  description = "Specifies the SKU of the storage account"
  type        = string
  validation {
    condition     = contains(["Standard_LRS", "Standard_GRS", "Standard_ZRS", "Premium_LRS", "Premium_ZRS", "Standard_GZRS", "Standard_RAGRS", "Standard_RAGZRS"], var.sku_name)
    error_message = "sku_name must be one of: Standard_LRS, Standard_GRS, Standard_ZRS, Premium_LRS, Premium_ZRS, Standard_GZRS, Standard_RAGRS, Standard_RAGZRS."
  }
}

variable "location" {
  type = string
}

variable "subnet_name" {
  description = "Specifies the name of the subnet used for the private endpoints"
  type        = string
}

variable "blob_private_endpoint_name" {
  description = "Specifies name of the blob private endpoint"
  type        = string
}

variable "file_private_endpoint_name" {
  description = "Specifies the name of the file service private endpoint"
  type        = string
}

variable "dfs_private_endpoint_name" {
  description = "Specifies the name of the dfs service private endpoint"
  type        = string
}

variable "queue_private_endpoint_name" {
  description = "Specifies the name of the queue service private endpoint"
  type        = string
}

variable "table_private_endpoint_name" {
  description = "Specifies the name of the table service private endpoint"
  type        = string
}

variable "tags" {
  description = "Specifies the tags that should be applied to the storage account resources"
  type        = map(string)
}

variable "key_expiration_period_in_days" {
  description = "Access keys will automatically be rotated in X days."
  type        = number
  default     = 14
}

variable "delete_retention_policy" {
  description = "Amount of days the soft deleted data is stored and available for recovery"
  type        = number
  default     = 7
  validation {
    condition     = var.delete_retention_policy >= 1 && var.delete_retention_policy <= 365
    error_message = "delete_retention_policy must be between 1 and 365."
  }
}

variable "delete_retention_policy_enabled" {
  description = "If soft delete on blobs should be enabled. Not used by the Bicep body (it always sends enabled: true); kept for parity."
  type        = bool
  default     = true
}

variable "encryption_enabled" {
  description = "Enable blob encryption at rest. Not used by the Bicep body; kept for parity."
  type        = bool
  default     = true
}

variable "ip_whitelist_array" {
  description = "IP addresses / CIDRs allowed in the storage firewall."
  type        = list(string)
  default     = []
}

variable "virtual_network_rules_array" {
  description = "Subnet resource IDs allowed in the storage firewall."
  type        = list(string)
  default     = []
}

variable "containers" {
  description = "Blob containers to create (blobServices is only deployed when non-empty)."
  type        = list(string)
  default     = ["lake3"]
}

variable "files" {
  description = "fileServices is only deployed when non-empty (the entries themselves are not used by the Bicep)."
  type        = list(any)
  default     = []
}

variable "vnet_name" {
  type = string
}

variable "vnet_resource_group_name" {
  type = string
}

variable "cors_rules" {
  description = "CORS rules of the blob and file services (ARM shape, sent as-is)."
  type = list(object({
    allowedOrigins  = list(string)
    allowedMethods  = list(string)
    maxAgeInSeconds = number
    exposedHeaders  = list(string)
    allowedHeaders  = list(string)
  }))
  default = [
    {
      allowedOrigins = [
        "https://mlworkspace.azure.ai",
        "https://ml.azure.com",
        "https://*.ml.azure.com",
        "https://ai.azure.com",
        "https://*.ai.azure.com",
        "https://mlworkspacecanary.azure.ai",
        "https://mlworkspace.azureml-test.net",
      ]
      allowedMethods = [
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "DELETE",
        "OPTIONS",
        "PATCH",
      ]
      maxAgeInSeconds = 1800
      exposedHeaders  = ["*"]
      allowedHeaders  = ["*"]
    }
  ]
}

# CMK
variable "cmk" {
  type    = bool
  default = false
}

variable "cmk_identity_id" {
  type    = string
  default = ""
}

variable "cmk_key_name" {
  type    = string
  default = ""
}

variable "cmk_key_vault_uri" {
  type    = string
  default = ""
}
