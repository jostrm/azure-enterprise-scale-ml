# Port of environment_setup/aifactory/bicep/esml-common/modules-common/routeTableAIGateway.bicep

resource "azurerm_route_table" "apim_route_table" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = merge(var.tags, { "azd-service-name" = var.name })

  route {
    name           = "apim-management"
    address_prefix = "ApiManagement"
    next_hop_type  = "Internet"
  }
  # Add additional routes as required
}
