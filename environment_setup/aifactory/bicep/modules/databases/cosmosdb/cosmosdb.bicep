metadata description = 'Creates an Azure Cosmos DB account.'
param name string
param location string
param tags object
param vNetRules array = []
param ipRules array = []
param enablePublicGenAIAccess bool = false
param createPrivateEndpoint bool = true
param corsRules array = []
@allowed(['Serverless', 'Provisioned'])
param capacityMode string = 'Serverless'
@minValue(1000)
@maxValue(1000000)
param totalThroughputLimit int = 1000
param enablePublicAccessWithPerimeter bool = false
@allowed([ 'GlobalDocumentDB', 'MongoDB'])
param kind string
param vnetName string
param subnetNamePend string
param vnetResourceGroupName string
param logAnalyticsWorkspaceResourceId string
// Container & database names
@minValue(4000)
@maxValue(1000000)
param autoscaleMaxThroughput int = 4000
param databaseName string = 'aifdb'
param databaseNameCaphost string = 'enterprise_memory'
param containerName string = 'defaultcontainer'
param partitionKeyPath string = '/id'
param minimalTlsVersion string = 'Tls12' // docs. //todo: 'TLS 1.2' //done-error: 'Tls1_2'
param connectionStringKey string = 'aifactory-proj-cosmosdb-con-string'
param keyvaultName string
@description('Default TTL in seconds. Set to -1 to disable or positive integer for automatic document expiration')
param defaultTtl int = -1

import { managedIdentityAllType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'
@description('Optional. The managed identity definition for this resource.')
param managedIdentities managedIdentityAllType?

param useCMK bool = false
param keyVaultKeyUri string = ''
param cmkUserAssignedIdentityId string = ''

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnetPend 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetNamePend
  parent: vnet
}
// Capability EnableServerless is not allowed in API version beyond 2024-05-15-preview. 
// Used API Version: 2024-12-01-preview. Use CapacityMode instead to serverless.

// Contoso: databaseAccounts@2022-08-15
// Change API version to a stable, well-supported version
var rules = [for rule in vNetRules: {
  id: string(rule)
  ignoreMissingVNetServiceEndpoint: true
}]

var cmkIdentityDict = useCMK ? {
  '${cmkUserAssignedIdentityId}': {}
} : {}

var formattedUserAssignedIdentities = union(reduce(
  map((managedIdentities.?userAssignedResourceIds ?? []), (id) => { '${id}': {} }),
  {},
  (cur, next) => union(cur, next)
), cmkIdentityDict)

var identity = (!empty(managedIdentities) || useCMK)
  ? {
      type: (managedIdentities.?systemAssigned ?? false)
        ? (!empty(formattedUserAssignedIdentities) ? 'SystemAssigned,UserAssigned' : 'SystemAssigned')
        : (!empty(formattedUserAssignedIdentities) ? 'UserAssigned' : null)
      userAssignedIdentities: !empty(formattedUserAssignedIdentities) ? formattedUserAssignedIdentities : null
    }
  : null

// v2 (no capacityMode): @2024-11-15
// serverless: resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
// serverless: 2025-05-01-preview, 2024-12-01-preview
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-12-01-preview' = {
  name: name
  kind: kind
  location: location
  identity: identity
  tags: tags
  properties: {
    keyVaultKeyUri: useCMK ? keyVaultKeyUri : null
    defaultIdentity: useCMK ? 'UserAssignedIdentity=${cmkUserAssignedIdentityId}' : null
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    createMode: 'Default'
    minimalTlsVersion: minimalTlsVersion
    databaseAccountOfferType: 'Standard'
    diagnosticLogSettings: {
      enableFullTextQuery: 'None'
    }
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    apiProperties: (kind == 'MongoDB') ? { serverVersion: '4.2' } : {}
    capacityMode: capacityMode // Use the parameter
    capacity: (capacityMode == 'Serverless') ? {
      totalThroughputLimit: totalThroughputLimit
    } : null
    
    enableFreeTier: false
    ipRules: [for rule in ipRules: {
      ipAddressOrRange: string(rule) // Ensure proper string conversion
    }]
    isVirtualNetworkFilterEnabled: vNetRules != []
    //TODO-1: cors
    //cors: length(corsRules) > 0 ? {
    //      allowedOrigins: corsRules
    //} : null
    networkAclBypass:'AzureServices'
    publicNetworkAccess:(enablePublicGenAIAccess||enablePublicAccessWithPerimeter)?'Enabled':'Disabled'
    virtualNetworkRules: enablePublicAccessWithPerimeter?[]:rules
  }
}

