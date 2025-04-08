param aiServicesPrincipalId string // Principal ID for Azure AI services/OpenAI
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param aiSearchName string // Resource ID for Azure AI Search

// ###### 2024-12-19 TechExcel ###### 
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // User -> RG

// Container Registry (EP, WebApp, Azure Function)
var acrPushRoleId = '8311e382-0749-4cb8-b61a-304f252e45ec' // SP, user -> RG
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // EP, App service or Function app -> RG

// Azure ML (AI Hub, AIProject)
var azureMLDataScientistRoleId = 'f6c7c914-8db3-469d-8ca1-694a8f32e121' // SP, user -> AI Hub, AI Project (RG)
var azureAIDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee'  // SP, user -> AI Hub
var cognitiveServicesCustomVisionContributorRoleId = 'c1ff6cc2-c111-46fe-8896-e0ef812ad9f3' // User, AI hub, AI project -> storage
var azureAIInferenceDeploymentOperatorRoleId = '3afb7f49-54cb-416e-8c09-6dc049efa503'  // User -> AI project
var azureAIAdministrator = 'b78c5d69-af96-48a3-bf8d-a8b4d589de94' // AI Project (to all underlying resources)

// AzureML: Managed Online Endpoints & User & SP
var azureMachineLearningWorkspaceConnectionSecretsReaderRoleId = 'ea01e6af-a1c1-4350-9563-ad00f8c72ec5'  // SP, user, EP -> AI Hub, AI Project (RG)
var azureMLMetricsWriter ='635dd51f-9968-44d3-b7fb-6d9a6bd613ae' // EP -> AI project

// Storage
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe' // AI Search, AI Hub, AI Project, User, SP -> Storage
var storageFileDataContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd' // AI Search, AI Hub, AI Project, User, SP -> Storage

// Cognitive Services: OpenAI, AI services
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // SP, User, AI Search, AIHub, AIProject -> AI service, OpenAI

// Search
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // User, SP, AI Services, etc -> AI Search
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // SP, User, AIHub, AIProject, App Service/FunctionApp -> AI Search
//var userAccessAdministratorRoleId = '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9' // AI services, AI Hub, AI Project <-> AI SEARCH

// ###### 2024-12-19 TechExcel ###### END
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName2
}

resource existingAiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' existing = {
  name: aiSearchName
}

resource roleAssignmentSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    description: '010'
  }
  scope: existingAiSearch
}
resource roleAssignmentSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataReader, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReader)
    description: '010'
  }
  scope: existingAiSearch
}

resource roleAssignmentSearchServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    description: '012'
  }
  scope: existingAiSearch
}
// AI Search - END

// 002 -> Storage START

resource roleAssignmentStorageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    description: '013'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageBlobDataContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    description: '014'
  }
  scope: existingStorageAccount2
}

// FILE
resource roleAssignmentStorageFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId,aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    description: '019b'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageFileDataContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    description: '019a'
  }
  scope: existingStorageAccount2
}

output roleAssignmentSearchIndexDataContributorGUID string = guid(existingAiSearch.id, searchIndexDataContributorRoleId, aiServicesPrincipalId)
output roleAssignmentSearchServiceContributorGUID string = guid(existingAiSearch.id, searchServiceContributorRoleId, aiServicesPrincipalId)
output roleAssignmentStorageBlobDataContributorGUID1 string = guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiServicesPrincipalId)
output roleAssignmentStorageFileDataContributorGUID1 string = guid(existingStorageAccount.id, storageFileDataContributorRoleId, aiServicesPrincipalId)
output roleAssignmentStorageBlobDataContributorGUID2 string = guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, aiServicesPrincipalId)
output roleAssignmentStorageFileDataContributorGUID2 string = guid(existingStorageAccount2.id, storageFileDataContributorRoleId, aiServicesPrincipalId)
