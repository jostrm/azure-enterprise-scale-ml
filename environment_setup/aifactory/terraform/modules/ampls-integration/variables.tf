variable "subscription_id" {
  description = "subscription().subscriptionId of the Bicep module scope (13-rgLevel: the common resource group's subscription)."
  type        = string
}

variable "resource_group_name" {
  description = "resourceGroup().name of the Bicep module scope (13-rgLevel: the common resource group)."
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

variable "priv_dns_subscription" {
  description = "Private DNS subscription (from foundation)"
  type        = string
}

variable "priv_dns_resource_group" {
  description = "Private DNS resource group (from foundation)"
  type        = string
}

variable "hub_vnet_name" {
  description = "Hub virtual network name"
  type        = string
}

variable "hub_vnet_resource_group" {
  description = "Hub virtual network resource group"
  type        = string
}

variable "monitoring_subnet_name" {
  description = "Monitoring subnet name in hub"
  type        = string
  default     = "snet-monitoring"
}

variable "existing_log_analytics_workspace_ids" {
  description = "Existing Log Analytics workspace IDs to connect to AMPLS (list length must be known at plan time)"
  type        = list(string)
  default     = []
}

variable "existing_application_insights_ids" {
  description = "Existing Application Insights IDs to connect to AMPLS (list length must be known at plan time)"
  type        = list(string)
  default     = []
}

variable "ingestion_access_mode" {
  description = "AMPLS ingestion access mode"
  type        = string
  default     = "PrivateOnly"

  validation {
    condition     = contains(["Open", "PrivateOnly"], var.ingestion_access_mode)
    error_message = "ingestion_access_mode must be one of: Open, PrivateOnly."
  }
}

variable "query_access_mode" {
  description = "AMPLS query access mode"
  type        = string
  default     = "PrivateOnly"

  validation {
    condition     = contains(["Open", "PrivateOnly"], var.query_access_mode)
    error_message = "query_access_mode must be one of: Open, PrivateOnly."
  }
}

variable "deploy_to_hub_resource_group" {
  description = "Deploy to hub resource group (where private DNS zones are). The caller must pass the azurerm provider of the target subscription (priv_dns_subscription when true, subscription_id when false)."
  type        = bool
  default     = true
}
