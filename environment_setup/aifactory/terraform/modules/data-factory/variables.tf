variable "name" {
  description = "Specifies the name of the Azure Data Factory"
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the Data Factory (the Bicep module scope)."
  type        = string
}

variable "location" {
  description = "Location where datafacory should be deployed"
  type        = string
}

variable "tags" {
  description = "Specifies a object with key value pairs added as tags to Data Factory resource"
  type        = map(string)
}

variable "vnet_id" {
  description = "(Required) Specifies the virtual network id associated with private endpoint"
  type        = string
}

variable "subnet_name" {
  description = "(Required) Specifies the subnet name that will be associated with the private endpoint"
  type        = string

  validation {
    condition     = length(var.subnet_name) >= 1
    error_message = "subnet_name must have at least 1 character."
  }
}

variable "portal_private_endpoint_name" {
  description = "Specifies name of the portal private endpoint (the Bicep keeps it in groupIds but names the endpoint '<name>-portal-pend')."
  type        = string
}

variable "runtime_private_endpoint_name" {
  description = "Specifies the name of the runtime service private endpoint (the Bicep keeps it in groupIds but names the endpoint '<name>-dataFactory-pend')."
  type        = string
}

variable "managed_identities" {
  description = "Optional. The managed identity definition for this resource (AVM managedIdentityAllType)."
  type = object({
    system_assigned            = optional(bool, false)
    user_assigned_resource_ids = optional(list(string), [])
  })
  default = null
}

variable "enable_public_access_with_perimeter" {
  description = "true: public network access Enabled and no private endpoints."
  type        = bool
  default     = false
}

variable "cmk" {
  description = "Enable Customer Managed Keys (CMK) encryption"
  type        = bool
  default     = false
}

variable "cmk_key_name" {
  description = "Name of the Customer Managed Key in Key Vault"
  type        = string
  default     = ""
}

variable "key_vault_uri" {
  description = "URI of the Key Vault for CMK (vaultUri, e.g. https://<kv>.vault.azure.net/)"
  type        = string
  default     = ""
}

# Linked Services bootstrap (authenticated via the project User-Assigned MI). A Credential of type ManagedIdentity is
# created on the factory pointing to the project UAMI; each linked service references it via CredentialReference.
# The UAMI is also added to the factory identity so the credential is valid. The UAMI still needs data-plane RBAC on
# each target (KV/Storage/Cosmos) - handled by RBAC modules.
variable "project_uami_resource_id" {
  description = "Resource ID of the project User-Assigned Managed Identity used by Data Factory linked services. Also assigned to the factory identity. Empty = no UAMI / no linked services."
  type        = string
  default     = ""
}

variable "deploy_linked_services" {
  description = "Master switch: create Data Factory linked services (Key Vault, Storage, Cosmos DB, Function) authenticated via the project UAMI."
  type        = bool
  default     = false
}

variable "linked_service_key_vault_name" {
  description = "Key Vault name for the AzureKeyVault linked service. Empty = skip."
  type        = string
  default     = ""
}

variable "linked_service_storage_account_name" {
  description = "ADLS Gen2 / Storage account name for the AzureBlobFS linked service. Empty = skip."
  type        = string
  default     = ""
}

variable "linked_service_cosmos_db_name" {
  description = "Cosmos DB account name for the CosmosDb linked service. Empty = skip."
  type        = string
  default     = ""
}

variable "linked_service_cosmos_db_database" {
  description = "Cosmos DB database name for the CosmosDb linked service. Required (with the account name) to create the Cosmos linked service."
  type        = string
  default     = ""
}

variable "enable_function_linked_service" {
  description = "Create the AzureFunction linked service (optional)."
  type        = bool
  default     = false
}

variable "linked_service_function_app_name" {
  description = "Function App name for the AzureFunction linked service. Empty = skip."
  type        = string
  default     = ""
}

variable "linked_service_function_resource_id" {
  description = "AAD resource/audience (Application ID URI or client ID) of the Function App for MSI authentication. Required to create the Function linked service."
  type        = string
  default     = ""
}

# Managed VNet + AutoResolve managed Integration Runtime + managed private endpoints. The managed private endpoints
# land in 'Pending' and must be APPROVED on each target resource - see the managed_private_endpoints output.
variable "enable_managed_vnet" {
  description = "Create the managed VNet, AutoResolve managed Integration Runtime and managed private endpoints to the data stores."
  type        = bool
  default     = false
}

variable "managed_pe_key_vault_resource_id" {
  description = "ARM resource ID of the Key Vault to reach via a managed private endpoint (groupId vault). Empty = skip."
  type        = string
  default     = ""
}

variable "managed_pe_storage_resource_id" {
  description = "ARM resource ID of the ADLS Gen2 / Storage account to reach via a managed private endpoint (groupId dfs). Empty = skip."
  type        = string
  default     = ""
}

variable "managed_pe_cosmos_resource_id" {
  description = "ARM resource ID of the Cosmos DB account to reach via a managed private endpoint (groupId Sql). Empty = skip."
  type        = string
  default     = ""
}

variable "managed_pe_function_resource_id" {
  description = "ARM resource ID of the Function App to reach via a managed private endpoint (groupId sites). Used only when enable_function_linked_service is true. Empty = skip."
  type        = string
  default     = ""
}

variable "storage_suffix" {
  description = "environment().suffixes.storage"
  type        = string
  default     = "core.windows.net"
}

variable "key_vault_dns_suffix" {
  description = "environment().suffixes.keyvaultDns"
  type        = string
  default     = ".vault.azure.net"
}
