// ================================================================
// RBAC AI STORAGE ACCOUNTS FOR AI FOUNDRY V2.1 MODULE
// This module assigns RBAC roles to AI Foundry system-assigned MI on Storage Accounts
// Roles: Storage Blob Data Contributor, Storage File Data Privileged Contributor
// ================================================================

@description('The name of the storage account')
param storageAccountName string

@description('The principal ID of the AI Foundry system-assigned managed identity')
param principalId string

@description('Storage Blob Data Contributor role ID')
param storageBlobDataContributorRoleId string

@description('Storage File Data Privileged Contributor role ID')
param storageFileDataPrivilegedContributorRoleId string

@description('Azure AI Developer role ID')
param azureAIDeveloperRoleId string = '64702f94-c441-49e6-a78b-ef80e0188fee'

@description('Array of user object IDs to assign Azure AI Developer role')
param userObjectIds array = []

@description('Whether the user principals are Azure AD Groups')
param useAdGroups bool = true

// Reference the existing storage account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

// Assign Storage Blob Data Contributor role
resource storageBlobDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, principalId, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Storage File Data Privileged Contributor role
resource storageFileDataPrivilegedContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, principalId, storageFileDataPrivilegedContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Azure AI Developer role to AI Foundry system-assigned MI
resource azureAIDeveloperSystemMIAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, principalId, azureAIDeveloperRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Azure AI Developer role to users/groups for Chat with Data scenarios
resource azureAIDeveloperUserAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, index) in userObjectIds: {
  name: guid(storageAccount.id, userObjectId, azureAIDeveloperRoleId, string(index))
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

@description('Storage Account RBAC assignments completed successfully')
output rbacAssignmentsCompleted bool = true

@description('Number of role assignments created')
output roleAssignmentsCount int = 2 + length(userObjectIds)
