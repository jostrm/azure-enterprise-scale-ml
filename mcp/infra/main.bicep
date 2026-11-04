targetScope = 'subscription'

@description('Existing resource group that hosts the internal Container Apps environment, Key Vault, identity, and app.')
param resourceGroupName string

@description('Azure region for the new managed identity and Container App.')
param location string

@description('Name of the existing internal Container Apps managed environment.')
param environmentName string

@description('Name of the new Container App.')
param appName string

@description('Name of the new user-assigned managed identity.')
param identityName string

@description('Name of the existing Azure Container Registry.')
param registryName string

@description('Resource group containing the existing Azure Container Registry.')
param registryResourceGroupName string

@description('Name of the existing RBAC-enabled Key Vault.')
param keyVaultName string

@description('Name of the existing dedicated API-key secret.')
param apiKeySecretName string

@description('Immutable MCP image reference in the form registry/repository@sha256:digest.')
param mcpImage string = ''

@description('Immutable Factory API image reference in the form registry/repository@sha256:digest.')
param apiImage string = ''

@secure()
@description('Secret-free JSON pilot agent configuration. Secure prevents deployment logging.')
param agentConfigJson string = ''

@secure()
@description('Secret-free JSON application authentication configuration. Secure prevents deployment logging.')
param applicationAuthJson string = ''

@description('Governed pilot scope key.')
param scopeKey string

@description('Expected externally reachable MCP resource URL. Validate against the deployed FQDN before Foundry registration.')
param resourceUrl string

@description('Set true only after immutable images and secure runtime configuration are supplied.')
param deployApplication bool = false

@description('AppOnboard scaffold session identifier.')
param sessionId string

@description('Display name of the deployment operator.')
param deployedBy string

@description('ISO 8601 scaffold creation timestamp.')
param createdAt string

var tags = {
  'app-onboard-skill': 'true'
  'app-onboard-session-id': sessionId
  'created-at': createdAt
  environment: scopeKey
  'deployed-by': deployedBy
  'aifactory.managed_by': 'aifactory-mcp'
}

var validatedMcpImage = !deployApplication || contains(mcpImage, '@sha256:') ? mcpImage : fail('mcpImage must be an immutable @sha256 digest when deployApplication is true.')
var validatedApiImage = !deployApplication || contains(apiImage, '@sha256:') ? apiImage : fail('apiImage must be an immutable @sha256 digest when deployApplication is true.')
var validatedAgentConfigJson = !deployApplication || !empty(agentConfigJson) ? agentConfigJson : fail('agentConfigJson is required when deployApplication is true.')
var validatedApplicationAuthJson = !deployApplication || !empty(applicationAuthJson) ? applicationAuthJson : fail('applicationAuthJson is required when deployApplication is true.')

resource targetResourceGroup 'Microsoft.Resources/resourceGroups@2023-07-01' existing = {
  name: resourceGroupName
}

resource registryResourceGroup 'Microsoft.Resources/resourceGroups@2023-07-01' existing = {
  name: registryResourceGroupName
}

module identity './modules/identity.bicep' = {
  name: 'aifactory-mcp-identity'
  scope: targetResourceGroup
  params: {
    identityName: identityName
    location: location
    tags: tags
  }
}

module secretAccess './modules/role-assignments.bicep' = {
  name: 'aifactory-mcp-secret-access'
  scope: targetResourceGroup
  params: {
    identityPrincipalId: identity.outputs.principalId
    keyVaultName: keyVaultName
    apiKeySecretName: apiKeySecretName
  }
  dependsOn: [
    identity
  ]
}

module registryPull './modules/registry-pull.bicep' = {
  name: 'aifactory-mcp-registry-pull'
  scope: registryResourceGroup
  params: {
    identityPrincipalId: identity.outputs.principalId
    registryName: registryName
  }
  dependsOn: [
    identity
  ]
}

module application './modules/application.bicep' = if (deployApplication) {
  name: 'aifactory-mcp-application'
  scope: targetResourceGroup
  params: {
    appName: appName
    location: location
    managedEnvironmentName: environmentName
    registryName: registryName
    identityResourceId: identity.outputs.resourceId
    identityClientId: identity.outputs.clientId
    keyVaultName: keyVaultName
    apiKeySecretName: apiKeySecretName
    mcpImage: validatedMcpImage
    apiImage: validatedApiImage
    agentConfigJson: validatedAgentConfigJson
    applicationAuthJson: validatedApplicationAuthJson
    scopeKey: scopeKey
    resourceUrl: resourceUrl
    tags: tags
  }
  dependsOn: [
    secretAccess
    registryPull
  ]
}

output appId string = application.?outputs.?appId ?? ''
output serviceUri string = deployApplication ? resourceUrl : ''
output identityResourceId string = identity.outputs.resourceId
output identityPrincipalId string = identity.outputs.principalId
output identityClientId string = identity.outputs.clientId
