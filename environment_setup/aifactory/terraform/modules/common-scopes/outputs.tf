output "bootstrap_managed_private_dns" {
  value = local.bootstrap_managed_private_dns
}

output "join_own_hub" {
  value = local.join_own_hub
}

output "own_hub_vnet_parts" {
  value = local.own_hub_vnet_parts
}

output "own_hub_subscription_id" {
  value = local.own_hub_subscription_id
}

output "own_hub_resource_group_name" {
  value = local.own_hub_resource_group_name
}

output "priv_dns_subscription" {
  value = local.priv_dns_subscription
}

output "priv_dns_resource_group_name" {
  value = local.priv_dns_resource_group_name
}

output "use_common_sp_oid" {
  value = local.use_common_sp_oid
}

output "use_common_sp_id" {
  value = local.use_common_sp_id
}

output "use_common_sp_secret" {
  value = local.use_common_sp_secret
}

output "personas_groups_enabled" {
  value = local.personas_groups_enabled
}

output "read_common_sp_oid" {
  value = local.read_common_sp_oid
}

output "copy_common_sp" {
  value = local.copy_common_sp
}

output "seeding_key_vault_id" {
  value = local.seeding_key_vault_id
}
