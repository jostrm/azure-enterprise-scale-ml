variable "subscription_id" {
  description = "Subscription of the common environment (subscription().subscriptionId)."
  type        = string
}

variable "env" {
  description = "dev, test or prod."
  type        = string
  validation {
    condition     = contains(["dev", "test", "prod"], var.env)
    error_message = "env must be dev, test or prod."
  }
}

variable "location" {
  type = string
}

variable "location_suffix" {
  description = "Short location, for example weu or sdc."
  type        = string
}

variable "aifactory_suffix_rg" {
  description = "Scale set suffix of the resource groups, for example -001."
  type        = string
  default     = ""
}

variable "common_rg_name_prefix" {
  description = "Resource group prefix (admin_aifactoryPrefixRG)."
  type        = string
  default     = ""
}

variable "common_resource_name" {
  description = "Common resource name identifier (vnetResourceGroupBase), default esml-common."
  type        = string
  default     = "esml-common"
}

variable "common_resource_suffix" {
  type    = string
  default = ""
}

variable "common_resource_short_name" {
  type    = string
  default = "cmn"
}

variable "common_resource_abbreviation" {
  type    = string
  default = "esml"
}

variable "common_resource_group_param" {
  type    = string
  default = ""
}

variable "vnet_name_base" {
  type = string
}

variable "vnet_resource_group_param" {
  type    = string
  default = ""
}

variable "vnet_name_full_param" {
  type    = string
  default = ""
}

variable "network_env" {
  type    = string
  default = ""
}

variable "common_lake_name_prefix_max8chars" {
  type    = string
  default = ""
}

variable "common_subnet_name" {
  type    = string
  default = ""
}

variable "byo_subnets" {
  type    = bool
  default = false
}

variable "subnet_common" {
  type    = string
  default = ""
}

variable "subnet_common_scoring" {
  type    = string
  default = ""
}

variable "subnet_common_powerbi_gw" {
  type    = string
  default = ""
}
