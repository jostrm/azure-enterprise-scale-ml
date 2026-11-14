# Port of environment_setup/aifactory/bicep/modules/subnetWithNsg.bicep

# azapi (exact type + API version of the Bicep): azurerm_subnet cannot express serviceEndpoints[].locations
# (the Bicep pins every service endpoint to [location]); azurerm only has service + network_identifier.

locals {
  # Bicep 'existing'-style parent: resourceId('Microsoft.Network/virtualNetworks', virtualNetworkName) in the deployment RG.
  virtual_network_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.Network/virtualNetworks/${var.virtual_network_name}"
}

# Bicep: substring(uniqueString(name), 0, 12) in the delegation names
module "unique_name" {
  source = "../arm-unique-string"
  values = [var.name]
}

resource "azapi_resource" "snt" {
  type      = "Microsoft.Network/virtualNetworks/subnets@2023-05-01"
  name      = var.name
  parent_id = local.virtual_network_id

  body = {
    properties = {
      addressPrefix         = var.address_prefix
      defaultOutboundAccess = var.allow_default_outbound_access
      serviceEndpoints = [for x in var.service_endpoints : {
        service   = x
        locations = [var.location]
      }]
      delegations = [for x in var.delegations : {
        properties = {
          serviceName = x
        }
        name = "${lower(split("/", split(".", x)[0])[0])}-del-${substr(module.unique_name.value, 0, 12)}"
      }]
      privateEndpointNetworkPolicies    = var.private_endpoint_network_policies
      privateLinkServiceNetworkPolicies = var.private_link_service_network_policies
      # null is sent as JSON null, exactly like the Bicep's "!empty(x) ? {...} : null"
      routeTable = var.route_table_id != "" ? { id = var.route_table_id } : null
      networkSecurityGroup = {
        id = var.nsg_id
      }
      natGateway = var.nat_gateway_id != "" ? { id = var.nat_gateway_id } : null
    }
  }
}
