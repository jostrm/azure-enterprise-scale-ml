variable "location" {
  description = "Location of the route table."
  type        = string
}

variable "tags" {
  description = "Tags. 'azd-service-name' = name is added (Bicep: union(tags, { 'azd-service-name': name }))."
  type        = map(string)
}

variable "name" {
  description = "Name of the route table."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group the route table is deployed to (the Bicep module's deployment scope)."
  type        = string
}
