variable "subscription_id" {
  description = "Subscription of the resource group holding the private endpoints (the Bicep module scope)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group holding the private endpoints (the Bicep module scope)."
  type        = string
}

variable "dns_config" {
  description = "dnsConfig output of a resource module: objects { name = private endpoint name ('' = none), type = key in private_links_dns_zones, id, groupid }. Names must be known at plan time."
  type = list(object({
    name    = string
    type    = string
    id      = optional(string)
    groupid = optional(string)
  }))
}

variable "private_links_dns_zones" {
  description = "13-rgLevel privateLinksDnsZones: map of type => { id, name } of the private DNS zones."
  type = map(object({
    id   = string
    name = string
  }))
}

variable "resource_created_now" {
  description = "Unused by the Bicep (kept for interface parity)."
  type        = bool
  default     = false
}
