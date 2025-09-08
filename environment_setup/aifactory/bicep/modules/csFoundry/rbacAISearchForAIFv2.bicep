// ================================================================
// RBAC AI SEARCH FOR AI FOUNDRY V2.1 MODULE
// This module assigns RBAC roles to AI Foundry system-assigned MI and project MI on AI Search
// Roles: Search Service Contributor, Search Index Data Reader, Search Index Data Contributor, Azure AI Developer
// Note: User RBAC assignments are handled in ../aiSearchRbacUsers.bicep module (called from 08-rbac.bicep)
// ================================================================

@description('The name of the AI Search service')
param aiSearchName string

@description('The principal ID of the AI Foundry system-assigned managed identity')
param principalId string

@description('The principal ID of the AI Foundry project system-assigned managed identity')
param projectPrincipalId string = ''

@description('Search Service Contributor role ID')
param searchServiceContributorRoleId string

@description('Search Index Data Reader role ID')
param searchIndexDataReaderRoleId string

@description('Search Index Data Contributor role ID')
param searchIndexDataContributorRoleId string

@description('Azure AI Developer role ID')
param azureAIDeveloperRoleId string = '64702f94-c441-49e6-a78b-ef80e0188fee'

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

// ============== PROJECT PRINCIPAL ROLE ASSIGNMENTS ==============

// Assign Search Service Contributor role to Project Principal
resource projectSearchServiceContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(aiSearchService.id, projectPrincipalId, searchServiceContributorRoleId, 'project')
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Search Index Data Reader role to Project Principal
resource projectSearchIndexDataReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(aiSearchService.id, projectPrincipalId, searchIndexDataReaderRoleId, 'project')
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Search Index Data Contributor role to Project Principal
resource projectSearchIndexDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(aiSearchService.id, projectPrincipalId, searchIndexDataContributorRoleId, 'project')
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Azure AI Developer role to Project Principal
resource projectAzureAIDeveloperAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(aiSearchService.id, projectPrincipalId, azureAIDeveloperRoleId, 'project')
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

@description('AI Search RBAC assignments completed successfully')
output rbacAssignmentsCompleted bool = true

@description('Number of role assignments created')
output roleAssignmentsCount int = (4 + (!empty(projectPrincipalId) ? 4 : 0))
