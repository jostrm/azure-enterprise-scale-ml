# Port of environment_setup/aifactory/bicep/modules/monitoring/dataCollectionEndpoint.bicep
# Data Collection Endpoint for Azure Monitor Agent private link scenarios.

resource "azurerm_monitor_data_collection_endpoint" "data_collection_endpoint" {
  name                          = var.dce_name
  resource_group_name           = var.resource_group_name
  location                      = var.location
  tags                          = var.tags
  kind                          = var.kind
  description                   = var.dce_description
  public_network_access_enabled = var.enable_public_network_access # networkAcls.publicNetworkAccess Enabled/Disabled
}
