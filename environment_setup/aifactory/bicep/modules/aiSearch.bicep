@description('Name of service')
param aiSearchName string
@description('Specifies the VNET id that will be associated with the private endpoint')
param vnetId string
@description('Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
param tags object
param location string
param enableSharedPrivateLink bool
param acrNameDummy string = ''
param sharedPrivateLinks array = []
@allowed([
  'S0' // 'Free': Invalid SKU name
  'S1' // 'Basic': Invalid SKU name
  'standard'
  'standard2' // 0 out of 0 quota, is default, apply to get this.
])
param skuName string = 'standard' 
@allowed([
  'default'
  'highDensity'
])
param hostingMode string = 'default'
param replicaCount int = 1
param partitionCount int = 1
param privateEndpointName string
@allowed([
  'disabled'
  'free'
  'standard'
])
param semanticSearchTier string = 'disabled'
param publicNetworkAccess bool = false
param ipRules array = []

var subnetRef = '${vnetId}/subnets/${subnetName}'

resource aiSearchSharedPend 'Microsoft.Search/searchServices@2024-03-01-preview' = if(enableSharedPrivateLink == true) {
  name: aiSearchName
  location: location
  tags: tags
  sku: {
    name: 'standard2' // Neends to be standard2 or higher (You may not have quota for this. You need to apply if so)
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
    hostingMode: hostingMode
    partitionCount: partitionCount
    publicNetworkAccess:'Enabled' // publicNetworkAccess? 'Enabled': 'Disabled'  // Enabled, for ipRules to work.
    networkRuleSet: {
      bypass: 'AzureServices' //'None', 'AzureServices', 'None'
      ipRules: ipRules
    }
    semanticSearch: semanticSearchTier
  }
  @batchSize(1)
  resource sharedPrivateLinkResource 'sharedPrivateLinkResources@2024-06-01-preview' =  [for (sharedPL, i) in sharedPrivateLinks: {
        name: '${aiSearchName}-shared-pe-${i}' //  'search-shared-private-link-${i}'
        properties: sharedPL
    }]
}

// To add Azure Portal. ipRules and add: nslookup on stamp2.ext.search.windows.net (Non-authorative answer)
resource aiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' = if(enableSharedPrivateLink == false) {
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
    hostingMode: hostingMode
    partitionCount: partitionCount
    publicNetworkAccess:'Enabled' // publicNetworkAccess? 'Enabled': 'Disabled'  // Enabled, for ipRules to work.
    networkRuleSet: {
      bypass: 'AzureServices' //'None' (GH copilot say also: 'AzureServices') // Azure docs says: 'AzurePortal'
      ipRules: ipRules
    }
    
    semanticSearch: semanticSearchTier
  }

}

/*
Error Not Found:  aisearch3pmpbprj001genaisdcdev-002/aisearch-aisearch3pmpbprj001genaisdcdev-002-shared-plink-0
TODO: remove "-" and shorten name.

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

*/

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
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
  
}

var hostName = 'https://${aiSearch.name}.search.windows.net'
output aiSearchEndpoint string = hostName
output aiSearchName string = aiSearch.name
output aiSearchId string = aiSearch.id
output principalId string = aiSearch.identity.principalId

output dnsConfig array = [
  {
    name: pendAISearch.name
    type: 'searchService'
    id:aiSearch.id
  }
]
