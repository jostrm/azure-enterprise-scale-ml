# Port of environment_setup/aifactory/bicep/esml-common/ai-gateway/14-add-networking-aigw.bicep
# Docs: https://github.com/Azure-Samples/ai-hub-gateway-solution-accelerator/blob/main/guides/bring-your-own-network.md
#
# The Bicep's uniqueDetermenistic salt (uniqueString of the vNet RG id / common RG name) is only used in nested
# deployment names, which have no Terraform equivalent, so it is not computed here.

locals {
  common_resource_group_name = "${var.common_rg_name_prefix}esml-common-${var.location_suffix}-${var.env}${var.aifactory_suffix_rg}"
  vnet_resource_group_name   = var.vnet_resource_group_param != "" ? replace(var.vnet_resource_group_param, "<network_env>", var.network_env) : local.common_resource_group_name
  vnet_name_full             = var.vnet_name_full_param != "" ? var.vnet_name_full_param : "${var.vnet_name_base}-${var.location_suffix}-${var.env}${var.common_resource_suffix}"

  # The subnet modules have no explicit scope in the Bicep: they go to this module's own deployment scope.
  deployment_resource_group_name = coalesce(var.resource_group_name, local.vnet_resource_group_name)

  # SUBNET - APIM
  # If there is a forced tunneling applied on the subnet (directly through route table or in-directly through BGP),
  # you need to enable service endpoints for the following services (only on the APIM subnet)
  apim_subnet_settings = {
    cidr        = var.cidr_apim
    name        = "apimSubnetSettings"
    delegations = []
    service_endpoints = [
      "Microsoft.AzureActiveDirectory",
      "Microsoft.EventHub",
      "Microsoft.KeyVault",
      "Microsoft.ServiceBus",
      "Microsoft.Sql",
      "Microsoft.Storage",
    ]
  }

  # SUBNET - FUNCTION APP
  function_app_subnet_settings = {
    cidr = var.cidr_function_app
    name = "functionAppSubnetSettings"
    delegations = [
      "Microsoft.Web/serverFarms",
    ]
    service_endpoints = [
      "Microsoft.KeyVault",
      "Microsoft.Storage",
      "Microsoft.CognitiveServices",
      "Microsoft.ContainerRegistry",
      "Microsoft.AzureCosmosDB",
      "Microsoft.Web",
    ]
  }
}

module "nsg_ai_gateway" {
  source = "../nsg-ai-gateway"

  name                = "nsg-${var.name}-apim"
  tags                = var.tags
  location            = var.location
  resource_group_name = local.vnet_resource_group_name
}

# If this subnet has a route table, it should include a route to handle APIM management control plane traffic.
module "route_table_ai_gateway" {
  source = "../route-table-ai-gateway"

  name                = "rt-${var.name}"
  tags                = var.tags
  location            = var.location
  resource_group_name = local.vnet_resource_group_name
}

module "subnet_apim_ai_gw" {
  source = "../subnet-with-nsg"

  name                              = "snt-${var.name}-apim"
  virtual_network_name              = local.vnet_name_full
  address_prefix                    = local.apim_subnet_settings.cidr
  location                          = var.location
  service_endpoints                 = local.apim_subnet_settings.service_endpoints
  delegations                       = local.apim_subnet_settings.delegations
  route_table_id                    = module.route_table_ai_gateway.id
  nsg_id                            = module.nsg_ai_gateway.id
  central_dns_zone_by_policy_in_hub = var.central_dns_zone_by_policy_in_hub
  subscription_id                   = var.subscription_id_dev_test_prod
  resource_group_name               = local.deployment_resource_group_name

  # Bicep dependsOn: vnetResourceGroup, nsgAIGateway, routeTableAIGateway (the last two are implicit via the ids)
}

module "nsg_function_app" {
  source = "../nsg-function-app"

  name                = "nsg-${var.name}-function-app"
  tags                = var.tags
  location            = var.location
  resource_group_name = local.vnet_resource_group_name
}

module "subnet_function_app" {
  source = "../subnet-with-nsg"

  name                              = "snt-${var.name}-function-app"
  virtual_network_name              = local.vnet_name_full
  address_prefix                    = local.function_app_subnet_settings.cidr
  location                          = var.location
  service_endpoints                 = local.function_app_subnet_settings.service_endpoints
  delegations                       = local.function_app_subnet_settings.delegations
  nsg_id                            = module.nsg_function_app.id
  central_dns_zone_by_policy_in_hub = var.central_dns_zone_by_policy_in_hub
  subscription_id                   = var.subscription_id_dev_test_prod
  resource_group_name               = local.deployment_resource_group_name

  depends_on = [module.subnet_apim_ai_gw]
}
