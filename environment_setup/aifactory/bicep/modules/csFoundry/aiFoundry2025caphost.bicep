param cosmosDBConnection string 
param azureStorageConnection string 
param aiSearchConnection string
param projectName string
param accountName string
param projectCapHost string

var threadConnections = ['${cosmosDBConnection}']
var storageConnections = ['${azureStorageConnection}']
var vectorStoreConnections = ['${aiSearchConnection}']

// AI Foundry resource (AI Services)
resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
   name: accountName
}

resource accountCapabilityHost 'Microsoft.CognitiveServices/accounts/capabilityHosts@2025-06-01' = {
  name: '${projectCapHost}acc'
  parent: account
  properties: {
  }
  dependsOn: [
    account  // Explicit dependency to ensure account is fetched first
  ]
}

// AI foundry project
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  name: projectName
  parent: account
}

resource projectCapabilityHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-06-01' = {
  name: projectCapHost
  parent: project
  properties: {
    capabilityHostKind: 'Agents'
    vectorStoreConnections: vectorStoreConnections
    storageConnections: storageConnections
    threadStorageConnections: threadConnections
  }
  dependsOn: [
    account              //  Ensure account is fetched
    project              // Ensure project is fetched  
    accountCapabilityHost // Ensure account capability host is created first
  ]
}

output projectCapHost string = projectCapabilityHost.name
output accountCapHost string = accountCapabilityHost.name
