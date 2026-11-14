variable "name" {
  description = "Base name of the AI gateway networking resources."
  type        = string
  default     = "ai-gateway"
}

variable "tags" {
  description = "Tags."
  type        = map(string)
}

variable "location" {
  description = "Location."
  type        = string
}

variable "location_suffix" {
  description = "Short location notation, e.g. weu."
  type        = string
}

variable "env" {
  description = "Environment: dev, test or prod."
  type        = string
}

variable "aifactory_suffix_rg" {
  description = "AI Factory suffix for resource groups."
  type        = string
}

variable "common_rg_name_prefix" {
  description = "Resource group name prefix."
  type        = string
}

variable "vnet_name" {
  description = "Unused by the Bicep module (vnetNameFull is derived); kept for parity of the parameter list."
  type        = string
}

variable "common_resource_suffix" {
  description = "Common resource suffix, e.g. -001."
  type        = string
}

variable "subscription_id_dev_test_prod" {
  description = "Subscription of the vNet resource group."
  type        = string
}

variable "vnet_resource_group_param" {
  description = "Optional BYO vNet resource group name; '<network_env>' is replaced by network_env."
  type        = string
  default     = ""
}

variable "vnet_name_full_param" {
  description = "Optional BYO full vNet name."
  type        = string
  default     = ""
}

variable "network_env" {
  description = "Network environment token used in vnet_resource_group_param."
  type        = string
  default     = ""
}

variable "vnet_name_base" {
  description = "vNet base name."
  type        = string
  default     = "vnt-esmlcmn"
}

variable "central_dns_zone_by_policy_in_hub" {
  description = "If true, use the DNS zone in the hub for the private endpoint. If false, use the DNS zone in the same resource group as the private endpoint."
  type        = bool
  default     = false
}

variable "cidr_apim" {
  description = "CIDR of the APIM subnet (Bicep: CIDRApim)."
  type        = string
}

variable "cidr_function_app" {
  description = "CIDR of the Function App subnet (Bicep: CIDRFunctionApp)."
  type        = string
}

variable "resource_group_name" {
  description = <<-EOT
    Terraform-only: resource group this Bicep module is deployed to (its implicit scope; the 12 stage passes its own
    vNet resource group). The two subnets go here, while the NSGs and route table go to the vNet resource group
    computed inside the module, as in the Bicep. null = the computed vNet resource group.
  EOT
  type        = string
  default     = null
}
