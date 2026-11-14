variable "name" {
  description = "Specifies the name of the NSG, network security group."
  type        = string
}

variable "location" {
  description = "Specifies the location where the network security group should be deployed."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group the NSG is deployed to (the Bicep module's deployment scope; the stage passes the vNet resource group)."
  type        = string
}

variable "tags" {
  description = "Specifies the tags that should be applied to the network security group."
  type        = map(string)
}

variable "ip_whitelist_array" {
  description = "Optional: whitelist IP addresses from project members to see keyvault, and to connect via Bastion (Bicep: IPwhiteList_Array)."
  type        = list(string)
  default     = []
}

variable "enable_flow_logs" {
  description = "Deploy the NSG flow log (only when storage_account_id is also set)."
  type        = bool
  default     = true
}

variable "storage_account_id" {
  description = "Storage account id for the NSG flow log. Empty = no flow log."
  type        = string
  default     = ""
}

variable "network_watcher_name" {
  description = "Network watcher name. null = Bicep default 'NetworkWatcher_<location>'."
  type        = string
  default     = null
}

variable "network_watcher_resource_group" {
  description = "Resource group of the network watcher (Bicep: networkWatcherResourceGroup)."
  type        = string
  default     = "NetworkWatcherRG"
}

variable "flow_log_retention_days" {
  description = "Flow log retention in days."
  type        = number
  default     = 30
}
