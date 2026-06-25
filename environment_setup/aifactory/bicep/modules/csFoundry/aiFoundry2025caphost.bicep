param cosmosDBConnection string 
param azureStorageConnection string 
param aiSearchConnection string
param projectName string
param accountName string
@description('Optional name for the project capability host. If omitted, a deterministic name is generated.')
param projectCapHostName string = ''

var defaultProjectCapabilityHostName = 'chagent${replace(projectName, '-', '')}'
var resolvedProjectCapabilityHostName = empty(projectCapHostName) ? defaultProjectCapabilityHostName : projectCapHostName

// CRITICAL: Use API version 2025-07-01-preview for capability hosts (per AVM module)
// AI Foundry resource (AI Services) - must use 2025-07-01-preview for capability host support
#disable-next-line BCP081
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
#disable-next-line BCP081
resource cosmosDbConnectionResource 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' existing = {
  name: cosmosDBConnection
  parent: project
}

#disable-next-line BCP081
resource storageAccountConnectionResource 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' existing = {
  name: azureStorageConnection
  parent: project
}

#disable-next-line BCP081
resource aiSearchConnectionResource 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' existing = {
  name: aiSearchConnection
  parent: project
}

// Project-level capability host.
// NOTE: The ACCOUNT-level capability host is intentionally NOT created here. In the agent network
// injection scenario the platform auto-provisions it from the account's networkInjections; creating it
// in Bicep would conflict/time out. For the non-injection (disableAgentNetworkInjection=true) path it is
// created explicitly via aiFoundry2025AccountCaphost.bicep (which sets the matching customerSubnet).
// NOTE: capabilityHostKind is NOT a valid property at project scope (only at account scope).
//       Permissible project-level properties: vectorStoreConnections, threadStorageConnections,
//       storageConnections, aiServicesConnections.
#disable-next-line BCP081
resource projectCapabilityHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-09-01' = {
  name: resolvedProjectCapabilityHostName
  parent: project
  properties: {
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

output projectCapHost string = projectCapabilityHost.name
