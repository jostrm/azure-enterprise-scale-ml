variable "priv_dns_subscription" {
  description = "Subscription of the private DNS zones (the scope this module deploys to; the caller passes the matching azurerm provider)."
  type        = string
}

variable "priv_dns_resource_group" {
  description = "Resource group of the private DNS zones (the scope this module deploys to)."
  type        = string
}

variable "v_net_name" {
  description = "Name of the VNet to link every zone to."
  type        = string
}

variable "v_net_resource_group" {
  description = "Resource group of the VNet (same subscription as the zones, like the Bicep resourceGroup(vNetResourceGroup))."
  type        = string
}

variable "location" {
  description = "Deployment location. Used only for the '<location>.data.privatelink.azurecr.io' zone when all_global is false."
  type        = string
}

variable "all_global" {
  description = "true: every zone and link is in location 'global' (Microsoft only supports global Private DNS Zones)."
  type        = bool
  default     = true
}

variable "private_links_dns_zones" {
  description = "Zones to create: objects with name (and id) - 13-rgLevel privateLinksDnsZonesArray."
  type = list(object({
    name = string
    id   = optional(string)
  }))
}
