// ================================================================
// RBAC KEY VAULT FOR AI FOUNDRY AGENTS MODULE
// This module assigns RBAC roles to AI Foundry system-assigned MI on Key Vault
// Roles: Key Vault Secrets User, Key Vault Contributor
// Required for: Agent playground, API key management, connection strings
// ================================================================

@description('The name of the Key Vault service')
param keyVaultName string

@description('The name of the AI Foundry account to get the principal ID from')
param aiFoundryAccountName string

@description('The principal ID of the AI Foundry project system-assigned managed identity')
param projectPrincipalId string = ''

@description('Key Vault Secrets User role ID')
param keyVaultSecretsUserRoleId string = '4633458b-17de-408a-b874-0445c86b69e6'

@description('Key Vault Contributor role ID')
param keyVaultContributorRoleId string = 'f25e0fa2-a7c8-4377-a976-54943a77a395'

@description('Key Vault Secrets Officer role ID - For Agent operations')
param keyVaultSecretsOfficerRoleId string = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

// Reference the AI Foundry account to get its system-assigned managed identity
#disable-next-line BCP081
resource aiFoundryAccount 'Microsoft.CognitiveServices/accounts@2025-07-01-preview' existing = {
  name: aiFoundryAccountName
}

// Get the principal ID from the AI Foundry account's system-assigned managed identity
var principalId = aiFoundryAccount.identity.principalId

// Reference the existing Key Vault service
resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
}

// Assign Key Vault Secrets User role to AI Foundry system-assigned MI
resource keyVaultSecretsUserSystemMIAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, aiFoundryAccount.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Key Vault Contributor role to AI Foundry system-assigned MI
resource keyVaultContributorSystemMIAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, aiFoundryAccount.id, keyVaultContributorRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// ============== PROJECT PRINCIPAL ROLE ASSIGNMENTS ==============

// Assign Key Vault Secrets User role to Project Principal
resource projectKeyVaultSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(keyVault.id, projectPrincipalId, keyVaultSecretsUserRoleId, 'project')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: 'AI Foundry project managed identity - Key Vault Secrets User for Agent operations'
  }
}

// Assign Key Vault Secrets Officer role to Project Principal
resource projectKeyVaultSecretsOfficerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(keyVault.id, projectPrincipalId, keyVaultSecretsOfficerRoleId, 'project')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: 'AI Foundry project managed identity - Key Vault Secrets Officer for Agent operations'
  }
}

@description('Key Vault RBAC assignments completed successfully')
output rbacAssignmentsCompleted bool = true

@description('Number of role assignments created')
output roleAssignmentsCount int = (2 + (!empty(projectPrincipalId) ? 2 : 0))
