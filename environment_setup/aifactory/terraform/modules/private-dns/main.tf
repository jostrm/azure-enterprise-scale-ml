# Port of environment_setup/aifactory/bicep/modules/privateDns.bicep

locals {
  # [for obj in dnsConfig: if(!empty(obj.name))] - keyed by the private endpoint name.
  dns_config = { for obj in var.dns_config : obj.name => obj if obj.name != "" }
}

# azapi: azurerm has no standalone private DNS zone group resource (only the private_dns_zone_group block
# inside azurerm_private_endpoint, which belongs to the module that owns the endpoint). The endpoint itself
# ('existing' in Bicep, the parent of '${obj.name}/...') is addressed by its ARM resource ID.
resource "azapi_resource" "private_endpoint_dns_zone" {
  for_each  = local.dns_config
  type      = "Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01"
  name      = "${each.value.name}DnsZone"
  parent_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.Network/privateEndpoints/${each.value.name}"
  body = {
    properties = {
      privateDnsZoneConfigs = [
        {
          name = each.value.name
          properties = {
            privateDnsZoneId = var.private_links_dns_zones[each.value.type].id
          }
        }
      ]
    }
  }
}
