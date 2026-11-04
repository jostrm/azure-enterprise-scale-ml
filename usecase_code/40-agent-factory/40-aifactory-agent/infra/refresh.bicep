targetScope = 'resourceGroup'

param location string
param jobName string = 'aifactory-agent-refresh-dev'
param environmentName string
param identityName string = 'mi-aifactory-agent-refresh-dev'
param image string
param searchName string
param foundryAccount string
param storageAccount string
param storageContainer string
param bundleBlob string
param bundleSha256 string
param bootstrapCommand string
param schedule string = '0 3 * * *'

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: environmentName
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: { 'managed-by': 'enterprise-scale-ai-factory-agent' }
}
resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchName
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccount
}
resource service 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  name: 'default'
  parent: storage
}
resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  name: storageContainer
  parent: service
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccount
}
resource searchDocuments 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, identity.id, 'index-documents')
  scope: search
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
  }
}
resource searchSchema 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, identity.id, 'index-schema')
  scope: search
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')
  }
}
resource blobState 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(container.id, identity.id, 'refresh-state')
  scope: container
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}
resource embeddings 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, identity.id, 'embeddings')
  scope: foundry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}
resource job 'Microsoft.App/jobs@2025-01-01' = {
  name: jobName
  location: location
  tags: { 'managed-by': 'enterprise-scale-ai-factory-agent' }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      scheduleTriggerConfig: {
        cronExpression: schedule
        parallelism: 1
        replicaCompletionCount: 1
      }
    }
    template: {
      containers: [{
        name: 'refresh'
        image: image
        command: ['/bin/sh', '-c']
        args: [bootstrapCommand]
        env: [
          { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
          { name: 'BUNDLE_ACCOUNT', value: storageAccount }
          { name: 'BUNDLE_CONTAINER', value: storageContainer }
          { name: 'BUNDLE_BLOB', value: bundleBlob }
          { name: 'BUNDLE_SHA256', value: bundleSha256 }
          { name: 'AGENT_COMMAND', value: 'ingest' }
          { name: 'PYTHONUNBUFFERED', value: '1' }
          { name: 'PIP_DISABLE_PIP_VERSION_CHECK', value: '1' }
        ]
        resources: { cpu: json('0.5'), memory: '1Gi' }
      }]
    }
  }
}

output identityClientId string = identity.properties.clientId
output jobId string = job.id
