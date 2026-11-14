# Port of environment_setup/aifactory/bicep/modules/monitoring/amplsPrivateEndpoint.bicep
# Private endpoint for Azure Monitor Private Link Scope, integrated with private DNS zones.

resource "azurerm_private_endpoint" "private_endpoint" {
  name                = var.private_endpoint_name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
  subnet_id           = var.subnet_id

  private_service_connection {
    name                           = "${var.private_endpoint_name}-connection"
    private_connection_resource_id = var.ampls_id
    subresource_names              = ["azuremonitor"]
    is_manual_connection           = false
  }

  # The zone group is a separate child resource below (as in the Bicep).
  lifecycle {
    ignore_changes = [private_dns_zone_group]
  }
}

# azapi: the Bicep names each privateDnsZoneConfig (e.g. 'privatelink-monitor-azure-com'); the azurerm
# private_dns_zone_group block names the configs after the zones and cannot set these names.
resource "azapi_resource" "private_dns_zone_group" {
  count     = var.enable_private_dns_zone_group ? 1 : 0
  type      = "Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01"
  name      = "default"
  parent_id = azurerm_private_endpoint.private_endpoint.id
  body = {
    properties = {
      privateDnsZoneConfigs = [
        for config in var.private_dns_zone_configs : {
          name = config.name
          properties = {
            privateDnsZoneId = config.private_dns_zone_resource_id
          }
        }
      ]
    }
  }
}
