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
@allowed([ 'GlobalDocumentDB', 'MongoDB', 'Parse' ])
param kind string
param vnetName string
param subnetNamePend string
param vnetResourceGroupName string
// Container & database names
@minValue(4000)
@maxValue(1000000)
param autoscaleMaxThroughput int = 4000
param databaseName string = 'defaultdb'
param containerName string = 'defaultcontainer'
param partitionKeyPath string = '/id'

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

// v2 (no capacityMode): @2024-11-15
// serverless: resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
// serverless: 2025-05-01-preview
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview' = {
  name: name
  kind: kind
  location: location
  tags: tags
  properties: {
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    createMode: 'Default'
    databaseAccountOfferType: 'Standard'
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    apiProperties: (kind == 'MongoDB') ? { serverVersion: '4.2' } : {}
    capacityMode: capacityMode // Use the parameter
    capacity: (capacityMode == 'Serverless') ? {
      totalThroughputLimit: totalThroughputLimit
    } : null
    //capabilities: [ { name: 'EnableServerless' } ]
    enableFreeTier: false
    ipRules: [for rule in ipRules: {
      ipAddressOrRange: string(rule) // Ensure proper string conversion
    }]
    isVirtualNetworkFilterEnabled: vNetRules != []
    //TODO-1: cors: length(corsRules) > 0 ? corsRules : null
    networkAclBypass:'AzureServices'
    publicNetworkAccess:enablePublicGenAIAccess||enablePublicAccessWithPerimeter?'Enabled':'Disabled'
    virtualNetworkRules: !enablePublicAccessWithPerimeter?rules:null
  }
}

// Add a SQL database resource
resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-12-01-preview' = if(kind == 'GlobalDocumentDB') {
  parent: cosmos
  name: databaseName
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
    }
    options: (capacityMode == 'Provisioned') ? {
      autoscaleSettings: {
        maxThroughput: autoscaleMaxThroughput
      }
    } : {}
  }
}
resource pendCosmos 'Microsoft.Network/privateEndpoints@2022-01-01' = if(createPrivateEndpoint) {
  name: 'pend-cosmosdb-sql-${name}'
  location: location
  properties: {
    subnet: {
      id: subnetPend.id
    }
    privateLinkServiceConnections: [
      {
        name: 'pend-cosmosdb-sql-${name}'
        properties: {
          privateLinkServiceId: cosmos.id
          groupIds: [
            'Sql'
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

output endpoint string = cosmos.properties.documentEndpoint
output id string = cosmos.id
output name string = cosmos.name
output dnsConfig array = [
  {
    name: createPrivateEndpoint? pendCosmos.name: ''
    type: 'cosmosdbnosql'
    id:createPrivateEndpoint? pendCosmos.id: ''
  }
]

