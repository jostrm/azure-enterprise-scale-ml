// Data-plane roles for the lifecycle Function's identity. Assignment names include the principal, so recreating the
// app (new identity) never collides with orphaned assignments.

param principalId string
param storageAccountName string
param grantQueueRole bool = true
@description('RBAC-enabled Key Vault the Function reads its secrets from. Empty: no grant.')
param keyVaultName string = ''

var storageRoles = concat([
  'b7e6dc6d-f1e8-4753-8033-0f276bb0955b' // Storage Blob Data Owner (identity-based AzureWebJobsStorage)
  '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3' // Storage Table Data Contributor (lifecycle state table)
], grantQueueRole ? [
  '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // Storage Queue Data Contributor (event queue)
] : [])
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = if (!empty(keyVaultName)) {
  name: empty(keyVaultName) ? 'unused' : keyVaultName
}

resource storageAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in storageRoles: {
  name: guid(storage.id, principalId, role)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource vaultAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(keyVaultName)) {
  name: guid(vault.id, principalId, keyVaultSecretsUser)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
