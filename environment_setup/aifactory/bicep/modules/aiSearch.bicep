@description('Name of service')
param aiSearchName string
@description('Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
param tags object
param location string
param enableSharedPrivateLink bool
param acrNameDummy string = ''

import { managedIdentityAllType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'
@description('Optional. The managed identity definition for this resource.')
param managedIdentities managedIdentityAllType?

param sharedPrivateLinks array = []
param approveStorageSharedLinks bool = false
param storageAccountNameForSharedLinks string = ''
param approveAiServicesSharedLink bool = false
param aiServicesNameForSharedLink string = ''

//@allowed([
//  'S0' // 'Free': Invalid SKU name
//  'S1' // 'Basic': Invalid SKU name
//  'standard'
//  'standard2' // 0 out of 0 quota, is default, apply to get this.
//])

@allowed(['free', 'basic', 'standard', 'standard2', 'standard3', 'storage_optimized_l1', 'storage_optimized_l2'])
param skuName string = 'standard' 
@allowed([
  'Default'
  'HighDensity'
])
param hostingMode string = 'Default'
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

// CMK parameters
param cmk bool = false
param cmkKeyName string = ''
param cmkKeyVaultUri string = ''
param cmkIdentityId string = ''

var formattedUserAssignedIdentities = reduce(
  map((managedIdentities.?userAssignedResourceIds ?? []), (id) => { '${id}': {} }),
  {},
  (cur, next) => union(cur, next)
) // Converts the flat array to an object like { '${id1}': {}, '${id2}': {} }
var identity = !empty(managedIdentities)
  ? {
      type: (managedIdentities.?systemAssigned ?? false)
        ? (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'SystemAssigned,UserAssigned' : 'SystemAssigned')
        : (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'UserAssigned' : 'None')
      userAssignedIdentities: !empty(formattedUserAssignedIdentities) ? formattedUserAssignedIdentities : null
    }
  : {type:'SystemAssigned'}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}

// To add Azure Portal. ipRules and add: nslookup on stamp2.ext.search.windows.net (Non-authorative answer)
// 2025-05-01
//resource aiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' = {
resource aiSearch 'Microsoft.Search/searchServices@2025-05-01' = {
  name: aiSearchName
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  identity: identity
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
    
    // Customer-Managed Key encryption
    encryptionWithCmk: cmk ? {
      enforcement: 'Enabled'
    } : null
  }
  
  @batchSize(1)
  resource sharedPrivateLinkResource 'sharedPrivateLinkResources@2025-05-01' = [for (sharedPL, i) in (enableSharedPrivateLink ? sharedPrivateLinks : []): {
    name: '${aiSearchName}-shared-pe-${i}'
    properties: sharedPL
  }]
}

resource pendAISearch 'Microsoft.Network/privateEndpoints@2024-05-01' = if(!enablePublicAccessWithPerimeter) {
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
        name: aiSearch.name
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
    name:!enablePublicAccessWithPerimeter ? pendAISearch.name : ''
    type: 'searchService'
    id:aiSearch.id
  }
]

// Auto-approve shared private link requests when requested
resource storageAccountForSharedLinks 'Microsoft.Storage/storageAccounts@2024-01-01' existing = if (approveStorageSharedLinks && enableSharedPrivateLink) {
  name: storageAccountNameForSharedLinks
}

resource approveSharedPrivateLinkBlob 'Microsoft.Storage/storageAccounts/privateEndpointConnections@2024-01-01' = if (approveStorageSharedLinks && enableSharedPrivateLink) {
  name: '${aiSearch.name}-shared-pe-0'
  parent: storageAccountForSharedLinks
  properties: {
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Approved during deployment'
    }
  }
  dependsOn: [
    aiSearch::sharedPrivateLinkResource[0]
  ]
}

resource approveSharedPrivateLinkFile 'Microsoft.Storage/storageAccounts/privateEndpointConnections@2024-01-01' = if (approveStorageSharedLinks && enableSharedPrivateLink) {
  name: '${aiSearch.name}-shared-pe-1'
  parent: storageAccountForSharedLinks
  properties: {
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Approved during deployment'
    }
  }
  dependsOn: [
    aiSearch::sharedPrivateLinkResource[1]
  ]
}

resource aiServicesAccountForSharedLink 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (approveAiServicesSharedLink && enableSharedPrivateLink) {
  name: aiServicesNameForSharedLink
}

resource approveSharedPrivateLinkAiServices 'Microsoft.CognitiveServices/accounts/privateEndpointConnections@2024-10-01' = if (approveAiServicesSharedLink && enableSharedPrivateLink) {
  name: '${aiSearch.name}-shared-pe-2'
  parent: aiServicesAccountForSharedLink
  properties: {
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Approved during deployment'
    }
  }
  dependsOn: [
    aiSearch::sharedPrivateLinkResource[2]
  ]
}
