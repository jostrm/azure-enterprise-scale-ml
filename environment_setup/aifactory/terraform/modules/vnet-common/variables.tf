variable "location" {
  description = "Deployment location."
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

variable "common_vnet_cidr" {
  description = "CIDR for common vNet."
  type        = string
}

variable "common_pbi_subnet_name" {
  description = "Common Power BI subnet for vNet gateway."
  type        = string
}

variable "common_pbi_subnet_cidr" {
  description = "CIDR for common Power BI subnet for gateway."
  type        = string
}

variable "common_subnet_name" {
  description = "Common subnet."
  type        = string
}

variable "common_subnet_cidr" {
  description = "CIDR for common subnet."
  type        = string
}

variable "common_subnet_scoring_cidr" {
  description = "CIDR for common scoring subnet."
  type        = string
}

variable "common_bastion_subnet_name" {
  description = "Common Bastion host subnet for RDP access over private IP."
  type        = string
}

variable "common_bastion_subnet_cidr" {
  description = "Common Bastion host subnet CIDR."
  type        = string
}

variable "central_dns_zone_by_policy_in_hub" {
  description = "Unused by the Bicep module; kept for parity of the parameter list."
  type        = bool
  default     = false
}

variable "deploy_only_ai_gateway_networking" {
  description = "Unused by the Bicep module; kept for parity of the parameter list."
  type        = bool
  default     = false
}

variable "byo_subnet" {
  description = "BYO subnets: create the subnets as separate resources in an existing vNet."
  type        = bool
  default     = false
}

variable "byo_vnet" {
  description = "BYO vNet: create the subnets as separate resources in an existing vNet."
  type        = bool
  default     = false
}

variable "subscription_id" {
  description = "Subscription of the vNet resource group (the Bicep module's deployment scope)."
  type        = string
}

variable "resource_group_name" {
  description = "vNet resource group (the Bicep module's deployment scope); the nsg-* NSGs live here too."
  type        = string
}
