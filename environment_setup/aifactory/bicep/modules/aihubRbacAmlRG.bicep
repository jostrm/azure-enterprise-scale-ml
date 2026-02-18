param azureMachineLearningObjectId string
param aiHubName string = ''
param aiHubPrincipalId string = ''
param aiHubProjectName string = ''
param aiHubProjectPrincipalId string = ''
param aiSearchName string = ''
@description('Contributor role ID for RBAC assignments. Default is the built-in Contributor role.')
param contributorRoleId string = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

var aml_appId = '0736f41a-0425-4b46-bdb5-1563eff02385'
var azureAIAdministrator = 'b78c5d69-af96-48a3-bf8d-a8b4d589de94' // AIHub -> RG: (AIServices, AI Projects, Agents)
// contributorRoleId is now a parameter 
// Search
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // User, SP, AI Services, etc -> AI Search

resource aiHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing  = if(!empty(aiHubName)) {
  name: aiHubName
}
// Please ensure that the project managed identity has Search Index Data Reader and Search Service Contributor roles on the Search resource
resource existingAIHubProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing  = if(!empty(aiHubProjectName)) {
  name: aiHubProjectName
}
resource existingAiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' existing = if(!empty(aiSearchName)) {
  name: aiSearchName
}

// Project
@description('Role Assignment to Azure AI Search: SearchIndexDataContributor AI Hub project. Grants full access to Azure Cognitive Search index data')
resource searchServiceContributorRole2Project 'Microsoft.Authorization/roleAssignments@2022-04-01'  = if(!empty(aiSearchName)) {
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, existingAIHubProject.id)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: aiHubProjectPrincipalId // existingAIHubProject.id
    principalType:'ServicePrincipal'
    description:'001 - searchServiceContributorRoleId to AI Hub project'
  }
  scope:existingAiSearch
}
@description('Role Assignment to Azure AI Search: searchIndexDataReader for users. 	Grants full access to Azure Cognitive Search index data')
resource searchIndexDataReader2Project 'Microsoft.Authorization/roleAssignments@2022-04-01'  = if(!empty(aiSearchName)) {
  name: guid(existingAiSearch.id, searchIndexDataReader, existingAIHubProject.id)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReader)
    principalId: aiHubProjectPrincipalId // existingAIHubProject.id
    principalType:'ServicePrincipal'
    description:'002 - searchIndexDataReader to AI Hub project'
  }
  scope:existingAiSearch
}
@description('Role Assignment to Azure AI Search: searchIndexDataReader for users. 	Grants full access to Azure Cognitive Search index data')
resource searchIndexDataContributor2Project 'Microsoft.Authorization/roleAssignments@2022-04-01'  = if(!empty(aiSearchName)) {
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, existingAIHubProject.id)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: aiHubProjectPrincipalId // existingAIHubProject.id
    principalType:'ServicePrincipal'
    description:'003 - searchIndexDataContributorRoleId to AI Hub project'
  }
  scope:existingAiSearch
}

// RG scope: Contributor for Aml OID and AI Hub
@description('Role Assignment for ResoureGroup: AzureML OID for Contributor')
resource contributorAmlOID 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, contributorRoleId,azureMachineLearningObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: azureMachineLearningObjectId
    principalType: 'ServicePrincipal'
    description:'010 - Contributor on RG for AML SP on RG: ${resourceGroup().id}'
  }
  scope:resourceGroup()
}

@description('AI Hub: contributorRoleId:')
resource contributorAIHub 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(!empty(aiHubName)) {
  name: guid(resourceGroup().id, contributorRoleId, aiHubPrincipalId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: aiHubPrincipalId
    principalType: 'ServicePrincipal'
    description:'011 - Contributor on RG for AI Hub: ${aiHub.name}'
  }
  scope:resourceGroup()
}

