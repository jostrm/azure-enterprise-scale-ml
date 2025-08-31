// ================================================================
// KEY VAULT RBAC ASSIGNMENTS FOR USERS MODULE
// This module assigns RBAC roles to users/groups on Key Vault
// Replaces access policies with RBAC model
// ================================================================

@description('The name of the Key Vault')
param keyVaultName string

@description('Array of user object IDs')
param userObjectIds array = []

@description('Array of service principal object IDs')
param servicePrincipalIds array = []

@description('Array of managed identity object IDs')
param managedIdentityIds array = []

@description('Whether user principals are Azure AD Groups')
param useAdGroups bool = true

@description('Key Vault Administrator role ID - Full access')
param keyVaultAdministratorRoleId string = '00482a5a-887f-4fb3-b363-3b7fe8e74483'

@description('Key Vault Secrets Officer role ID - Manage secrets')
param keyVaultSecretsOfficerRoleId string = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

@description('Key Vault Secrets User role ID - Read secrets')
param keyVaultSecretsUserRoleId string = '4633458b-17de-408a-b874-0445c86b69e6'

@description('Key Vault Contributor role ID - Management operations')
param keyVaultContributorRoleId string = 'f25e0fa2-a7c8-4377-a976-54943a77a395'

// Reference the existing Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// Assign Key Vault Secrets User role to users/groups
resource keyVaultSecretsUserAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, index) in userObjectIds: {
  name: guid(keyVault.id, userObjectId, keyVaultSecretsUserRoleId, string(index))
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

// Assign Key Vault Secrets Officer role to service principals (equivalent to get,list,set permissions)
resource keyVaultSecretsOfficerSpAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (spId, index) in servicePrincipalIds: {
  name: guid(keyVault.id, spId, keyVaultSecretsOfficerRoleId, string(index))
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalId: spId
    principalType: 'ServicePrincipal'
  }
}]

// Assign Key Vault Secrets Officer role to managed identities
resource keyVaultSecretsOfficerMiAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (miId, index) in managedIdentityIds: {
  name: guid(keyVault.id, miId, keyVaultSecretsOfficerRoleId, string(index))
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalId: miId
    principalType: 'ServicePrincipal'
  }
}]

@description('Key Vault RBAC assignments completed successfully')
output rbacAssignmentsCompleted bool = true

@description('Number of role assignments created')
output roleAssignmentsCount int = length(userObjectIds) + length(servicePrincipalIds) + length(managedIdentityIds)

@description('Key Vault resource ID')
output keyVaultId string = keyVault.id
