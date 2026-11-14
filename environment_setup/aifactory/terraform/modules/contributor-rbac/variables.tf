variable "subscription_id" {
  description = "Subscription ID of the deployment resource group (subscription().subscriptionId)."
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group the Contributor role is assigned on (resourceGroup().name)."
  type        = string
}

variable "user_id" {
  description = "Specifies the objectId of the person that ordered the resources"
  type        = string
  default     = ""
}

variable "user_email" {
  description = "Specifies the email address of the person that ordered the resources (used in the role assignment description only)"
  type        = string
}

variable "use_ad_groups" {
  description = "true: the additional object IDs are AD groups (principalType Group)."
  type        = bool
  default     = false
}

variable "contributor_role_id" {
  description = "Contributor role ID for RBAC assignments. Default is the built-in Contributor role."
  type        = string
  default     = "b24988ac-6180-42a0-ab88-20f7382dd24c"
}

variable "additional_user_ids" {
  description = "Additional optional Object ID of more people to access Resource group"
  type        = list(string)

  validation {
    # ARM rejects a template that defines the same role assignment name twice; for_each needs unique keys.
    condition     = length(distinct(var.additional_user_ids)) == length(var.additional_user_ids)
    error_message = "additional_user_ids must not contain duplicates."
  }
}

variable "additional_user_emails" {
  description = "Additional optional email adress of more people to access the Resource group (description only)"
  type        = list(string)
}
