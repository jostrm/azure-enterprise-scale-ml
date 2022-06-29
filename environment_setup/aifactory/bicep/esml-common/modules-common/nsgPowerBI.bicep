@description('Specifies the name of the NSG, network security group')
param name string

@description('Specifies the location where the  network security group should be deployed. Defaults to resourceGroup.location')
param location string

@description('Specifies the tags that should be applied to the network security group')
param tags object

resource pbiNsg 'Microsoft.Network/networkSecurityGroups@2020-06-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    securityRules: [
      // --- Inbound --- https://docs.microsoft.com/en-us/power-bi/enterprise/service-security-private-links
 
      // --- Outbound --- 
       {
        name: 'AzureActiveDirectory'
        properties: {
          description: 'Optional'
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
       {
        name: 'AzureStorageAccount'
        properties: {
          description: 'Optional'
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
      {
        name: 'AzureFrontDoor'
        properties: {
          description: 'Optional'
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
    ]
  }
}

output nsgId string = pbiNsg.id
