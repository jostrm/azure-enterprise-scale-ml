# Port of the scope variables of environment_setup/aifactory/bicep/esml-common/main/13-rgLevel.bicep:
# where the private DNS zones live, which hub an added own-hub scale set joins, and whether the common
# service principal is read from the seeding Key Vault (externalKv.getSecret). Pure (no resources), so the
# root can configure the private_dns and own_hub providers from it before any resource is planned.

locals {
  p = var.parameters

  common_resource_group_name = local.p.commonResourceGroup_param != "" ? local.p.commonResourceGroup_param : "${local.p.commonRGNamePrefix}${local.p.commonResourceName}-${local.p.locationSuffix}-${local.p.env}${local.p.aifactorySuffixRG}"
  vnet_resource_group_name   = local.p.vnetResourceGroup_param != "" ? replace(local.p.vnetResourceGroup_param, "<network_env>", local.p.network_env) : local.common_resource_group_name

  # var bootstrapManagedPrivateDns = !centralDnsZoneByPolicyInHub && toLower(access_hub_mode) == 'integrated' && setup_hub_access
  bootstrap_managed_private_dns = !local.p.centralDnsZoneByPolicyInHub && lower(local.p.access_hub_mode) == "integrated" && local.p.setup_hub_access
  # var joinOwnHub = bootstrapManagedPrivateDns && own_hub_vnet_id != ''
  join_own_hub = local.bootstrap_managed_private_dns && local.p.own_hub_vnet_id != ""

  # Padded splits keep the indexes valid when the parameters are empty.
  own_hub_vnet_parts                 = split("/", "${local.p.own_hub_vnet_id}/////////")
  own_hub_subscription_id            = local.join_own_hub ? local.own_hub_vnet_parts[2] : var.subscription_id
  own_hub_resource_group_name        = local.join_own_hub ? local.own_hub_vnet_parts[4] : local.vnet_resource_group_name
  own_hub_private_dns_resource_group = local.p.own_hub_private_dns_resource_group_id != "" ? local.p.own_hub_private_dns_resource_group_id : "/subscriptions/${local.own_hub_vnet_parts[2]}/resourceGroups/${local.own_hub_vnet_parts[4]}"
  own_hub_private_dns_parts          = split("/", "${local.own_hub_private_dns_resource_group}////")
  priv_dns_resource_group_name       = local.join_own_hub ? local.own_hub_private_dns_parts[4] : ((local.p.privDnsResourceGroup_param != "" && local.p.centralDnsZoneByPolicyInHub) ? local.p.privDnsResourceGroup_param : local.vnet_resource_group_name)
  priv_dns_subscription              = local.join_own_hub ? local.own_hub_private_dns_parts[2] : ((local.p.privDnsSubscription_param != "" && local.p.centralDnsZoneByPolicyInHub) ? local.p.privDnsSubscription_param : var.subscription_id)

  # SP removal support: a common service principal is used only when its seeding Key Vault secret name is set and
  # is not a placeholder (<todo>/<optional>).
  use_common_sp_oid       = local.p.commonServicePrincipleOIDKey != "" && !strcontains(lower(local.p.commonServicePrincipleOIDKey), "<todo>") && !strcontains(lower(local.p.commonServicePrincipleOIDKey), "<optional>")
  use_common_sp_id        = local.p.inputCommonSPIDKey != "" && !strcontains(lower(local.p.inputCommonSPIDKey), "<todo>") && !strcontains(lower(local.p.inputCommonSPIDKey), "<optional>")
  use_common_sp_secret    = local.p.inputCommonSPSecretKey != "" && !strcontains(lower(local.p.inputCommonSPSecretKey), "<todo>") && !strcontains(lower(local.p.inputCommonSPSecretKey), "<optional>")
  personas_groups_enabled = try(local.p.tags["AIF-Persona-Access"], "") == "groups-v1"
  # spCmnKvSecretsUser / kvAdminCommonSPSecretsUser read the object id; addSecret copies all three secrets.
  read_common_sp_oid   = !local.personas_groups_enabled && !local.p.deployOnlyAIGatewayNetworking && local.use_common_sp_oid
  copy_common_sp       = !local.p.deployOnlyAIGatewayNetworking && local.use_common_sp_id && local.use_common_sp_secret && local.use_common_sp_oid
  seeding_key_vault_id = "/subscriptions/${local.p.inputKeyvaultSubscription}/resourceGroups/${local.p.inputKeyvaultResourcegroup}/providers/Microsoft.KeyVault/vaults/${local.p.inputKeyvault}"
}
