variable "ampls_name" {
  description = "Name of the Azure Monitor Private Link Scope"
  type        = string
}

variable "subscription_id" {
  description = "Subscription of the resource group (the Bicep module scope)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the AMPLS (the Bicep module scope)."
  type        = string
}

variable "location" {
  description = "Location for the AMPLS resource"
  type        = string
}

variable "tags" {
  description = "Tags to apply to the AMPLS resource"
  type        = map(string)
  default     = {}
}

variable "ingestion_access_mode" {
  description = "Access mode for ingestion - controls how data can be ingested"
  type        = string
  default     = "PrivateOnly"

  validation {
    condition     = contains(["Open", "PrivateOnly"], var.ingestion_access_mode)
    error_message = "ingestion_access_mode must be one of: Open, PrivateOnly."
  }
}

variable "query_access_mode" {
  description = "Access mode for query - controls how data can be queried"
  type        = string
  default     = "PrivateOnly"

  validation {
    condition     = contains(["Open", "PrivateOnly"], var.query_access_mode)
    error_message = "query_access_mode must be one of: Open, PrivateOnly."
  }
}

variable "log_analytics_workspaces" {
  description = "Array of Log Analytics workspaces ({ id }) to connect to AMPLS. The list length must be known at plan time."
  type        = list(object({ id = string }))
  default     = []
}

variable "application_insights_components" {
  description = "Array of Application Insights components ({ id }) to connect to AMPLS. The list length must be known at plan time."
  type        = list(object({ id = string }))
  default     = []
}

variable "data_collection_endpoints" {
  description = "Array of Data Collection Endpoints ({ id }) to connect to AMPLS. The list length must be known at plan time."
  type        = list(object({ id = string }))
  default     = []
}

variable "enable_network_isolation" {
  description = "Enable network isolation for maximum security (declared but not used by the Bicep)."
  type        = bool
  default     = true
}
