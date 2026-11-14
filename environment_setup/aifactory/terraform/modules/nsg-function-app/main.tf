# Port of environment_setup/aifactory/bicep/esml-common/modules-common/nsgFunctionApp.bicep
# Azure Function App (Premium plan with VNet integration) NSG rules: inbound HTTP/HTTPS, Azure Load Balancer,
# App Service management (454), default deny; outbound SQL, Storage, AAD, App Insights, Event Hub, Key Vault, Internet (443).

locals {
  # Bicep: param networkWatcherName string = 'NetworkWatcher_${location}'
  network_watcher_name = var.network_watcher_name == null ? "NetworkWatcher_${var.location}" : var.network_watcher_name
  deploy_flow_log      = var.enable_flow_logs && var.storage_account_id != ""
}

# Inline security_rule blocks: the whole rule set is owned by this resource, like the Bicep PUT of securityRules.
resource "azurerm_network_security_group" "function_app_nsg" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "Allow-HTTP-HTTPS"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
    description                = "Allow HTTP/HTTPS traffic to Function App"
  }

  security_rule {
    name                       = "Allow-AzureLoadBalancer"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = "*"
    description                = "Allow Azure Load Balancer inbound traffic"
  }

  security_rule {
    name                       = "Allow-AppService-Management"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "454"
    source_address_prefix      = "AppService"
    destination_address_prefix = "*"
    description                = "Allow Function App management traffic"
  }

  security_rule {
    name                       = "Deny-All-Inbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
    description                = "Deny all other inbound traffic"
  }

  security_rule {
    name                       = "Allow-SQL"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "1433"
    source_address_prefix      = "*"
    destination_address_prefix = "Sql"
    description                = "Allow access to Azure SQL"
  }

  security_rule {
    name                       = "Allow-Storage"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "Storage"
    description                = "Allow access to Azure Storage"
  }

  security_rule {
    name                       = "Allow-AAD"
    priority                   = 120
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureActiveDirectory"
    description                = "Allow access to Azure Active Directory"
  }

  security_rule {
    name                       = "Allow-AppInsights-AzureMonitor"
    priority                   = 130
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["1886", "443"]
    source_address_prefix      = "*"
    destination_address_prefix = "AzureMonitor"
    description                = "Allow access to Application Insights"
  }

  security_rule {
    name                       = "Allow-EventHub"
    priority                   = 140
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "EventHub"
    description                = "Allow access to Event Hub"
  }

  security_rule {
    name                       = "Allow-KeyVault"
    priority                   = 150
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureKeyVault"
    description                = "Allow access to Key Vault"
  }

  security_rule {
    name                       = "Allow-Internet"
    priority                   = 160
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
    description                = "Allow general outbound internet access for dependencies"
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

  target_resource_id = azurerm_network_security_group.function_app_nsg.id
  storage_account_id = var.storage_account_id
  enabled            = true
  version            = 2 # format: { type: 'JSON', version: 2 }

  retention_policy {
    days    = var.flow_log_retention_days
    enabled = true
  }
}
