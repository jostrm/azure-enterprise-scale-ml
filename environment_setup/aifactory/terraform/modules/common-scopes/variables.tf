variable "parameters" {
  description = "The 13-rgLevel.bicep parameters this module reads (Bicep names and defaults)."
  type = object({
    env                                   = string
    locationSuffix                        = string
    tags                                  = any
    aifactorySuffixRG                     = optional(string, "")
    commonRGNamePrefix                    = optional(string, "")
    commonResourceName                    = optional(string, "esml-common")
    commonResourceGroup_param             = optional(string, "")
    vnetResourceGroup_param               = optional(string, "")
    network_env                           = optional(string, "")
    centralDnsZoneByPolicyInHub           = optional(bool, false)
    access_hub_mode                       = optional(string, "")
    setup_hub_access                      = optional(bool, false)
    own_hub_vnet_id                       = optional(string, "")
    own_hub_private_dns_resource_group_id = optional(string, "")
    privDnsSubscription_param             = optional(string, "")
    privDnsResourceGroup_param            = optional(string, "")
    deployOnlyAIGatewayNetworking         = optional(bool, false)
    inputKeyvault                         = string
    inputKeyvaultSubscription             = string
    inputKeyvaultResourcegroup            = string
    inputCommonSPIDKey                    = string
    inputCommonSPSecretKey                = string
    commonServicePrincipleOIDKey          = string
  })
}

variable "subscription_id" {
  description = "subscription().subscriptionId of the common environment."
  type        = string
}
