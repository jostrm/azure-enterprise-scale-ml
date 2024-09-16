@description('Name of service')
param aiSearchName string
@description('Specifies the VNET id that will be associated with the private endpoint')
param vnetId string
@description('Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
param tags object
param location string
param enableSharedPrivateLink bool
param sharedPrivateLinks array = []
// 'Basic' = S0
@allowed([
  'Free'
  'S0'
  'S1'
  'S2'
  'S3'
])
param skuName string = 'S0'
param replicaCount int = 1
param partitionCount int = 1
param privateEndpointName string
param semanticSearchTier string = 'disabled' //'disabled', 'standard'
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
    }
    semanticSearch: semanticSearchTier
  }
}

@batchSize(1)
resource sharedPrivateLink 'Microsoft.Search/searchServices/sharedPrivateLinks@2024-06-01-preview' = [for (sharedPend, i) in sharedPrivateLinks: if(enableSharedPrivateLink) {
  name: 'aisearch-${aiSearchName}-shared-plink-${i}'
  parent: aiSearch
  properties: {
    groupId: 'aiSearch'
    sharedPrivateLinkResourceId: sharedPrivateLinks[i].privateLinkResourceId
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Compliance with network design'
    }
  }
}]

/*
resource symbolicname 'Microsoft.Search/searchServices/sharedPrivateLinkResources@2024-03-01-preview' = {
  name: 'string'
  parent: resourceSymbolicName
  properties: {
    groupId: 'string'
    privateLinkResourceId: 'string'
    provisioningState: 'string'
    requestMessage: 'string'
    resourceRegion: 'string'
    status: 'string'
  }
}
*/
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
            'searchService'
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
    type: 'searchService'
    id:aiSearch.id
  }
]
