# Port of environment_setup/aifactory/bicep/modules/createPrivateDnsZones.bicep

locals {
  location_global = "global" # Using default Microsoft Private DNS, they are registered in global.

  # vnet 'existing' -> resource ID built like ARM resourceId() (no plan-time read). The Bicep scope
  # resourceGroup(vNetResourceGroup) keeps the subscription of the deployment scope (the DNS subscription).
  vnet_id = "/subscriptions/${var.priv_dns_subscription}/resourceGroups/${var.v_net_resource_group}/providers/Microsoft.Network/virtualNetworks/${var.v_net_name}"

  zones = {
    for zone in var.private_links_dns_zones : zone.name => {
      # ARM id of the zone, as privateDnsZones[i].id (input of uniqueString() for the link name).
      id       = "/subscriptions/${var.priv_dns_subscription}/resourceGroups/${var.priv_dns_resource_group}/providers/Microsoft.Network/privateDnsZones/${zone.name}"
      location = (zone.name == "${var.location}.data.privatelink.azurecr.io" && var.all_global == false) ? var.location : local.location_global
    }
  }
  global_zones   = { for k, z in local.zones : k => z if z.location == local.location_global }
  regional_zones = { for k, z in local.zones : k => z if z.location != local.location_global }
}

# Link name: '${zone}/${uniqueString(privateDnsZones[i].id)}'
module "unique_link_name" {
  source   = "../arm-unique-string"
  for_each = local.zones
  values   = [each.value.id]
}

# Global zones (the default and the only case in 13-rgLevel): azurerm_private_dns_zone is always 'global'.
resource "azurerm_private_dns_zone" "zone" {
  for_each            = local.global_zones
  name                = each.key
  resource_group_name = var.priv_dns_resource_group
}

# Regional zone ('<location>.data.privatelink.azurecr.io' with all_global = false): azapi, because
# azurerm_private_dns_zone cannot set a location other than 'global'.
resource "azapi_resource" "zone_regional" {
  for_each  = local.regional_zones
  type      = "Microsoft.Network/privateDnsZones@2024-06-01"
  name      = each.key
  parent_id = "/subscriptions/${var.priv_dns_subscription}/resourceGroups/${var.priv_dns_resource_group}"
  location  = each.value.location
  body = {
    properties = {}
  }
}

resource "azurerm_private_dns_zone_virtual_network_link" "link" {
  for_each             = local.global_zones
  name                 = module.unique_link_name[each.key].value
  private_dns_zone_id  = azurerm_private_dns_zone.zone[each.key].id
  registration_enabled = false              # No auto-registration of VM records in the zone
  resolution_policy    = "NxDomainRedirect" # 'Default' or 'NxDomainRedirect'
  virtual_network_id   = local.vnet_id
}

# Regional link: azapi for the same reason as the regional zone (azurerm links are always 'global').
resource "azapi_resource" "link_regional" {
  for_each  = local.regional_zones
  type      = "Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01"
  name      = module.unique_link_name[each.key].value
  parent_id = azapi_resource.zone_regional[each.key].id
  location  = each.value.location
  body = {
    properties = {
      registrationEnabled = false
      resolutionPolicy    = "NxDomainRedirect"
      virtualNetwork = {
        id = local.vnet_id
      }
    }
  }
}
