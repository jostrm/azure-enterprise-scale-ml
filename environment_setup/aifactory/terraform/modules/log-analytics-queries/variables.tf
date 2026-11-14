variable "subscription_id" {
  description = "Subscription ID of the deployment resource group."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the workspace (the Bicep module's scope; resourceGroup().id seeds the names)."
  type        = string
}

variable "log_analytics_name" {
  description = "Name of the Log Analytics workspace."
  type        = string
}

variable "deployment_name" {
  description = "Name of the Bicep module deployment (deployment().name), which seeds the saved search names, e.g. 'logAnalyticsCmnQs<uniqueInAIFenv>'."
  type        = string
}
