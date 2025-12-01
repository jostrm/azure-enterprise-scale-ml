param cosmosDBConnection string 
param azureStorageConnection string 
param aiSearchConnection string
param projectName string
param accountName string
@description('Set to true to create project capability host')
param projectCapHost bool = true
param projectCapHostName string = ''

// CRITICAL: Use API version 2025-07-01-preview for capability hosts (per AVM module)
// AI Foundry resource (AI Services) - must use 2025-07-01-preview for capability host support
resource account 'Microsoft.CognitiveServices/accounts@2025-07-01-preview' existing = {
   name: accountName
}

// AI Foundry project - Use 2025-07-01-preview for projects with capability hosts
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-07-01-preview' existing = {
  name: projectName
  parent: account
}

// Get existing connection resources to reference them properly
// These connections must already be deployed by the aiFoundry2025project.bicep module
resource cosmosDbConnectionResource 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' existing = {
  name: cosmosDBConnection
  parent: project
}

resource storageAccountConnectionResource 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' existing = {
  name: azureStorageConnection
  parent: project
}

resource aiSearchConnectionResource 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' existing = {
  name: aiSearchConnection
  parent: project
}

// Account-level capability host - Must be created BEFORE project capability host
// NOTE: Name format follows AVM pattern - remove dashes from account name
// IMPORTANT: Account capability host depends on project and connections per AVM pattern
resource accountCapabilityHost 'Microsoft.CognitiveServices/accounts/capabilityHosts@2025-07-01-preview' = {
  name: 'chagent${replace(accountName, '-', '')}'
  parent: account
  properties: {
    capabilityHostKind: 'Agents'
  }
  dependsOn: [
    project
    cosmosDbConnectionResource
    storageAccountConnectionResource
    aiSearchConnectionResource
  ]
}

// Project-level capability host - Created AFTER account capability host
// NOTE: Name format follows AVM pattern - remove dashes from project name
resource projectCapabilityHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-07-01-preview' = {
  name: 'chagent${replace(projectName, '-', '')}'
  parent: project
  properties: {
    capabilityHostKind: 'Agents'
    threadStorageConnections: ['${cosmosDbConnectionResource.name}']
    vectorStoreConnections: ['${aiSearchConnectionResource.name}']
    storageConnections: ['${storageAccountConnectionResource.name}']
  }
  dependsOn: [
    accountCapabilityHost  // CRITICAL: Must wait for account capability host
    cosmosDbConnectionResource
    storageAccountConnectionResource
    aiSearchConnectionResource
  ]
}

output projectCapHost string = projectCapabilityHost.name
output accountCapHost string = accountCapabilityHost.name
