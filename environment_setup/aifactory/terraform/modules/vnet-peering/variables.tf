variable "resource_group_name" {
  description = "Resource group of the local VNet (the Bicep module scope)."
  type        = string
}

variable "vnet_name" {
  description = "Name of the local VNet (in this resource group) that owns the peering."
  type        = string
}

variable "peering_name" {
  description = "Deterministic peering name, max 80 characters."
  type        = string

  validation {
    condition     = length(var.peering_name) <= 80
    error_message = "peering_name must be at most 80 characters."
  }
}

variable "remote_vnet_id" {
  description = "ARM id of the remote VNet."
  type        = string
}

variable "allow_gateway_transit" {
  description = "true on the hub side: lets the spoke use the hub VPN gateway."
  type        = bool
  default     = false
}

variable "use_remote_gateways" {
  description = "true on the spoke side: route to the hub VPN gateway. The hub side must already allow gateway transit."
  type        = bool
  default     = false
}
