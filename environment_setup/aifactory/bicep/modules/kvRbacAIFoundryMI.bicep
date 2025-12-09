// ================================================================
// KEY VAULT RBAC FOR AI FOUNDRY SYSTEM MANAGED IDENTITY
// This module assigns Key Vault RBAC roles specifically to the 
// AI Foundry system-assigned managed identity for project Key Vault
// ================================================================

@description('The name of the project Key Vault')
param keyVaultName string

@description('The name of the AI Foundry account to get the principal ID from')
param aiFoundryAccountName string

@description('Key Vault Secrets Officer role ID - Can manage secrets')
param keyVaultSecretsOfficerRoleId string = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

@description('Key Vault Secrets User role ID - Can read secrets')
param keyVaultSecretsUserRoleId string = '4633458b-17de-408a-b874-0445c86b69e6'

// Reference the AI Foundry account to get its system-assigned managed identity
#disable-next-line BCP081
resource aiFoundryAccount 'Microsoft.CognitiveServices/accounts@2025-07-01-preview' existing = {
  name: aiFoundryAccountName
}

// Get the principal ID from the AI Foundry account's system-assigned managed identity
var principalId = aiFoundryAccount.identity.principalId

// Reference the existing Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
}

// Assign Key Vault Secrets Officer role to AI Foundry system-assigned MI
// This allows the AI Foundry to create and manage secrets for agents
resource keyVaultSecretsOfficerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, aiFoundryAccount.id, keyVaultSecretsOfficerRoleId, 'aifoundry-mi')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
    description: 'AI Foundry system managed identity - Key Vault Secrets Officer for Agent operations'
  }
}

@description('AI Foundry Key Vault RBAC assignment completed')
output rbacAssignmentCompleted bool = true

@description('Key Vault resource ID')
output keyVaultId string = keyVault.id
