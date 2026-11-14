# Port of environment_setup/aifactory/bicep/esml-common/modules-common/nsgCommon.bicep
# TODO (from Bicep): outbound connection to ports 443, 445 for storage service tag
# The commented-out DEBUG_AllowAllInbound_TEMPORARY / DEBUG_AllowAllOutbound_TEMPORARY rules of the Bicep are not ported (commented out there too).
# All rule priorities live in the 1000+ range so that 100-999 stays free for future higher-priority overrides.

locals {
  # Bicep: param networkWatcherName string = 'NetworkWatcher_${location}'
  network_watcher_name = var.network_watcher_name == null ? "NetworkWatcher_${var.location}" : var.network_watcher_name
  deploy_flow_log      = var.enable_flow_logs && var.storage_account_id != ""
}

# Inline security_rule blocks: the whole rule set is owned by this resource, like the Bicep PUT of securityRules.
resource "azurerm_network_security_group" "cmn_nsg" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "AML_CI_44224"
    priority                   = 1200
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "44224"
    source_address_prefix      = "AzureMachineLearning"
    destination_address_prefix = "*"
    description                = "Required for Azure Machine Learning"
  }

  security_rule {
    name                       = "AML_Port_29876-29877"
    priority                   = 1100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "29876-29877"
    source_address_prefix      = "BatchNodeManagement"
    destination_address_prefix = "*"
    description                = "Required for Azure Machine Learning batch compute nodes"
  }

  security_rule {
    name                       = "Bastion_GetSessionInformation"
    priority                   = 1300
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["22", "3389"]
    source_address_prefix      = var.bastion_ip_range
    destination_address_prefix = "*"
    description                = "Bastion will reach to the VM (DSVM / jump server) over private IP. RDP/SSH ports 3389/22. NB! Change the IP range if not working"
  }

  security_rule {
    name                       = "Allow_VNet_Inbound"
    priority                   = 1000
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "VirtualNetwork"
    description                = "Allow all inbound traffic from any subnet in the same VNet (all ports, all protocols)."
  }

  security_rule {
    name                       = "Allow_APIM"
    priority                   = 1010
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3443"
    source_address_prefix      = "ApiManagement"
    destination_address_prefix = "*"
    description                = "Allow inbound from Azure API Management control plane (port 3443)."
  }

  security_rule {
    name                       = "DenyAllInboundExceptExplicit"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
    description                = "Deny all other inbound traffic not explicitly allowed above"
  }

  security_rule {
    name                         = "AzureDevOps_Allow_1"
    priority                     = 2000
    direction                    = "Outbound"
    access                       = "Allow"
    protocol                     = "*"
    source_port_range            = "*"
    destination_port_range       = "*"
    source_address_prefix        = "VirtualNetwork"
    destination_address_prefixes = ["13.107.6.0/24", "13.107.9.0/24", "13.107.42.0/24", "13.107.43.0/24"]
    description                  = "Required for communication to Azure Devops. Needed to checkin code"
  }

  security_rule {
    name                       = "AzureActiveDirectoryDomainServices_Allow"
    priority                   = 2050
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureActiveDirectoryDomainServices"
    description                = "Required for Azure Active Directory Domain Services communication"
  }

  security_rule {
    name                       = "AADLoginForWindows_Allow3services"
    priority                   = 2100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
    description                = "To enable Azure AD authentication for Windows VMs."
  }

  security_rule {
    name                       = "AADLoginForWindows_AllowServiceMeta"
    priority                   = 2200
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "169.254.169.254"
    description                = "To enable Azure AD authentication for Windows VMs."
  }

  security_rule {
    name                       = "AzureActiveDirectory"
    priority                   = 2300
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureActiveDirectory"
    description                = "AML - Azure AD authentication (HTTPS only)"
  }

  security_rule {
    name                       = "AzureMachineLearningOutbound"
    priority                   = 2400
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureMachineLearning"
    description                = "AML !!"
  }

  security_rule {
    name                       = "AzureResourceManager"
    priority                   = 2500
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureResourceManager"
    description                = "AML !!"
  }

  security_rule {
    name                       = "AzureStorageAccount"
    priority                   = 2600
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["443", "445"]
    source_address_prefix      = "*"
    destination_address_prefix = "Storage.${var.location}"
    description                = "AML - Azure Storage (HTTPS and SMB)"
  }

  security_rule {
    name                       = "AzureFrontDoor"
    priority                   = 2700
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureFrontDoor.FrontEnd"
    description                = "AML !!"
  }

  security_rule {
    name                       = "AzureFrontDoorFirstParty"
    priority                   = 2710
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureFrontDoor.FirstParty"
    description                = "Required for MCR pulls — MCR layers/manifests are served via FrontDoor FirstParty backend (AKS/ACA system images)."
  }

  security_rule {
    name                       = "AzureMonitor"
    priority                   = 2720
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureMonitor"
    description                = "Required for AKS / ACA / VM log + metric egress (Container Insights, Log Analytics, App Insights)."
  }

  security_rule {
    name                       = "AzureContainerRegistry"
    priority                   = 2800
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureContainerRegistry.${var.location}"
    description                = "AML !!"
  }

  security_rule {
    name                       = "MicrosoftContainerRegistry"
    priority                   = 2900
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "MicrosoftContainerRegistry"
    description                = "AML !!"
  }

  security_rule {
    name                       = "AKS_private_loadbalancer_call_from_DSVM_in_vNet"
    priority                   = 1600
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "VirtualNetwork"
    description                = "Required for communication from private DSVM to call private AKS cluster endpoints. Needed for Azure ML inferencing."
  }

  security_rule {
    name                       = "AzureMachineLearning_2023_sdkv2_1"
    priority                   = 3100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Udp"
    source_port_range          = "*"
    destination_port_range     = "5831"
    source_address_prefix      = "*"
    destination_address_prefix = "AzureMachineLearning"
    description                = "Required for 2023 Mars update, to support Azure ML SDK v2"
  }

  security_rule {
    name                       = "AzureMachineLearning_2023_sdkv2_2"
    priority                   = 3300
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5831"
    source_address_prefix      = "*"
    destination_address_prefix = "BatchNodeManagement.${var.location}"
    description                = "Required for 2023 Mars update, to support Azure ML SDK v2"
  }

  security_rule {
    name                       = "AzureMachineLearning_2023_sdkv2_3"
    priority                   = 3200
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["8787", "18881"]
    source_address_prefix      = "*"
    destination_address_prefix = "AzureMachineLearning"
    description                = "Required for 2023 Mars update, to support Azure ML SDK v2"
  }

  security_rule {
    name                       = "AzureDataFactory_Portal"
    priority                   = 3400
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
    description                = "Required for Data Factory portal authoring and monitoring"
  }

  security_rule {
    name                       = "AzureDataFactory_SelfHostedIR"
    priority                   = 3500
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "DataFactory.${var.location}"
    description                = "Required for self-hosted IR to connect to Data Factory"
  }

  security_rule {
    name                       = "ServiceBus_InteractiveAuthoring"
    priority                   = 3600
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "ServiceBus"
    description                = "Required for self-hosted IR interactive authoring"
  }

  security_rule {
    name                       = "Microsoft_Downloads"
    priority                   = 3700
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
    description                = "Required for self-hosted IR updates from Microsoft"
  }

  security_rule {
    name                       = "Allow_VNet_Outbound"
    priority                   = 1000
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "VirtualNetwork"
    description                = "Allow all outbound traffic to any subnet in the same VNet (all ports, all protocols)."
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

  target_resource_id = azurerm_network_security_group.cmn_nsg.id
  storage_account_id = var.storage_account_id
  enabled            = true
  version            = 2 # format: { type: 'JSON', version: 2 }

  retention_policy {
    days    = var.flow_log_retention_days
    enabled = true
  }
}
