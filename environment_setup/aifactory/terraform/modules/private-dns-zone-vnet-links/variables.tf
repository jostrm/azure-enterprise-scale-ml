variable "subscription_id" {
  description = "Subscription of the resource group holding the private DNS zones (the Bicep module scope)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group holding the existing private DNS zones (the Bicep module scope)."
  type        = string
}

variable "private_links_dns_zones" {
  description = "Zones to link: objects with a name property (13-rgLevel privateLinksDnsZonesArray)."
  type = list(object({
    name = string
    id   = optional(string)
  }))
}

variable "vnet_id" {
  description = "ARM id of the VNet to link."
  type        = string
}

variable "location" {
  description = "Deployment location. Used only for the '<location>.data.privatelink.azurecr.io' zone when all_global is false."
  type        = string
}

variable "all_global" {
  description = "true: every link is in location 'global'."
  type        = bool
  default     = true
}
