# Port of environment_setup/aifactory/bicep/esml-common/modules-common/vNetCommonPreserve.bicep

locals {
  # 'existing' retainedVnet -> built resourceId('Microsoft.Network/virtualNetworks', vnetNameFull)
  retained_vnet_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.Network/virtualNetworks/${var.vnet_name_full}"

  # Bicep: [for subnet in plan.createSubnets: ...] -> keyed by subnet name (stable key)
  missing_subnets = { for subnet in var.plan.createSubnets : subnet.name => subnet }
}

# ARM deployment mode is not create-only: the coordinator must hold the hub lease
# and revalidate absence immediately before deploying this initial parent resource.
# (Terraform's create additionally refuses to adopt an already existing vNet: it must be imported.)
# Only addressSpace is set, like the Bicep (no subnets in the body).
resource "azurerm_virtual_network" "initial_vnet" {
  count = var.plan.createVnet ? 1 : 0

  name                = var.vnet_name_full
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
  address_space       = var.plan.addressPrefixes

  lifecycle {
    # Add-only plan: Bicep never deletes. A later plan with createVnet = false (vNet now exists) would make Terraform
    # destroy this instance; fail instead of deleting shared hub networking (Terraform-specific guard).
    prevent_destroy = true
  }
}

# azapi: subnet.properties is an arbitrary pass-through object from the preservation plan; azurerm_subnet cannot take
# a raw ARM property bag. Exact Bicep type + API version.
resource "azapi_resource" "missing_subnets" {
  for_each = local.missing_subnets

  type      = "Microsoft.Network/virtualNetworks/subnets@2023-11-01"
  name      = each.value.name
  parent_id = local.retained_vnet_id

  body = {
    properties = each.value.properties
  }

  # @batchSize(1): serialize the subnet PUTs on the parent vNet.
  locks = [local.retained_vnet_id]

  lifecycle {
    prevent_destroy = true # add-only, see initial_vnet
  }

  depends_on = [azurerm_virtual_network.initial_vnet]
}
