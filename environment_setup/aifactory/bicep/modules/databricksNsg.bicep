@description('Specifies the name of the databricks network security group')
param name string

@description('Specifies the location where the databricks network security group should be deployed. Defaults to resourceGroup.location')
param location string

@description('Specifies the tags that should be applied to the databricks network security group')
param tags object

resource dbxNsg 'Microsoft.Network/networkSecurityGroups@2020-06-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    securityRules: [
      // --- Inbound ---
      // All rule priorities live in the 1000+ range so that 100-999 stays free for future higher-priority overrides.
      // Lower number = higher priority. VNet-wide allow sits at 1000 (highest).
      {
        name: 'Allow_VNet_Inbound'
        properties: {
          description: 'Allow all inbound traffic from any subnet in the same VNet (all ports, all protocols).'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'VirtualNetwork'
          access: 'Allow'
          priority: 1000
          direction: 'Inbound'
        }
      }
      {
        name: 'Allow_APIM'
        properties: {
          description: 'Allow inbound from Azure API Management control plane (port 3443).'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '3443'
          sourceAddressPrefix: 'ApiManagement'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1010
          direction: 'Inbound'
        }
      }
      {
        name: 'Microsoft.Databricks-workspaces_UseOnly_databricks-worker-to-worker-inbound'
        properties: {
          description: 'Required for worker nodes communication within a cluster.'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'VirtualNetwork'
          access: 'Allow'
          priority: 1020
          direction: 'Inbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: []
          destinationAddressPrefixes: []
        }
      }
      {
        name: 'Microsoft.Databricks-workspaces_UseOnly_databricks-control-plane-to-worker-ssh'
        properties: {
            description: 'Required for Databricks control plane management of worker nodes.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '22'
            sourceAddressPrefix: 'AzureDatabricks'
            destinationAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 1030
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Microsoft.Databricks-workspaces_UseOnly_databricks-control-plane-to-worker-proxy'
        properties: {
            description: 'Required for Databricks control plane communication with worker nodes.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '5557'
            sourceAddressPrefix: 'AzureDatabricks'
            destinationAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 1040
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      // --- Outbound --- 
      // Same 1000+ convention as Inbound. VNet-wide allow at 1000 (highest).
      {
        name: 'Allow_VNet_Outbound'
        properties: {
            description: 'Allow all outbound traffic to any subnet in the same VNet (all ports, all protocols).'
            protocol: '*'
            sourcePortRange: '*'
            destinationPortRange: '*'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 1000
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Microsoft.Databricks-workspaces_UseOnly_databricks-worker-to-databricks-webapp'
        properties: {
            description: 'Required for workers communication with Databricks Webapp.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: 'AzureDatabricks'
            access: 'Allow'
            priority: 1005
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Microsoft.Databricks-workspaces_UseOnly_databricks-worker-to-sql'
        properties: {
            description: 'Required for workers communication with Azure SQL services.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '3306'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: 'Sql'
            access: 'Allow'
            priority: 1010
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Microsoft.Databricks-workspaces_UseOnly_databricks-worker-to-storage'
        properties: {
            description: 'Required for workers communication with Azure Storage services.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: 'Storage'
            access: 'Allow'
            priority: 1020
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Microsoft.Databricks-workspaces_UseOnly_databricks-worker-to-worker-outbound'
        properties: {
            description: 'Required for worker nodes communication within a cluster.'
            protocol: '*'
            sourcePortRange: '*'
            destinationPortRange: '*'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 1030
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
     }
     {
        name: 'Microsoft.Databricks-workspaces_UseOnly_databricks-worker-to-eventhub'
        properties: {
            description: 'Required for worker communication with Azure Eventhub services.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '9093'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: 'EventHub'
            access: 'Allow'
            priority: 1040
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'AzureFrontDoorFirstParty'
        properties: {
            description: 'Required for MCR pulls — MCR layers/manifests are served via FrontDoor FirstParty backend.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: 'AzureFrontDoor.FirstParty'
            access: 'Allow'
            priority: 1050
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'AzureMonitor'
        properties: {
            description: 'Required for log + metric egress (Container Insights, Log Analytics, App Insights).'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: 'AzureMonitor'
            access: 'Allow'
            priority: 1060
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
    ]
  }
}

output nsgId string = dbxNsg.id
