variable "plan" {
  description = <<-EOT
    Only the reviewed, live-inventory-bound preserve-v1 plan is supported (produced by
    common_network_preservation.plan_common_network; never reuse a stale plan). Same shape as the Bicep param:
    { createVnet = bool, addressPrefixes = list(string), createSubnets = list({ name = string, properties = <ARM subnet properties> }),
      createNetworkSecurityGroups = list(string) }
  EOT
  type        = any
}

variable "location" {
  description = "Location of the vNet."
  type        = string
}

variable "tags" {
  description = "Tags."
  type        = map(string)
}

variable "vnet_name_full" {
  description = "Full name of the virtual network."
  type        = string
}

variable "subscription_id" {
  description = "Subscription of the vNet resource group (the Bicep module's deployment scope)."
  type        = string
}

variable "resource_group_name" {
  description = "vNet resource group (the Bicep module's deployment scope)."
  type        = string
}
