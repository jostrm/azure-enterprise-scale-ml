variable "subscription_id" {
  description = "Subscription ID of the deployment resource group."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group the identity is created in (the Bicep module's scope)."
  type        = string
}

variable "name" {
  description = "Name of the user assigned managed identity."
  type        = string
}

variable "location" {
  description = "Location of the managed identity."
  type        = string
}

variable "tags" {
  description = "Tags; 'azd-service-name' = name is added."
  type        = map(string)
}
