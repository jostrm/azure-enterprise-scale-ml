variable "subscription_id" {
  description = "Subscription ID of the deployment resource group (subscription().subscriptionId)."
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group the role is assigned on (resourceGroup().name)."
  type        = string
}

variable "user_id" {
  description = "Specifies the objectId of the person that ordered the resources"
  type        = string
  default     = ""
}

variable "user_email" {
  description = "Specifies the email address of the person that ordered the resources (description only)"
  type        = string
}

variable "additional_user_ids" {
  description = "Additional optional Object ID of more people to access the Vm vmAdminLoginRole"
  type        = list(string)

  validation {
    # ARM rejects a template that defines the same role assignment name twice.
    condition     = length(distinct(var.additional_user_ids)) == length(var.additional_user_ids)
    error_message = "additional_user_ids must not contain duplicates."
  }
}

variable "additional_user_emails" {
  description = "Additional optional email address of more people to access the Vm vmAdminLoginRole (unused by the Bicep body, kept for parity)"
  type        = list(string)
}

variable "use_ad_groups" {
  description = "true: the additional object IDs are AD groups (principalType Group)."
  type        = bool
  default     = false
}