// Add a SQL database resource
resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-12-01-preview' = if(kind == 'GlobalDocumentDB') {
  parent: cosmos
  name: databaseName
  tags:tags
  properties: {
    resource: {
      id: databaseName
    }
  }
}
// Add a SQL container resource
resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' = if(kind == 'GlobalDocumentDB') {
  parent: cosmosDatabase
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: {
        paths: [
          partitionKeyPath
        ]
        kind: 'Hash'
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
      defaultTtl: defaultTtl // TTL in seconds, -1 to disable, positive for expiration time
    }
    options: (capacityMode == 'Provisioned') ? {
      autoscaleSettings: {
        maxThroughput: autoscaleMaxThroughput
      }
    } : {}
  }
}
// Caphost DB - enterprise_memory
resource cosmosDatabaseCaphost 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-12-01-preview' = if(kind == 'GlobalDocumentDB') {
  parent: cosmos
  name: databaseNameCaphost
  tags:tags
  properties: {
    resource: {
      id: databaseNameCaphost
    }
  }
}


// Add MongoDB database and collection resources

// MongoDB database
resource mongoDatabase 'Microsoft.DocumentDB/databaseAccounts/mongodbDatabases@2024-12-01-preview' = if(kind == 'MongoDB') {
  parent: cosmos
  name: databaseName
  tags:tags
  properties: {
    resource: {
      id: databaseName
    }
  }
}

// MongoDB collection
resource mongoCollection 'Microsoft.DocumentDB/databaseAccounts/mongodbDatabases/collections@2024-12-01-preview' = if(kind == 'MongoDB') {
  parent: mongoDatabase
  name: containerName
  tags:tags
  properties: {
    resource: {
      id: containerName
      shardKey: {
        '${replace(partitionKeyPath, '/', '')}': 'Hash'
      }
      indexes: [
        {
          key: {
            keys: ['_id']
          }
        }
      ]
    }
    options: (capacityMode == 'Provisioned') ? {
      autoscaleSettings: {
        maxThroughput: autoscaleMaxThroughput
      }
    } : {}
  }
}
resource pendCosmos 'Microsoft.Network/privateEndpoints@2024-05-01' = if(createPrivateEndpoint) {
  name: '${name}-pend'
  location: location
  properties: {
    subnet: {
      id: subnetPend.id
    }
    customNetworkInterfaceName: '${name}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${name}-pend'
        properties: {
          privateLinkServiceId: cosmos.id
          groupIds: [
            kind == 'GlobalDocumentDB'?'Sql': kind == 'MongoDB'?'MongoDB':'Cassandra'
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

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyvaultName
  scope: resourceGroup()
}

@description('Key Vault: CosmosDB')
resource cosmosConnectionString 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: keyVault
  name: connectionStringKey
  properties: {
    value: kind == 'MongoDB' 
      ? cosmos.listConnectionStrings().connectionStrings[0].connectionString
      : 'AccountEndpoint=${cosmos.properties.documentEndpoint};AccountKey=${cosmos.listKeys().primaryMasterKey};'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

output endpoint string = cosmos.properties.documentEndpoint
output id string = cosmos.id
output name string = cosmos.name
output dnsConfig array = [
  {
    name: createPrivateEndpoint? pendCosmos.name: ''
    type: kind == 'GlobalDocumentDB'? 'cosmosdbnosql':kind == 'MongoDB'? 'cosmosdbmongo': 'cosmosdbcassandra'
    id:createPrivateEndpoint? cosmos.id: ''
  }
]

