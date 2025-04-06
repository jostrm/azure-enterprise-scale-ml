metadata description = 'Creates an Azure Cosmos DB account.'
param name string
param location string
param tags object
param vNetRules array = []
param ipRules array = []
param enablePublicGenAIAccess bool = false
param corsRules array = []
param totalThroughputLimit int = 1000

@allowed([ 'GlobalDocumentDB', 'MongoDB', 'Parse' ])
param kind string

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
    capacityMode: 'Serverless' // 'Serverless' or 'Provisioned'
    capacity: {
      totalThroughputLimit: totalThroughputLimit
    }
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

output endpoint string = cosmos.properties.documentEndpoint
output id string = cosmos.id
output name string = cosmos.name
