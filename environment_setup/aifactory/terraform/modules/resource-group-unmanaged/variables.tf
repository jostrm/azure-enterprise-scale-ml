variable "rg_name" {
  description = "Name of the resource group."
  type        = string
}

variable "location" {
  description = "Location of the resource group."
  type        = string
}

variable "tags" {
  description = "Tags applied to the resource group."
  type        = map(string)
}
