# Port of environment_setup/aifactory/bicep/modules/monitoring/amplsHubSimple.bicep
# Azure Monitor Private Link Scope - simplified hub deployment (hub/spoke). DCE and AMPLS are deployed by
# separate modules, as in the Bicep.

locals {
  ampls_name            = "ampls-${var.location_suffix}-${var.env}${var.common_resource_suffix}"
  private_endpoint_name = "pe-ampls-${var.location_suffix}-${var.env}${var.common_resource_suffix}"
  dce_name              = "dce-${var.location_suffix}-${var.env}${var.common_resource_suffix}"

  # hubVnet/hubSubnet 'existing' -> ARM resource ID (resourceGroup(hubVnetResourceGroup) keeps this subscription).
  hub_subnet_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.hub_vnet_resource_group}/providers/Microsoft.Network/virtualNetworks/${var.hub_vnet_name}/subnets/${var.hub_subnet_name}"
}

# DATA COLLECTION ENDPOINTS
module "data_collection_endpoint" {
  source              = "../data-collection-endpoint"
  dce_name            = local.dce_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
  dce_description     = "Data Collection Endpoint for Azure Monitor Private Link - ${var.env} environment"
  kind                = "Linux"

  enable_public_network_access = false
}

# AZURE MONITOR PRIVATE LINK SCOPE
module "azure_monitor_private_link_scope" {
  source                          = "../ampls"
  ampls_name                      = local.ampls_name
  subscription_id                 = var.subscription_id
  resource_group_name             = var.resource_group_name
  location                        = var.location
  tags                            = var.tags
  ingestion_access_mode           = var.ingestion_access_mode
  query_access_mode               = var.query_access_mode
  log_analytics_workspaces        = var.log_analytics_workspaces
  application_insights_components = var.application_insights_components
  data_collection_endpoints = [
    {
      id = module.data_collection_endpoint.dce_id
    }
  ]
  enable_network_isolation = true

  depends_on = [module.data_collection_endpoint]
}

# PRIVATE ENDPOINTS
module "ampls_private_endpoint" {
  source                = "../ampls-private-endpoint"
  private_endpoint_name = local.private_endpoint_name
  resource_group_name   = var.resource_group_name
  location              = var.location
  tags                  = var.tags
  subnet_id             = local.hub_subnet_id
  ampls_id              = module.azure_monitor_private_link_scope.ampls_id
  private_dns_zone_configs = [
    {
      name                         = "privatelink-monitor-azure-com"
      private_dns_zone_resource_id = var.private_dns_zone_resource_ids.monitor
    },
    {
      name                         = "privatelink-oms-opinsights-azure-com"
      private_dns_zone_resource_id = var.private_dns_zone_resource_ids.oms
    },
    {
      name                         = "privatelink-ods-opinsights-azure-com"
      private_dns_zone_resource_id = var.private_dns_zone_resource_ids.ods
    },
    {
      name                         = "privatelink-agentsvc-azure-automation-net"
      private_dns_zone_resource_id = var.private_dns_zone_resource_ids.agentsvc
    },
  ]
  enable_private_dns_zone_group = true

  depends_on = [module.azure_monitor_private_link_scope]
}
