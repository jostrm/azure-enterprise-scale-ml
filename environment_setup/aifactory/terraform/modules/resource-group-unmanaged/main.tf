# Port of environment_setup/aifactory/bicep/modules/resourcegroupUnmanaged.bicep

# Subscription scope. No managed_by is set on purpose:
# Why? to avoid this error message: "The managed by property of the resource group cannot be changed from its current value"
# When? If RG created with contactperson A, and other person B is set to ContactPerson, and RG needs update - error will occur.
resource "azurerm_resource_group" "common_resource_un_managed" {
  name     = var.rg_name
  location = var.location
  tags     = var.tags
}
