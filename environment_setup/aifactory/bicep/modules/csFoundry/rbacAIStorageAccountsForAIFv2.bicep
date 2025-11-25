// ================================================================
// RBAC AI STORAGE ACCOUNTS FOR AI FOUNDRY V2.1 MODULE
// This module assigns RBAC roles to AI Foundry system-assigned MI on Storage Accounts
// Roles: Storage Blob Data Contributor, Storage File Data Privileged Contributor, Storage Queue Data Contributor
// Required for: Data access, PromptFlow, Azure Functions, Queue processing
// Note: Azure AI Developer role should be assigned on AI Services resource, not storage
// ================================================================

@description('The name of the storage account')
param storageAccountName string
param storageAccountName2 string

@description('The name of the AI Foundry account to get the principal ID from')
param aiFoundryAccountName string

@description('The principal ID of the AI Foundry project system-assigned managed identity')
param projectPrincipalId string = ''

@description('Storage Blob Data Contributor role ID')
param storageBlobDataContributorRoleId string

@description('Storage File Data Privileged Contributor role ID')
param storageFileDataPrivilegedContributorRoleId string

@description('Storage Queue Data Contributor role ID')
param storageQueueDataContributorRoleId string = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

// Reference the AI Foundry account to get its system-assigned managed identity
resource aiFoundryAccount 'Microsoft.CognitiveServices/accounts@2025-07-01-preview' existing = {
  name: aiFoundryAccountName
}

// Get the principal ID from the AI Foundry account's system-assigned managed identity
var principalId = aiFoundryAccount.identity.principalId

// Reference the existing storage account
resource storageAccount 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: storageAccountName
}

// Reference the second existing storage account
resource storageAccount2 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: storageAccountName2
}

// Assign Storage Blob Data Contributor role
resource storageBlobDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, aiFoundryAccount.id, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Storage File Data Privileged Contributor role
resource storageFileDataPrivilegedContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, aiFoundryAccount.id, storageFileDataPrivilegedContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Storage Queue Data Contributor role
resource storageQueueDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, aiFoundryAccount.id, storageQueueDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// ============== PROJECT PRINCIPAL ROLE ASSIGNMENTS ==============

// Assign Storage Blob Data Contributor role to Project Principal
resource projectStorageBlobDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(storageAccount.id, projectPrincipalId, storageBlobDataContributorRoleId, 'project')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Storage File Data Privileged Contributor role to Project Principal
resource projectStorageFileDataPrivilegedContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(storageAccount.id, projectPrincipalId, storageFileDataPrivilegedContributorRoleId, 'project')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Storage Queue Data Contributor role to Project Principal
resource projectStorageQueueDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(storageAccount.id, projectPrincipalId, storageQueueDataContributorRoleId, 'project')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ============== STORAGE ACCOUNT 2 ROLE ASSIGNMENTS ==============

// Assign Storage Blob Data Contributor role to Storage Account 2
resource storageBlobDataContributorAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount2.id, aiFoundryAccount.id, storageBlobDataContributorRoleId)
  scope: storageAccount2
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Storage File Data Privileged Contributor role to Storage Account 2
resource storageFileDataPrivilegedContributorAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount2.id, aiFoundryAccount.id, storageFileDataPrivilegedContributorRoleId)
  scope: storageAccount2
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Storage Queue Data Contributor role to Storage Account 2
resource storageQueueDataContributorAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount2.id, aiFoundryAccount.id, storageQueueDataContributorRoleId)
  scope: storageAccount2
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// ============== STORAGE ACCOUNT 2 PROJECT PRINCIPAL ROLE ASSIGNMENTS ==============

// Assign Storage Blob Data Contributor role to Project Principal for Storage Account 2
resource projectStorageBlobDataContributorAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(storageAccount2.id, projectPrincipalId, storageBlobDataContributorRoleId, 'project')
  scope: storageAccount2
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Storage File Data Privileged Contributor role to Project Principal for Storage Account 2
resource projectStorageFileDataPrivilegedContributorAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(storageAccount2.id, projectPrincipalId, storageFileDataPrivilegedContributorRoleId, 'project')
  scope: storageAccount2
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Storage Queue Data Contributor role to Project Principal for Storage Account 2
resource projectStorageQueueDataContributorAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(storageAccount2.id, projectPrincipalId, storageQueueDataContributorRoleId, 'project')
  scope: storageAccount2
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

@description('Storage Account RBAC assignments completed successfully')
output rbacAssignmentsCompleted bool = true

@description('Number of role assignments created')
output roleAssignmentsCount int = (6 + (!empty(projectPrincipalId) ? 6 : 0))
