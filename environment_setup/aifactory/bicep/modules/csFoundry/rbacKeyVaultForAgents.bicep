// ================================================================
// RBAC KEY VAULT FOR AI FOUNDRY AGENTS MODULE
// This module assigns RBAC roles to AI Foundry system-assigned MI on Key Vault
// Roles: Key Vault Secrets User, Key Vault Contributor
// Required for: Agent playground, API key management, connection strings
// ================================================================

@description('The name of the Key Vault service')
param keyVaultName string

@description('The principal ID of the AI Foundry system-assigned managed identity')
param principalId string

@description('Key Vault Secrets User role ID')
param keyVaultSecretsUserRoleId string = '4633458b-17de-408a-b874-0445c86b69e6'

@description('Key Vault Contributor role ID')
param keyVaultContributorRoleId string = 'f25e0fa2-a7c8-4377-a976-54943a77a395'

@description('Array of user object IDs to assign Key Vault roles')
param userObjectIds array = []

@description('Whether the user principals are Azure AD Groups')
param useAdGroups bool = true

// Reference the existing Key Vault service
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// Assign Key Vault Secrets User role to AI Foundry system-assigned MI
resource keyVaultSecretsUserSystemMIAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, principalId, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Key Vault Contributor role to AI Foundry system-assigned MI
resource keyVaultContributorSystemMIAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, principalId, keyVaultContributorRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Key Vault Secrets User role to users/groups for Agent playground
resource keyVaultSecretsUserAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, index) in userObjectIds: {
  name: guid(keyVault.id, userObjectId, keyVaultSecretsUserRoleId, string(index))
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

@description('Key Vault RBAC assignments completed successfully')
output rbacAssignmentsCompleted bool = true

@description('Number of role assignments created')
output roleAssignmentsCount int = 2 + length(userObjectIds)
