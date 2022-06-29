@description('Specifies the name of the NSG, network security group')
param name string

@description('Specifies the location where the  network security group should be deployed. Defaults to resourceGroup.location')
param location string

@description('Specifies the tags that should be applied to the network security group')
param tags object

resource cmnNsg 'Microsoft.Network/networkSecurityGroups@2020-06-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    securityRules: [
      // --- Inbound ---
      { //!
        name: 'AML_CI_44224'
        properties: {
          description: 'Required for Azure Machine Learning'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '44224'
          sourceAddressPrefix: 'AzureMachineLearning'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1050
          direction: 'Inbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: []
          destinationAddressPrefixes: []
        }
      }
      { //!
        name: 'AML_Port_29876-29877'
        properties: {
            description: 'Required for Azure Machine Learning batch compute nodes'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '29876-29877'
            sourceAddressPrefix: 'BatchNodeManagement'
            destinationAddressPrefix: '*'
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
      {// !! 
        name: 'AzureActiveDirectory'
        properties: {
          description: 'AML'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureActiveDirectory'
          access: 'Allow'
          priority: 130
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureMachineLearningOutbound'
        properties: {
          description: 'AML'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureMachineLearning'
          access: 'Allow'
          priority: 140
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureResourceManager'
        properties: {
          description: 'AML'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureResourceManager'
          access: 'Allow'
          priority: 150
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureStorageAccount'
        properties: {
          description: 'AML !!'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'Storage.${location}'
          access: 'Allow'
          priority: 160
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureFrontDoor'
        properties: {
          description: 'AML'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureFrontDoor.FrontEnd'
          access: 'Allow'
          priority: 170
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureContainerRegistry'
        properties: {
          description: 'AML'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureContainerRegistry.${location}'
          access: 'Allow'
          priority: 180
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'MicrosoftContainerRegistry'
        properties: {
          description: 'AML'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'MicrosoftContainerRegistry'
          access: 'Allow'
          priority: 200
          direction: 'Outbound'
        }
      }
    ]
  }
}

output nsgId string = cmnNsg.id
