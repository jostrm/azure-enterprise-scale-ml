targetScope = 'resourceGroup'

param location string
param identityName string = 'mi-aifactory-agent-dev'
param searchName string
param storageName string
param storageContainer string
param foundryAccount string
param foundryProject string
param agentName string = 'enterprise-scale-ai-factory'
@allowed([
  'project_reference'
  'agent_endpoint'
])
param agentInvocation string = 'project_reference'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: {
    'managed-by': 'enterprise-scale-ai-factory-agent'
  }
}

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchName
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageName
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  name: 'default'
  parent: storage
}
resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  name: storageContainer
  parent: blobService
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccount
}
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  name: '${foundryAccount}/${foundryProject}'
}
resource agent 'Microsoft.CognitiveServices/accounts/projects/agents@2025-06-01' existing = {
  parent: project
  name: agentName
}

resource searchRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, identity.id, 'search-read')
  scope: search
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')
  }
}
resource blobState 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(container.id, identity.id, 'blob-state')
  scope: container
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}
resource inference 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, identity.id, 'inference')
  scope: foundry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}
resource projectRuntime 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (agentInvocation == 'project_reference') {
  name: guid(project.id, identity.id, 'foundry-project-runtime')
  scope: project
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '142bfaed-a13f-4c2d-bed2-6db62c4a1009')
  }
}
resource agentConsumer 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (agentInvocation == 'agent_endpoint') {
  name: guid(agent.id, identity.id, 'foundry-agent-consumer')
  scope: agent
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6')
  }
}
resource inventory 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, identity.id, 'inventory-read')
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')
  }
}

output identityId string = identity.id
output clientId string = identity.properties.clientId
output principalId string = identity.properties.principalId
