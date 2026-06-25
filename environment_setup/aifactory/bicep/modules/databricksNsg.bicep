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
      // IMPORTANT: Azure Databricks AUTO-PROVISIONS and MANAGES the required NSG rules for a
      // VNet-injected workspace via subnet delegation to Microsoft.Databricks/workspaces. This
      // includes ALL of the 'Microsoft.Databricks-workspaces_UseOnly_*' rules AND the
      // VirtualNetwork -> VirtualNetwork allow-all inbound/outbound rules.
      // Per Microsoft docs these rules must NOT be hand-authored or duplicated here:
      // https://learn.microsoft.com/azure/databricks/security/network/classic/vnet-inject#network-security-group-rules
      // Previously this module defined those rules manually, which caused a deployment-time
      // SecurityRuleConflict ("Security rule Allow_VNet_Outbound conflicts with rule
      // Microsoft.Databricks-workspaces_UseOnly_databricks-worker-to-databricks-webapp. Rules
      // cannot have the same Priority and Direction") because the Databricks-injected rules
      // collided with our duplicates.
      // Only genuinely ADDITIONAL custom egress/ingress rules are defined below, placed in a high
      // priority band (3900+) that never collides with the Databricks-managed rules.
      // --- Inbound (custom additions only) ---
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
          priority: 3900
          direction: 'Inbound'
        }
      }
      // --- Outbound (custom additions only) ---
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
            priority: 3900
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
            priority: 3910
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
