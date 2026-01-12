// ================================================================
// KEY VAULT RBAC SINGLE ASSIGNMENT MODULE
// This module assigns a specific RBAC role to a single principal on Key Vault
// Replaces individual access policy assignments
// ================================================================

@description('Optional deterministic suffix. Leave empty to derive from scope + principal + role.')
param assignmentName string = ''

@description('The name of the Key Vault')
param keyVaultName string

@description('Principal ID (user, service principal, or managed identity)')
param principalId string

@description('Key Vault role ID to assign')
param keyVaultRoleId string

@description('Principal type')
@allowed(['User', 'Group', 'ServicePrincipal'])
param principalType string = 'ServicePrincipal'

@description('Optional description for the role assignment')
param roleDescription string = ''

// Reference the existing Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
}

// Use deterministic GUID based on scope, principal, role (and optional suffix) to keep deployments idempotent
var assignmentGuid = empty(assignmentName)
  ? guid(keyVault.id, principalId, keyVaultRoleId)
  : guid(keyVault.id, principalId, keyVaultRoleId, assignmentName)

resource keyVaultRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: assignmentGuid
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultRoleId)
    principalId: principalId
    principalType: principalType
    description: !empty(roleDescription) ? roleDescription : 'Key Vault RBAC assignment for ${principalType}'
  }
}

@description('Role assignment completed successfully')
output roleAssignmentCompleted bool = true

@description('Role assignment resource ID')
output roleAssignmentId string = keyVaultRoleAssignment.id

@description('Key Vault resource ID')
output keyVaultId string = keyVault.id
