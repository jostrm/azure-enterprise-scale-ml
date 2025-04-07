metadata description = 'Creates an Azure Cosmos DB account.'
param name string
param location string
param tags object
param vNetRules array = []
param ipRules array = []
param enablePublicGenAIAccess bool = false
param corsRules array = []
param totalThroughputLimit int = 1000
param enablePublicAccessWithPerimeter bool = false
@allowed([ 'GlobalDocumentDB', 'MongoDB', 'Parse' ])
param kind string
param vnetName string
param subnetNamePend string
param vnetResourceGroupName string
param capacityMode string = 'Serverless' // 'Serverless' or 'Provisioned'

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
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-12-01-preview' = {
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
    } : {}
    //capabilities: [ { name: 'EnableServerless' } ]
    enableFreeTier: false
    ipRules: [for rule in ipRules: {
        ipAddressOrRange: rule
    }]
    isVirtualNetworkFilterEnabled: true
    cors: corsRules
    networkAclBypass:'AzureServices'
    publicNetworkAccess:enablePublicGenAIAccess?'Enabled':'Disabled'
    virtualNetworkRules: [for rule in vNetRules: {
      id: rule
      ignoreMissingVNetServiceEndpoint: true
    }]
  }
}
// First, add a parameter for the database and container names
param databaseName string = 'defaultdb'
param containerName string = 'defaultcontainer'
param partitionKeyPath string = '/id'
param autoscaleMaxThroughput int = 4000

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
resource pendCosmos 'Microsoft.Network/privateEndpoints@2022-01-01' = if(enablePublicAccessWithPerimeter==false) {
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
    name: !enablePublicAccessWithPerimeter? pendCosmos.name: ''
    type: 'Sql'
    id:!enablePublicAccessWithPerimeter? pendCosmos.id: ''
  }
]

