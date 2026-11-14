variable "subscription_id" {
  description = "Subscription ID of the deployment (resource group and vnet resource group)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group the registry is deployed to (the Bicep module's scope)."
  type        = string
}

variable "sku_name" {
  description = "(Optional) Specifies the Azure container registry service tier name, defaults to premium because of the private endpoints association. NB! Basic and Standard ACR SKUs don't support private endpoints."
  type        = string
  default     = "Premium"
  validation {
    condition     = contains(["Premium", "Standard", "Basic"], var.sku_name)
    error_message = "sku_name must be one of: Premium, Standard, Basic."
  }
}

variable "container_registry_name" {
  description = "(Required) Specifies the name of the Azure container registry that will be deployed ('-' are removed)"
  type        = string
}

variable "subnet_name" {
  description = "(Required) Specifies the subnet name that will be associated with the private endpoint"
  type        = string
}

variable "private_endpoint_name" {
  description = "(Required) Specifies the private endpoint name"
  type        = string
}

variable "tags" {
  description = "(Required) Specifies the tags that will be associated with azure container registry resources"
  type        = map(string)
}

variable "location" {
  type = string
}

variable "vnet_name" {
  type = string
}

variable "vnet_resource_group_name" {
  type = string
}

variable "enable_public_access_with_perimeter" {
  type    = bool
  default = false
}

variable "allow_public_access_when_behind_vnet" {
  type    = bool
  default = false
}

variable "admin_user_enabled" {
  type    = bool
  default = false
}

variable "dedicated_data_point" {
  description = "dataEndpointEnabled"
  type        = bool
  default     = true
}

variable "zone_redundancy" {
  type    = string
  default = "Disabled"
}

variable "ip_rules" {
  description = "IP rules { action, value }; single IPs get /32."
  type = list(object({
    action = string
    value  = string
  }))
  default = []
}

variable "existing_ip_rules" {
  description = "Existing IP rules { action, value }, merged with ip_rules."
  type = list(object({
    action = string
    value  = string
  }))
  default = []
}

variable "export_enabled" {
  description = "exportPolicy status: 'enabled' or 'disabled'"
  type        = string
  default     = "enabled"
}

variable "retention_days" {
  description = "retentionPolicy days"
  type        = number
  default     = 7
}

variable "managed_identities" {
  description = "Optional. The managed identity definition for this resource (AVM managedIdentityAllType: systemAssigned, userAssignedResourceIds). null = not provided."
  type = object({
    system_assigned            = optional(bool)
    user_assigned_resource_ids = optional(list(string))
  })
  default = null
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

variable "cmk_identity_client_id" {
  type    = string
  default = ""
}

variable "cmk_key_name" {
  type    = string
  default = ""
}

variable "cmk_key_vault_uri" {
  description = "Vault URI with trailing '/', e.g. https://kv.vault.azure.net/ (keyIdentifier = '<uri>keys/<name>')."
  type        = string
  default     = ""
}
