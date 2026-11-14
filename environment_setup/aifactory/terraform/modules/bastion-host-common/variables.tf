variable "tags" {
  description = "tags"
  type        = map(string)
}

variable "name" {
  description = "Name of the BASTION host"
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the Bastion host (the Bicep module scope)."
  type        = string
}

variable "location" {
  description = "location"
  type        = string
  default     = "westeurope"
}

variable "scale_units" {
  description = "2-50 VMs to support"
  type        = number
  default     = 3
}

variable "subnet_id" {
  description = "subnet resourceId for Bastion host"
  type        = string
}
