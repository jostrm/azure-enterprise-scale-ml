output "deploy" {
  description = "Bicep module symbol -> deployed? (the `if` of each module in 11-rgCommon.bicep)."
  value       = local.deploy
}

output "names" {
  description = "Names 11-rgCommon.bicep deploys."
  value = {
    commonResourceGroupName = local.common_resource_group_name
    uniqueInAIFenv          = module.naming.unique_in_aif_env
    cmkIdentityName         = local.cmk_identity_name
  }
}

output "common_resource_group_id" {
  value = module.rgCommon.rg_id
}

output "cmk_identity" {
  description = "The CMK identity 13-rgLevel reads as cmkIdentityExisting (null when cmk is false)."
  value = local.deploy.cmkIdentity ? {
    id           = module.cmkIdentity[0].managed_identity_id
    client_id    = module.cmkIdentity[0].managed_identity_client_id
    principal_id = module.cmkIdentity[0].managed_identity_principal_id
  } : null
}
