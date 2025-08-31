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

@description('AI Search RBAC assignments completed successfully')
output rbacAssignmentsCompleted bool = true

@description('Number of role assignments created')
output roleAssignmentsCount int = 3
