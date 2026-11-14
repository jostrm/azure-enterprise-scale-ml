output "nsg_id" {
  description = "Resource id of the network security group."
  value       = azurerm_network_security_group.pbi_nsg.id
}

output "flow_log_id" {
  description = "Resource id of the NSG flow log, or empty string when not deployed."
  value       = local.deploy_flow_log ? azurerm_network_watcher_flow_log.nsg_flow_log[0].id : ""
}
