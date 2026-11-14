variable "dce_name" {
  description = "Name of the Data Collection Endpoint"
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the DCE (the Bicep module scope)."
  type        = string
}

variable "location" {
  description = "Location for the DCE resource"
  type        = string
}

variable "tags" {
  description = "Tags to apply to the DCE resource"
  type        = map(string)
  default     = {}
}

variable "dce_description" {
  description = "Description of the Data Collection Endpoint"
  type        = string
  default     = "Data Collection Endpoint for Azure Monitor Agent private link"
}

variable "kind" {
  description = "Kind of the Data Collection Endpoint"
  type        = string
  default     = "Linux"

  validation {
    condition     = contains(["Linux", "Windows"], var.kind)
    error_message = "kind must be one of: Linux, Windows."
  }
}

variable "enable_public_network_access" {
  description = "Enable public network access"
  type        = bool
  default     = false
}
