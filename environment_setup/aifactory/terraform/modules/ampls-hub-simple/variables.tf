variable "subscription_id" {
  description = "Subscription of the target resource group (the Bicep module scope). The caller passes the matching azurerm provider."
  type        = string
}

variable "resource_group_name" {
  description = "Target resource group of the AMPLS, DCE and private endpoint (the Bicep module scope)."
  type        = string
}

variable "env" {
  description = "Environment identifier (dev, test, prod)"
  type        = string

  validation {
    condition     = contains(["dev", "test", "prod"], var.env)
    error_message = "env must be one of: dev, test, prod."
  }
}

variable "location" {
  description = "Location for all resources"
  type        = string
}

variable "location_suffix" {
  description = "Location suffix for naming (e.g., weu, eus2)"
  type        = string
}

variable "common_resource_suffix" {
  description = "Common resource naming suffix"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "hub_vnet_name" {
  description = "Hub virtual network name"
  type        = string
}

variable "hub_vnet_resource_group" {
  description = "Hub virtual network resource group (same subscription as this module's scope)"
  type        = string
}

variable "hub_subnet_name" {
  description = "Hub subnet for the AMPLS private endpoint"
  type        = string
  default     = "snet-monitoring"
}

variable "log_analytics_workspaces" {
  description = "Existing Log Analytics Workspaces ({ id }) to connect"
  type        = list(object({ id = string }))
  default     = []
}

variable "application_insights_components" {
  description = "Existing Application Insights ({ id }) to connect"
  type        = list(object({ id = string }))
  default     = []
}

variable "private_dns_zone_resource_ids" {
  description = "Private DNS Zone configuration"
  type = object({
    monitor  = string
    oms      = string
    ods      = string
    agentsvc = string
  })
  default = {
    monitor  = ""
    oms      = ""
    ods      = ""
    agentsvc = ""
  }
}

variable "ingestion_access_mode" {
  description = "Access mode for AMPLS ingestion"
  type        = string
  default     = "PrivateOnly"

  validation {
    condition     = contains(["Open", "PrivateOnly"], var.ingestion_access_mode)
    error_message = "ingestion_access_mode must be one of: Open, PrivateOnly."
  }
}

variable "query_access_mode" {
  description = "Access mode for AMPLS query"
  type        = string
  default     = "PrivateOnly"

  validation {
    condition     = contains(["Open", "PrivateOnly"], var.query_access_mode)
    error_message = "query_access_mode must be one of: Open, PrivateOnly."
  }
}
