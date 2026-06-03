@description('Specifies the name of the databricks network security group')
param name string

@description('Specifies the location where the databricks network security group should be deployed. Defaults to resourceGroup.location')
param location string

@description('Specifies the tags that should be applied to the databricks network security group')
param tags object

resource aksNsg 'Microsoft.Network/networkSecurityGroups@2020-06-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    securityRules: [
      // --- Inbound ---
      // Highest-priority VNet allow rule: lets every subnet in the VNet reach this subnet on any port/protocol.
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
          priority: 100
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
          priority: 110
          direction: 'Inbound'
        }
      }
      { // AML copy start
        name: 'AzureMachineLearning'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '44224'
          sourceAddressPrefix: 'AzureMachineLearning'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 130
          direction: 'Inbound'
        }
      }
      // --- Outbound ---
      // Highest-priority VNet allow rule: lets this subnet reach any subnet in the same VNet on any port/protocol.
      // Priorities for the rest of the outbound rules start at 1000 so 100-999 stays free for future higher-priority overrides.
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
          priority: 100
          direction: 'Outbound'
        }
      }
      {
        name: 'AzureActiveDirectory'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureActiveDirectory'
          access: 'Allow'
          priority: 1000
          direction: 'Outbound'
        }
      } 
      {// !!
        name: 'MicrosoftContainerRegistry'
        properties: {
          description: 'AML !!!'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'MicrosoftContainerRegistry' // 'MicrosoftContainerRegistry.${location}'
          access: 'Allow'
          priority: 1010
          direction: 'Outbound'
        }
      }
      { 
        name: 'AzureMachineLearningOutbound'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureMachineLearning'
          access: 'Allow'
          priority: 1020
          direction: 'Outbound'
        }
      }
      {
        name: 'AzureResourceManager'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureResourceManager'
          access: 'Allow'
          priority: 1030
          direction: 'Outbound'
        }
      }
      {
        name: 'AzureStorageAccount'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'Storage.${location}'
          access: 'Allow'
          priority: 1040
          direction: 'Outbound'
        }
      }
      {
        name: 'AzureFrontDoor'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureFrontDoor.FrontEnd'
          access: 'Allow'
          priority: 1050
          direction: 'Outbound'
        }
      }
      {
        name: 'AzureContainerRegistry'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureContainerRegistry.${location}'
          access: 'Allow'
          priority: 1060
          direction: 'Outbound'
        }
      }
      {
        name: 'AzureFrontDoorFirstParty'
        properties: {
          description: 'Required for MCR pulls — MCR layers/manifests are served via FrontDoor FirstParty backend.'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureFrontDoor.FirstParty'
          access: 'Allow'
          priority: 1070
          direction: 'Outbound'
        }
      }
      {
        name: 'AzureMonitor'
        properties: {
          description: 'Required for AKS / ACA log + metric egress (Container Insights, Log Analytics, App Insights).'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureMonitor'
          access: 'Allow'
          priority: 1080
          direction: 'Outbound'
        }
      }
    ]
  }
}

output nsgId string = aksNsg.id
