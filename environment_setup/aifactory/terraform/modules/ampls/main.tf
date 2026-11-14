# Port of environment_setup/aifactory/bicep/modules/monitoring/ampls.bicep
# Azure Monitor Private Link Scope (AMPLS) for secure monitoring in a hub/spoke network architecture.

# azapi: the Bicep PUTs the scope with location = param location; azurerm_monitor_private_link_scope has no
# location argument (always 'Global'), so it cannot send the same location.
resource "azapi_resource" "ampls" {
  type      = "microsoft.insights/privateLinkScopes@2021-07-01-preview"
  name      = var.ampls_name
  parent_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  location  = var.location
  tags      = var.tags
  body = {
    properties = {
      accessModeSettings = {
        ingestionAccessMode = var.ingestion_access_mode
        queryAccessMode     = var.query_access_mode
      }
    }
  }
  response_export_values = ["properties.accessModeSettings"]
}

# Connect Log Analytics Workspaces to AMPLS ('law-${index}')
resource "azurerm_monitor_private_link_scoped_service" "log_analytics_connections" {
  count               = length(var.log_analytics_workspaces)
  name                = "law-${count.index}"
  resource_group_name = var.resource_group_name
  scope_name          = azapi_resource.ampls.name
  linked_resource_id  = var.log_analytics_workspaces[count.index].id
}

# Connect Application Insights Components to AMPLS ('ai-${index}')
resource "azurerm_monitor_private_link_scoped_service" "application_insights_connections" {
  count               = length(var.application_insights_components)
  name                = "ai-${count.index}"
  resource_group_name = var.resource_group_name
  scope_name          = azapi_resource.ampls.name
  linked_resource_id  = var.application_insights_components[count.index].id
}

# Connect Data Collection Endpoints to AMPLS ('dce-${index}')
resource "azurerm_monitor_private_link_scoped_service" "data_collection_endpoint_connections" {
  count               = length(var.data_collection_endpoints)
  name                = "dce-${count.index}"
  resource_group_name = var.resource_group_name
  scope_name          = azapi_resource.ampls.name
  linked_resource_id  = var.data_collection_endpoints[count.index].id
}
