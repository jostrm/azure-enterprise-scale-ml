targetScope = 'resourceGroup'

@description('Object ID of the user-assigned managed identity.')
param identityPrincipalId string

@description('Name of the existing RBAC-enabled Key Vault.')
param keyVaultName string

@description('Name of the existing API-key secret.')
param apiKeySecretName string

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource keyVault 'Microsoft.KeyVault/vaults@2026-05-15' existing = {
  name: keyVaultName
}

resource apiKeySecret 'Microsoft.KeyVault/vaults/secrets@2026-05-15' existing = {
  parent: keyVault
  name: apiKeySecretName
}

resource apiKeyReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(apiKeySecret.id, identityPrincipalId, keyVaultSecretsUserRoleId)
  scope: apiKeySecret
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output roleAssignmentId string = apiKeyReader.id
