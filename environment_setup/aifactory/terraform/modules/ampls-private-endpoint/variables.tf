variable "private_endpoint_name" {
  description = "Name of the private endpoint"
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the private endpoint (the Bicep module scope)."
  type        = string
}

variable "location" {
  description = "Location for the private endpoint"
  type        = string
}

variable "tags" {
  description = "Tags to apply to the private endpoint"
  type        = map(string)
  default     = {}
}

variable "subnet_id" {
  description = "Resource ID of the subnet where the private endpoint will be created"
  type        = string
}

variable "ampls_id" {
  description = "Resource ID of the Azure Monitor Private Link Scope"
  type        = string
}

variable "private_dns_zone_configs" {
  description = "Array of private DNS zone configurations"
  type = list(object({
    name                         = string
    private_dns_zone_resource_id = string
  }))
  default = [
    {
      name                         = "privatelink-monitor-azure-com"
      private_dns_zone_resource_id = ""
    },
    {
      name                         = "privatelink-oms-opinsights-azure-com"
      private_dns_zone_resource_id = ""
    },
    {
      name                         = "privatelink-ods-opinsights-azure-com"
      private_dns_zone_resource_id = ""
    },
    {
      name                         = "privatelink-agentsvc-azure-automation-net"
      private_dns_zone_resource_id = ""
    },
  ]
}

variable "enable_private_dns_zone_group" {
  description = "Enable automatic private DNS zone group"
  type        = bool
  default     = true
}
