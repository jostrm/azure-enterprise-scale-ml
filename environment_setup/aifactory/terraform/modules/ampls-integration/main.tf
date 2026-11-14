# Port of environment_setup/aifactory/bicep/modules/monitoring/amplsIntegration.bicep
# Integrates Azure Monitor Private Link Scope with the AI Factory foundation (hub/spoke).
#
# Scope: the Bicep deploys amplsHubSimple to resourceGroup(targetSubscription, targetResourceGroup). Terraform
# modules cannot switch subscription internally: the azapi resources use target_subscription in their parent_id,
# and the azurerm resources use the provider passed by the caller, which must be for target_subscription
# (providers = { azurerm = azurerm.private_dns } when deploy_to_hub_resource_group is true).

locals {
  target_resource_group = var.deploy_to_hub_resource_group ? var.priv_dns_resource_group : var.resource_group_name
  target_subscription   = var.deploy_to_hub_resource_group ? var.priv_dns_subscription : var.subscription_id

  # Private DNS Zone resource IDs
  private_dns_zone_resource_ids = {
    monitor  = "/subscriptions/${var.priv_dns_subscription}/resourceGroups/${var.priv_dns_resource_group}/providers/Microsoft.Network/privateDnsZones/privatelink.monitor.azure.com"
    oms      = "/subscriptions/${var.priv_dns_subscription}/resourceGroups/${var.priv_dns_resource_group}/providers/Microsoft.Network/privateDnsZones/privatelink.oms.opinsights.azure.com"
    ods      = "/subscriptions/${var.priv_dns_subscription}/resourceGroups/${var.priv_dns_resource_group}/providers/Microsoft.Network/privateDnsZones/privatelink.ods.opinsights.azure.com"
    agentsvc = "/subscriptions/${var.priv_dns_subscription}/resourceGroups/${var.priv_dns_resource_group}/providers/Microsoft.Network/privateDnsZones/privatelink.agentsvc.azure-automation.net"
  }

  # Convert existing resource IDs to the format expected by the AMPLS module
  log_analytics_workspaces        = [for workspace_id in var.existing_log_analytics_workspace_ids : { id = workspace_id }]
  application_insights_components = [for app_insights_id in var.existing_application_insights_ids : { id = app_insights_id }]
}

# AMPLS DEPLOYMENT
module "ampls_deployment" {
  source                          = "../ampls-hub-simple"
  subscription_id                 = local.target_subscription
  resource_group_name             = local.target_resource_group
  env                             = var.env
  location                        = var.location
  location_suffix                 = var.location_suffix
  common_resource_suffix          = var.common_resource_suffix
  tags                            = var.tags
  hub_vnet_name                   = var.hub_vnet_name
  hub_vnet_resource_group         = var.hub_vnet_resource_group
  hub_subnet_name                 = var.monitoring_subnet_name
  log_analytics_workspaces        = local.log_analytics_workspaces
  application_insights_components = local.application_insights_components
  private_dns_zone_resource_ids   = local.private_dns_zone_resource_ids
  ingestion_access_mode           = var.ingestion_access_mode
  query_access_mode               = var.query_access_mode
}
