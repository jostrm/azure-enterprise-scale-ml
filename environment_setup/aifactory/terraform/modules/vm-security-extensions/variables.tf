variable "subscription_id" {
  description = "Subscription of the VM's resource group (the Bicep module scope)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the VM (the Bicep module scope)."
  type        = string
}

variable "vm_name" {
  description = "Name of an existing VM in this resource group, created with Trusted Launch and a system-assigned identity."
  type        = string
}

variable "location" {
  description = "Location of the VM. azurerm_virtual_machine_extension takes the VM's location, which is this value."
  type        = string
}

variable "os_type" {
  description = "Operating system of the VM."
  type        = string

  validation {
    condition     = contains(["Windows", "Linux"], var.os_type)
    error_message = "os_type must be one of: Windows, Linux."
  }
}

variable "tags" {
  description = "Tags for the extension resources."
  type        = map(string)
  default     = {}
}
