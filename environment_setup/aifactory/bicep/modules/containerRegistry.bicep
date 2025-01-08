// Deploy keyvault with a private endpoint enabled

@description('(Required) Specifies the name of the Azure container registry that will be deployed')
param containerRegistryName string

@description('(Optional) Specifies the Azure container registry service tier name, defaults to premium because of the private endpoints association')
@allowed([
  'Premium'
])
param skuName string = 'Premium'

@description('(Required) Specifies the VNET id that will be associated with the private endpoint')
param vnetId string

@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string

@description('(Required) Specifies the private endpoint name')
param privateEndpointName string

@description('(Required) Specifies the tags that will be associated with azure container registry resources')
param tags object
param location string

var subnetRef = '${vnetId}/subnets/${subnetName}'
var policyOn = 'enabled' // 'disabled'
var containerRegistryNameCleaned = replace(containerRegistryName, '-', '')

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: containerRegistryNameCleaned
  tags: tags
  location: location
  sku: {
    name: skuName
  }
  properties: {
    adminUserEnabled: true
    networkRuleSet: {
      defaultAction: 'Deny'
      ipRules: []
    }
    dataEndpointEnabled: false
    networkRuleBypassOptions: 'AzureServices'
    policies: {
      quarantinePolicy: {
        status: policyOn
      }
      retentionPolicy: {
        status: policyOn
        days: 7
      }
      trustPolicy: {
        status: policyOn
        type: 'Notary'
      }
    }
    publicNetworkAccess: 'Disabled'
    zoneRedundancy: 'Disabled'
  }
}

resource pendAcr 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    customNetworkInterfaceName: '${privateEndpointName}-nic'
    subnet: {
      id: subnetRef
      name: subnetName
    }
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: containerRegistry.id
          groupIds: [
            'registry'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Compliance with network design'
          }
        }
       
      }
      
    ]
  }
}

output containerRegistryId string = containerRegistry.id
output containerRegistryName string = containerRegistry.name
output dnsConfig array = [
  {
    name: pendAcr.name
    type: 'registry'
    id:containerRegistry.id
  }
]
