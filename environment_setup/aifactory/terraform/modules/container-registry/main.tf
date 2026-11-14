# Port of environment_setup/aifactory/bicep/modules/containerRegistry.bicep

# Resource group scope. The Bicep imports managedIdentityAllType from br/public:avm/utl/types/avm-common-types:0.5.1
# only as a parameter type; it is expressed here as the type of var.managed_identities.

locals {
  resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  # Bicep 'existing' vnet (scope: resourceGroup(vnetResourceGroupName)) + subnet -> subnet.id, built like resourceId()
  subnet_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.vnet_resource_group_name}/providers/Microsoft.Network/virtualNetworks/${var.vnet_name}/subnets/${var.subnet_name}"

  policy_on                       = "disabled" # 'enabled' // 'disabled' GET https:: IMAGE_QUARANTINED: The image is quarantined
  container_registry_name_cleaned = replace(var.container_registry_name, "-", "")

  # Combine existing IP rules with new ones (union() also drops identical objects)
  all_ip_rules = distinct(concat(var.existing_ip_rules, var.ip_rules))
  # Normalize IP addresses: ensure single IPs have /32 suffix for proper deduplication
  normalized_ip_rules = [for rule in local.all_ip_rules : {
    value  = strcontains(rule.value, "/") ? rule.value : "${rule.value}/32"
    action = rule.action
  }]
  # Remove duplicates by the normalized 'value' (the last rule for a value wins, as in the Bicep reduce/union);
  # items() returns the entries sorted by key, as does iterating a Terraform map.
  unique_ip_rules_map = { for rule in local.normalized_ip_rules : rule.value => rule... }
  unique_ip_rules     = [for k, v in local.unique_ip_rules_map : v[length(v) - 1]]

  # managedIdentities (managedIdentityAllType?): null or an object with optional systemAssigned / userAssignedResourceIds.
  # Bicep empty(managedIdentities) is true for null and for {} (no property set).
  managed_identities_empty           = var.managed_identities == null ? true : (var.managed_identities.system_assigned == null && var.managed_identities.user_assigned_resource_ids == null)
  formatted_user_assigned_identities = var.managed_identities == null ? [] : coalesce(var.managed_identities.user_assigned_resource_ids, [])
  system_assigned                    = var.managed_identities == null ? false : coalesce(var.managed_identities.system_assigned, false)

  cmk_identity                 = (var.cmk && var.cmk_identity_id != "") ? [var.cmk_identity_id] : []
  all_user_assigned_identities = distinct(concat(local.formatted_user_assigned_identities, local.cmk_identity))

  # When CMK is enabled, ensure identity is UserAssigned with the CMK identity attached
  identity_type = (var.cmk && var.cmk_identity_id != "") ? "UserAssigned" : (
    (!local.managed_identities_empty || length(local.cmk_identity) > 0) ? (
      local.system_assigned
      ? (length(local.all_user_assigned_identities) > 0 ? "SystemAssigned, UserAssigned" : "SystemAssigned")
      : (length(local.all_user_assigned_identities) > 0 ? "UserAssigned" : "None")
    ) : "SystemAssigned" # Default fallback if nothing provided
  )
  identity_ids = (var.cmk && var.cmk_identity_id != "") ? [var.cmk_identity_id] : (
    length(local.all_user_assigned_identities) > 0 && local.identity_type != "SystemAssigned" ? local.all_user_assigned_identities : null
  )

  properties = merge(
    {
      adminUserEnabled         = var.admin_user_enabled
      dataEndpointEnabled      = var.dedicated_data_point
      networkRuleBypassOptions = "AzureServices"
      policies = {
        quarantinePolicy = {
          status = local.policy_on
        }
        retentionPolicy = {
          status = local.policy_on
          days   = var.retention_days
        }
        trustPolicy = {
          status = local.policy_on
          type   = "Notary"
        }
        exportPolicy = {
          status = var.export_enabled
          # status: enablePublicAccessWithPerimeter || allowPublicAccessWhenBehindVnet ? 'enabled' : 'disabled'
        }
      }
      publicNetworkAccess = (var.enable_public_access_with_perimeter || var.allow_public_access_when_behind_vnet) ? "Enabled" : "Disabled"
      zoneRedundancy      = var.zone_redundancy
    },
    # Only include encryption settings when all required CMK values are present.
    # Passing empty identity/keyIdentifier causes deployment failure. (null in the Bicep: left out)
    (var.cmk && var.cmk_identity_client_id != "" && var.cmk_key_vault_uri != "" && var.cmk_key_name != "") ? {
      encryption = {
        status = "enabled"
        keyVaultProperties = {
          identity      = var.cmk_identity_client_id
          keyIdentifier = "${var.cmk_key_vault_uri}keys/${var.cmk_key_name}"
        }
      }
    } : {},
    !var.enable_public_access_with_perimeter ? {
      networkRuleSet = {
        defaultAction = "Deny"
        ipRules       = local.unique_ip_rules
      }
    } : {}
  )

  deploy_private_endpoint = !var.enable_public_access_with_perimeter && var.sku_name == "Premium"
}

# 2025-05-01-preview matches the working portal-generated template.
# azapi (exact type + API version of the Bicep): azurerm_container_registry (5.12.0) has no trust policy
# (policies.trustPolicy type Notary), couples retention days with an enabled retention policy (the Bicep sends
# status 'disabled' with days 7), and uses a different, GA API version.
resource "azapi_resource" "container_registry" {
  type      = "Microsoft.ContainerRegistry/registries@2025-05-01-preview"
  name      = local.container_registry_name_cleaned
  parent_id = local.resource_group_id
  location  = var.location
  tags      = var.tags

  identity {
    type         = local.identity_type
    identity_ids = local.identity_ids
  }

  body = {
    sku = {
      name = var.sku_name
    }
    properties = local.properties
  }

  response_export_values = ["properties.loginServer"]
}

resource "azurerm_private_endpoint" "pend_acr" {
  count = local.deploy_private_endpoint ? 1 : 0

  name                          = var.private_endpoint_name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tags                          = var.tags
  subnet_id                     = local.subnet_id
  custom_network_interface_name = "${var.private_endpoint_name}-nic"

  # Bicep sets privateLinkServiceConnectionState Approved / Auto-Approved: an automatic (non-manual) connection to a
  # resource the caller owns is approved by ARM with exactly that state.
  private_service_connection {
    name                           = var.private_endpoint_name
    private_connection_resource_id = azapi_resource.container_registry.id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  # 13-rgLevel attaches the DNS zone group with privateDns.bicep (modules/private-dns); azurerm would remove it.
  lifecycle {
    ignore_changes = [private_dns_zone_group]
  }
}
