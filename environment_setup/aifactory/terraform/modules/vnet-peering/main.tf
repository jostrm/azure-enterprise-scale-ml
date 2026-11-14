# Port of environment_setup/aifactory/bicep/modules/networking/vnetPeering.bicep
# One side of a VNet peering, in the resource group of the local VNet. Used by 13-rgLevel when an added scale set
# joins the factory's own access hub: hub -> spoke (allow_gateway_transit) first, then spoke -> hub
# (use_remote_gateways). Same properties as bootstrap/lib/common_network_preservation.plan_peerings.

resource "azurerm_virtual_network_peering" "peering" {
  name                         = var.peering_name
  resource_group_name          = var.resource_group_name
  virtual_network_name         = var.vnet_name
  remote_virtual_network_id    = var.remote_vnet_id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
  allow_gateway_transit        = var.allow_gateway_transit
  use_remote_gateways          = var.use_remote_gateways
}
