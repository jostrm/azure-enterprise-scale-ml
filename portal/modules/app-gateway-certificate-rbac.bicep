// Replaces the role assignment at the end of aif_prepare_simple_application_gateway: the gateway identity
// reads the certificate secret. Scope is the certificate vault only.
targetScope = 'resourceGroup'

param certificateVaultId string
param principalId string

var keyVaultSecretsUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')

resource vault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: last(split(certificateVaultId, '/'))
}

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, principalId, keyVaultSecretsUser)
  scope: vault
  properties: {
    roleDefinitionId: keyVaultSecretsUser
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
