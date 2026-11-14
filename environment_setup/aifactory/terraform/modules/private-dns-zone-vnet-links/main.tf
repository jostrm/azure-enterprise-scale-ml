# Port of environment_setup/aifactory/bicep/modules/networking/privateDnsZoneVnetLinks.bicep
# Links existing private DNS zones (in this resource group) to one more VNet. Used by 13-rgLevel when an added
# scale set joins the factory's own access hub: the bootstrap created the zones and linked them to the hub VNet
# only. The zones are referenced, never PUT again. The link name is derived from the VNet id, so re-runs PUT the
# same link and every added scale set gets its own.

locals {
  location_global = "global"

  # zones 'existing' -> ARM resource IDs built like resourceId() (no plan-time read).
  zones = {
    for zone in var.private_links_dns_zones : zone.name => {
      id       = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.Network/privateDnsZones/${zone.name}"
      location = (zone.name == "${var.location}.data.privatelink.azurecr.io" && var.all_global == false) ? var.location : local.location_global
    }
  }
  global_zones   = { for k, z in local.zones : k => z if z.location == local.location_global }
  regional_zones = { for k, z in local.zones : k => z if z.location != local.location_global }

  # take('${last(split(vnetId, '/'))}-${uniqueString(vnetId)}', 80)
  link_name = substr("${element(split("/", var.vnet_id), length(split("/", var.vnet_id)) - 1)}-${module.unique_vnet.value}", 0, 80)
}

module "unique_vnet" {
  source = "../arm-unique-string"
  values = [var.vnet_id]
}

resource "azurerm_private_dns_zone_virtual_network_link" "zone_links" {
  for_each             = local.global_zones
  name                 = local.link_name
  private_dns_zone_id  = each.value.id
  registration_enabled = false
  resolution_policy    = "NxDomainRedirect"
  virtual_network_id   = var.vnet_id
}

# Regional link ('<location>.data.privatelink.azurecr.io' with all_global = false): azapi, because
# azurerm_private_dns_zone_virtual_network_link is always in location 'global'.
resource "azapi_resource" "zone_links_regional" {
  for_each  = local.regional_zones
  type      = "Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01"
  name      = local.link_name
  parent_id = each.value.id
  location  = each.value.location
  body = {
    properties = {
      registrationEnabled = false
      resolutionPolicy    = "NxDomainRedirect"
      virtualNetwork = {
        id = var.vnet_id
      }
    }
  }
}
