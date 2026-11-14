# Port of environment_setup/aifactory/bicep/esml-common/modules-common/nsgBastionNoWhitelist.bicep
# Same as nsg-bastion but without the Bastion_AllowHttpsInbound whitelist rule. ip_whitelist_array is accepted but unused (as in the Bicep).

locals {
  # Bicep: param networkWatcherName string = 'NetworkWatcher_${location}'
  network_watcher_name = var.network_watcher_name == null ? "NetworkWatcher_${var.location}" : var.network_watcher_name
  deploy_flow_log      = var.enable_flow_logs && var.storage_account_id != ""
}

# Inline security_rule blocks: the whole rule set is owned by this resource, like the Bicep PUT of securityRules.
resource "azurerm_network_security_group" "bastion_nsg" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "Bastion_GatewayManagerInbound"
    priority                   = 530
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "GatewayManager"
    destination_address_prefix = "*"
    description                = "Required for Bastion control plane"
  }

  security_rule {
    name                       = "Bastion_AzureLoadBalancerInbound"
    priority                   = 540
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = "*"
    description                = "This enables Azure Load Balancer to detect connectivity"
  }

  security_rule {
    name                       = "Bastion_HostCommunication"
    priority                   = 550
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_ranges    = ["8080", "5701"]
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "*"
    description                = "Data plane communication for Azure Bastion"
  }

  security_rule {
    name                       = "Bastion_SshOutbound"
    priority                   = 140
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_ranges    = ["22", "3389"]
    source_address_prefix      = "*"
    destination_address_prefix = "VirtualNetwork"
    description                = "Reach  target VMs over private IP, to other target VM subnets for port 3389 and 22"
  }

  security_rule {
    name                       = "Bastion_AzureCloudOutbound"
    priority                   = 150
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureCloud"
    description                = "Bastion needs to be able to connect to various public endpoints within Azure for storing logs."
  }

  security_rule {
    name                       = "Bastion_Communication"
    priority                   = 160
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_ranges    = ["8080", "5701"]
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "VirtualNetwork"
    description                = "Data plane communication for Azure Bastion"
  }

  security_rule {
    name                       = "Bastion_GetSessionInformation"
    priority                   = 170
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
    description                = "Bastion needs to be able to communicate with the Internet for session and certificate validation"
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

  target_resource_id = azurerm_network_security_group.bastion_nsg.id
  storage_account_id = var.storage_account_id
  enabled            = true
  version            = 2 # format: { type: 'JSON', version: 2 }

  retention_policy {
    days    = var.flow_log_retention_days
    enabled = true
  }
}
