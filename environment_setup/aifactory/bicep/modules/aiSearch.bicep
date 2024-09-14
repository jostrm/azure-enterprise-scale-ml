@description('Name of service')
param aiSearchName string
@description('Specifies the VNET id that will be associated with the private endpoint')
param vnetId string
@description('Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
param tags object
param location string
param skuName string = 'basic'
param replicaCount int = 1
param partitionCount int = 1
param privateEndpointName string
param semanticSearchTier string = 'free'
param publicNetworkAccess bool = false
param ipRules array = []

var subnetRef = '${vnetId}/subnets/${subnetName}'

resource aiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' = {
  name: aiSearchName
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode:'http401WithBearerChallenge' // or 'http403'
      }
    }
    replicaCount: replicaCount
    partitionCount: partitionCount
    publicNetworkAccess: publicNetworkAccess? 'enabled': 'disabled'
    networkRuleSet: {
      bypass: 'AzurePortal' //'None' (GH copilot say also: 'AzureServices')
      ipRules: ipRules
      //defaultAction: publicNetworkAccess? 'Allow':'Deny'
      //virtualNetworkRules: json('[{"id": "${subnetRef}"}]')
    }
    semanticSearch: semanticSearchTier
  }
}

resource pendAISearch 'Microsoft.Network/privateEndpoints@2022-01-01' = {
  name: privateEndpointName
  location: location
  properties: {
    subnet: {
      id: subnetRef
    }
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: aiSearch.id
          groupIds: [
            'aiSearch'
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

output aiSearchName string = aiSearch.name
output aiSearchId string = aiSearch.id
output dnsConfig array = [
  {
    name: pendAISearch.name
    type: 'aiSearch'
    id:aiSearch.id
  }
]
