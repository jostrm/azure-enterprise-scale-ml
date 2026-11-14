output "deploy" {
  description = "Bicep module symbol -> deployed? (the `if` of each module in 13-rgLevel.bicep)."
  value       = local.deploy
}

output "names" {
  description = "Names 13-rgLevel.bicep deploys, keyed by the Bicep variable that holds them."
  value = merge(local.names, {
    privDnsResourceGroupName = local.priv_dns_resource_group_name
    privDnsSubscription      = local.priv_dns_subscription
  })
}

output "adminVmResourceId" {
  description = "Admin VM resource ID. Empty when enableAdminVM is false or only AI Gateway networking is deployed."
  value       = local.deploy.vmPrivate ? module.vmPrivate[0].vm_resource_id : ""
}

output "adminVmName" {
  description = "Admin VM name and recommended self-hosted agent name. Empty when the admin VM is disabled."
  value       = local.deploy.vmPrivate ? module.vmPrivate[0].vm_name : ""
}
