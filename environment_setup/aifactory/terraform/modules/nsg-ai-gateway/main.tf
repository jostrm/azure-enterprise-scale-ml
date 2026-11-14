# Port of environment_setup/aifactory/bicep/esml-common/modules-common/nsgAIGateway.bicep
# API Management NSG rules: inbound management endpoint, Azure infrastructure load balancer,
# AllowAzureTrafficManager (only for external), client connectivity to the gateway; outbound to Azure SQL,
# Storage, Event Hubs, Key Vault, Internet dependencies and AllowMonitor.

locals {
  # Bicep: param networkWatcherName string = 'NetworkWatcher_${location}'
  network_watcher_name = var.network_watcher_name == null ? "NetworkWatcher_${var.location}" : var.network_watcher_name
  deploy_flow_log      = var.enable_flow_logs && var.storage_account_id != ""
}

# Inline security_rule blocks: the whole rule set is owned by this resource, like the Bicep PUT of securityRules.
resource "azurerm_network_security_group" "ai_gateway_nsg" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "Client-Communication-To-API-Gateway"
    priority                   = 3000
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "Internet"
    destination_address_prefix = "VirtualNetwork"
    description                = "Client communication to API Gateway"
  }

  security_rule {
    name                       = "Management-Endpoint"
    priority                   = 3010
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3443"
    source_address_prefix      = "ApiManagement"
    destination_address_prefix = "VirtualNetwork"
    description                = "Allow management endpoint for API management"
  }

  security_rule {
    name                       = "Azure-Infrastructure-Load-Balancer"
    priority                   = 3020
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "6390"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = "VirtualNetwork"
    description                = "Allow Azure Infrastructure Load Balancer"
  }

  security_rule {
    name                       = "AllowAzureTrafficManager"
    priority                   = 3030
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "AzureTrafficManager"
    destination_address_prefix = "VirtualNetwork"
  }

  security_rule {
    name                       = "Azure-SQL-Access"
    priority                   = 3000
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "1433"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "Sql"
    description                = "Access to Azure SQL"
  }

  security_rule {
    name                       = "Azure-Storage-Access"
    priority                   = 3010
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "Storage"
    description                = "Access to Azure Storage"
  }

  security_rule {
    name                       = "Azure-KeyVault-Access"
    priority                   = 3020
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "AzureKeyVault"
    description                = "Access to Azure Key Vault"
  }

  security_rule {
    name                       = "Azure-EventHub-Access"
    priority                   = 3030
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5671-5672"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "EventHub"
    description                = "Access to Azure Event Hub"
  }

  security_rule {
    name                       = "Internet-Dependency-Access"
    priority                   = 3040
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "Internet"
    description                = "Access to dependencies hosted on Internet"
  }

  security_rule {
    name                       = "AllowMonitor"
    priority                   = 3050
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["1886", "443"]
    source_address_prefix      = "AzureMonitor"
    destination_address_prefix = "VirtualNetwork"
  }
}

# NSG Flow Logs - Note: This requires Network Watcher to exist in the target region.
# Bicep: Microsoft.Network/networkWatchers/flowLogs@2023-05-01 '${networkWatcherName}/flowlog-${name}'.
# azurerm_network_watcher_flow_log expresses every property used (targetResourceId, storageId, enabled,
# retentionPolicy, format JSON v2 via version = 2).
# The Bicep declares networkWatcherResourceGroup but does not use it: the flow log has no scope, so ARM addresses
# the watcher in the NSG's own resource group. Same here (network_watcher_resource_group is kept, unused).
resource "azurerm_network_watcher_flow_log" "nsg_flow_log" {
  count = local.deploy_flow_log ? 1 : 0

  name                 = "flowlog-${var.name}"
  network_watcher_name = local.network_watcher_name
  resource_group_name  = var.resource_group_name
  location             = var.location
  tags                 = var.tags

  target_resource_id = azurerm_network_security_group.ai_gateway_nsg.id
  storage_account_id = var.storage_account_id
  enabled            = true
  version            = 2 # format: { type: 'JSON', version: 2 }

  retention_policy {
    days    = var.flow_log_retention_days
    enabled = true
  }
}
