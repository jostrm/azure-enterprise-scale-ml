param principalIdMI string
param aiSearchName string //scope:rg '8ebe5a00-799e-43f5-93ac-243d3dce84a7' //Search Index Data Contributor
param appInsightsName string // scope:rg '3913510d-42f4-4e42-8a64-420c390055eb' // Monitoring Metrics Publisher + '43d0d8ad-25c7-4714-9337-8ba259a9fe05' // Monitoring Reader
param resourceGroupId string //scope:rg f6c7c914-8db3-469d-8ca1-694a8f32e121' // Data Scientist Role 

// Search
//var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // User, SP, AI Services, etc -> AI Search
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // SP, User, Search, AIHub, AIProject, App Service/FunctionApp -> AI Search

// AI Hub and Project: RG
var aiHubProjectDataScientistRoleId = 'f6c7c914-8db3-469d-8ca1-694a8f32e121' // User, SP, AI Services, etc -> AI Hub and Project

// App Insights
var monitoringMetricsPublisherRoleId = '3913510d-42f4-4e42-8a64-420c390055eb' // User, SP, AI Services, etc -> App Insights
var monitoringReaderRoleId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05' // User, SP, AI Services, etc -> App Insights

resource existingAiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' existing = {
  name: aiSearchName
}
resource existingAppInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(appInsightsName)){
  name: appInsightsName
}

// Search
resource searchIndexDataContributorMI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, principalIdMI)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: principalIdMI
    principalType: 'ServicePrincipal'
    description:'searchIndexDataContributorRoleId to project service principal OID: ${principalIdMI} to ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}
resource searchServiceContributorRoleIdMI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, principalIdMI)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: principalIdMI
    principalType: 'ServicePrincipal'
    description:'searchServiceContributorRoleId to project service principal OID: ${principalIdMI} to ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}

// App Insights
resource monitoringMetricsPublisherRoleIdMI 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(!empty(appInsightsName)){
  name: guid(existingAppInsights.id, monitoringMetricsPublisherRoleId, principalIdMI)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisherRoleId)
    principalId: principalIdMI
    principalType: 'ServicePrincipal'
    description:'monitoringMetricsPublisherRoleId to project service principal OID:${principalIdMI} to ${existingAppInsights.name}'
  }
  scope:existingAppInsights
}
resource monitoringReaderRoleIdMI 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(!empty(appInsightsName)){
  name: guid(existingAppInsights.id, monitoringReaderRoleId, principalIdMI)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReaderRoleId)
    principalId: principalIdMI
    principalType: 'ServicePrincipal'
    description:'monitoringReaderRoleId to project service principal OID:${principalIdMI} to ${existingAppInsights.name}'
  }
  scope:existingAppInsights
}

// RG level
resource azureMLDataScientistRoleMI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, aiHubProjectDataScientistRoleId, principalIdMI)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiHubProjectDataScientistRoleId)
    principalId: principalIdMI
    principalType: 'ServicePrincipal'
    description:'azureMLDataScientistRoleId to project service principal OID:${principalIdMI} to ${resourceGroupId} on RG level'
  }
  scope:resourceGroup()
}

