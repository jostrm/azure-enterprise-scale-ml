# Port of environment_setup/aifactory/bicep/esml-common/modules-common/nsgPowerBI.bicep
# Inbound: none. See https://docs.microsoft.com/en-us/power-bi/enterprise/service-security-private-links

locals {
  # Bicep: param networkWatcherName string = 'NetworkWatcher_${location}'
  network_watcher_name = var.network_watcher_name == null ? "NetworkWatcher_${var.location}" : var.network_watcher_name
  deploy_flow_log      = var.enable_flow_logs && var.storage_account_id != ""
}

# Inline security_rule blocks: the whole rule set is owned by this resource, like the Bicep PUT of securityRules.
resource "azurerm_network_security_group" "pbi_nsg" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "AzureActiveDirectory"
    priority                   = 130
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureActiveDirectory"
    description                = "Optional"
  }

  security_rule {
    name                       = "AzureStorageAccount"
    priority                   = 160
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "Storage.${var.location}"
    description                = "Optional"
  }

  security_rule {
    name                       = "AzureFrontDoor"
    priority                   = 170
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureFrontDoor.FrontEnd"
    description                = "Optional"
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

  target_resource_id = azurerm_network_security_group.pbi_nsg.id
  storage_account_id = var.storage_account_id
  enabled            = true
  version            = 2 # format: { type: 'JSON', version: 2 }

  retention_policy {
    days    = var.flow_log_retention_days
    enabled = true
  }
}
