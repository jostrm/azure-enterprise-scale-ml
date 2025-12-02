param cosmosDBConnection string 
param azureStorageConnection string 
param aiSearchConnection string
param projectName string
param accountName string
@description('Optional name for the capability host. If omitted, a deterministic name is generated based on the selected level.')
param projectCapHostName string = ''
@description('When true, deploy the capability host at the account scope instead of the project scope.')
param accountLevel bool = false

var defaultProjectCapabilityHostName = 'chagent${replace(projectName, '-', '')}'
var defaultAccountCapabilityHostName = 'chagent${replace(accountName, '-', '')}'
var resolvedProjectCapabilityHostName = empty(projectCapHostName) ? defaultProjectCapabilityHostName : projectCapHostName
var resolvedAccountCapabilityHostName = empty(projectCapHostName) ? defaultAccountCapabilityHostName : projectCapHostName

// CRITICAL: Use API version 2025-07-01-preview for capability hosts (per AVM module)
// AI Foundry resource (AI Services) - must use 2025-07-01-preview for capability host support
resource account 'Microsoft.CognitiveServices/accounts@2025-07-01-preview' existing = {
   name: accountName
}

// AI Foundry project - Use 2025-07-01-preview for projects with capability hosts
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' existing = {
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
resource accountCapabilityHost 'Microsoft.CognitiveServices/accounts/capabilityHosts@2025-07-01-preview' = if (accountLevel) {
  name: resolvedAccountCapabilityHostName
  parent: account
  properties: {
    capabilityHostKind: 'Agents'
  }
}

// Project-level capability host - Created AFTER account capability host
// NOTE: Name format follows AVM pattern - remove dashes from project name
resource projectCapabilityHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-07-01-preview' = if (!accountLevel) {
  name: resolvedProjectCapabilityHostName
  parent: project
  properties: {
    capabilityHostKind: 'Agents'
    threadStorageConnections: ['${cosmosDbConnectionResource.name}']
    vectorStoreConnections: ['${aiSearchConnectionResource.name}']
    storageConnections: ['${storageAccountConnectionResource.name}']
  }
  dependsOn: [
    cosmosDbConnectionResource
    storageAccountConnectionResource
    aiSearchConnectionResource
  ]
}

#disable-next-line BCP318
output projectCapHost string = !accountLevel ? string(projectCapabilityHost.name) : ''
#disable-next-line BCP318
output accountCapHost string = accountLevel ? string(accountCapabilityHost.name) : ''
