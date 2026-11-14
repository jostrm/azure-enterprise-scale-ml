variable "nsg_id" {
  description = "Specifies the id of an NSG that should be connected to new subnet."
  type        = string
  default     = ""
}

variable "name" {
  description = "Specifies the name of the new subnet."
  type        = string
}

variable "address_prefix" {
  description = "Specifies the address prefix used for new subnet."
  type        = string
}

variable "location" {
  description = "Location used for the service endpoint locations of the new subnet."
  type        = string
}

variable "service_endpoints" {
  description = "Specifies an array of service endpoints that should be enabled on the new subnet."
  type        = list(string)
  default     = []
}

variable "delegations" {
  description = "Specifies an array of delegations (service names) that should be enabled on the new subnet."
  type        = list(string)
}

variable "virtual_network_name" {
  description = "Specifies the name of a virtual network used for deploying new subnet."
  type        = string
}

variable "private_endpoint_network_policies" {
  description = "privateEndpointNetworkPolicies of the subnet."
  type        = string
  default     = "Disabled"
}

variable "private_link_service_network_policies" {
  description = "privateLinkServiceNetworkPolicies of the subnet."
  type        = string
  default     = "Enabled"
}

variable "central_dns_zone_by_policy_in_hub" {
  description = "Unused by the Bicep module; kept for parity of the parameter list."
  type        = bool
  default     = false
}

variable "route_table_id" {
  description = "Optional route table id."
  type        = string
  default     = ""
}

variable "nat_gateway_id" {
  description = "Optional NAT gateway id."
  type        = string
  default     = ""
}

variable "allow_default_outbound_access" {
  description = "defaultOutboundAccess of the subnet."
  type        = bool
  default     = false
}

variable "subscription_id" {
  description = "Subscription of the virtual network (the Bicep module's deployment scope)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the virtual network (the Bicep module's deployment scope)."
  type        = string
}
