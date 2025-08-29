@description('Name of service')
param aiSearchName string
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
param enablePublicAccessWithPerimeter bool = false
param vnetName string
param vnetResourceGroupName string

//var subnetRef = '${vnetId}/subnets/${subnetName}'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}

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
    publicNetworkAccess:(enablePublicAccessWithPerimeter || publicNetworkAccess)? 'Enabled': 'Disabled'  // Enabled, for ipRules to work.
    networkRuleSet: {
      bypass: 'AzureServices' //'None', 'AzureServices', 'None', 'AzurePortal'
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
resource aiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' = if(!enableSharedPrivateLink) {
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
    publicNetworkAccess:(enablePublicAccessWithPerimeter || publicNetworkAccess)? 'Enabled': 'Disabled'  // Enabled, for ipRules to work.
    networkRuleSet: !enablePublicAccessWithPerimeter ? {
      bypass: 'AzureServices'
      ipRules: ipRules // [{value: 'ip'}], .e.g. only IP addresses. Not also "action: 'Allow'"
    }:null
    
    semanticSearch: semanticSearchTier
  }

}

resource pendAISearch 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${aiSearch.name}-pend-nic'
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
#disable-next-line BCP318
output principalId string = aiSearch.identity.principalId

output dnsConfig array = [
  {
    name: pendAISearch.name
    type: 'searchService'
    id:aiSearch.id
  }
]
