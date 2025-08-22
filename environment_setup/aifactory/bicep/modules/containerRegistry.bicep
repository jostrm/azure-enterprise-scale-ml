// Deploy keyvault with a private endpoint enabled

@description('(Required) Specifies the name of the Azure container registry that will be deployed')
param containerRegistryName string

@description('(Optional) Specifies the Azure container registry service tier name, defaults to premium because of the private endpoints association')
@allowed(['Premium', 'Standard', 'Basic']) 
param skuName string = 'Premium' // NB! Basic and Standard ACR SKUs don't support private endpoints.

@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string

@description('(Required) Specifies the private endpoint name')
param privateEndpointName string

@description('(Required) Specifies the tags that will be associated with azure container registry resources')
param tags object
param location string
param vnetName string
param vnetResourceGroupName string
param enablePublicAccessWithPerimeter bool = false

//var subnetRef = '${vnetId}/subnets/${subnetName}'
var policyOn = 'disabled' // 'enabled' // 'disabled' GET https:: IMAGE_QUARANTINED: The image is quarantined
var containerRegistryNameCleaned = replace(containerRegistryName, '-', '')

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}

// 2023-11-01-preview needed for metadataSearch (prev: registries@2023-07-01, 2023-11-01-preview)
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2024-11-01-preview' = {
  name: containerRegistryNameCleaned
  tags: tags
  location: location
  sku: {
    name: skuName
  }
  properties: {
    adminUserEnabled: true
    networkRuleSet: !enablePublicAccessWithPerimeter ? {
      defaultAction: 'Deny'
      ipRules: []
    }:null
    dataEndpointEnabled: false
    //networkRuleBypassOptions: !enablePublicAccessWithPerimeter? 'AzureServices': null
    networkRuleBypassOptions:'AzureServices'
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
    publicNetworkAccess: !enablePublicAccessWithPerimeter? 'Disabled': 'Enabled'
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
      id: subnet.id
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
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
       
      }
      
    ]
  }
}

output containerRegistryId string = containerRegistry.id
output containerRegistryName string = containerRegistry.name
output registryLoginServer string = containerRegistry.properties.loginServer
output dnsConfig array = [
  {
    name: pendAcr.name
    type: 'registry'
    id:containerRegistry.id
  }
]
