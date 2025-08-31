// ================================================================
// RBAC AI SEARCH FOR AI FOUNDRY V2.1 MODULE
// This module assigns RBAC roles to AI Foundry system-assigned MI on AI Search
// Roles: Search Service Contributor, Search Index Data Reader, Search Index Data Contributor
// ================================================================

@description('The name of the AI Search service')
param aiSearchName string

@description('The principal ID of the AI Foundry system-assigned managed identity')
param principalId string

@description('Search Service Contributor role ID')
param searchServiceContributorRoleId string

@description('Search Index Data Reader role ID')
param searchIndexDataReaderRoleId string

@description('Search Index Data Contributor role ID')
param searchIndexDataContributorRoleId string

@description('Azure AI Developer role ID')
param azureAIDeveloperRoleId string = '64702f94-c441-49e6-a78b-ef80e0188fee'

@description('Array of user object IDs to assign Azure AI Developer role')
param userObjectIds array = []

@description('Whether the user principals are Azure AD Groups')
param useAdGroups bool = true

// Reference the existing AI Search service
resource aiSearchService 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: aiSearchName
}

// Assign Search Service Contributor role
resource searchServiceContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiSearchService.id, principalId, searchServiceContributorRoleId)
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Search Index Data Reader role
resource searchIndexDataReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiSearchService.id, principalId, searchIndexDataReaderRoleId)
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Search Index Data Contributor role
resource searchIndexDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiSearchService.id, principalId, searchIndexDataContributorRoleId)
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Azure AI Developer role to AI Foundry system-assigned MI
resource azureAIDeveloperSystemMIAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiSearchService.id, principalId, azureAIDeveloperRoleId)
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Azure AI Developer role to users/groups for Chat with Data scenarios
resource azureAIDeveloperUserAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, index) in userObjectIds: {
  name: guid(aiSearchService.id, userObjectId, azureAIDeveloperRoleId, string(index))
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

@description('AI Search RBAC assignments completed successfully')
output rbacAssignmentsCompleted bool = true

@description('Number of role assignments created')
output roleAssignmentsCount int = 3 + length(userObjectIds)
