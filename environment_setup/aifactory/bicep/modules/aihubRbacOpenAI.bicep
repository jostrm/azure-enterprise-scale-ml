param openAIServicePrincipal string // Principal ID for Azure AI services/OpenAI
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param aiSearchName string // Resource ID for Azure AI Search
param openAIName string // Resource ID for Azure OpenAI
param userObjectIds array // Specific user's object ID's
@secure()
param servicePrincipleObjecId string // Service Principle Object ID
param useAdGroups bool = false

// Storage
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'

// Search
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // User, SP, AI Services, etc -> AI Search
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // SP, User, Search, AIHub, AIProject, App Service/FunctionApp -> AI Search

// Cognitive Services: OpenAI, AI services
// See table: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/role-based-access-control
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // SP, User, Search, AIHub, AIProject -> AI services, OpenAI
var cognitiveServicesOpenAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442' // All.  except: Access quota, create new Azure OpenAI, regenerate key under EP, content filter, add data source "on your data"
var cognitiveServicesContributorRoleId = '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68' // All, except: Access quota | Make inference API call with Microsoft Entra ID
var cognitiveServicesUsagesReaderId = 'bba48692-92b0-4667-a9ad-c31c7b334ac2' // Only Access quota (Minimal permission to view Cognitive Services usages)

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
resource existingOpenAIResource 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: openAIName
}

@description('Role Assignment for Azure AI Search: SearchIndexDataContributor for Azure OpenAI MI')
resource roleAssignmentSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, openAIServicePrincipal)
  properties: {
    principalId: openAIServicePrincipal
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    description: '010'
  }
  scope: existingAiSearch
}
resource roleAssignmentSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataReader, existingOpenAIResource.id)
  properties: {
    principalId: existingOpenAIResource.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReader)
    description: '010'
  }
  scope: existingAiSearch
}

@description('Role Assignment for Azure AI Search: SearchServiceContributor for Azure OpenAI MI')
resource roleAssignmentSearchServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, openAIServicePrincipal)
  properties: {
    principalId: openAIServicePrincipal
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    description: '012'
  }
  scope: existingAiSearch
}
// AI Search - END

// 002 -> Storage START

@description('Role Assignment for Azure Storage: StorageBlobDataContributor for Azure OpenAI MI')
resource roleAssignmentStorageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, openAIServicePrincipal)
  properties: {
    principalId: openAIServicePrincipal
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    description: '013'
  }
  scope: existingStorageAccount
}
@description('Role Assignment for Azure Storage 2: StorageBlobDataContributor for Azure OpenAI MI')
resource roleAssignmentStorageBlobDataContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, openAIServicePrincipal)
  properties: {
    principalId: openAIServicePrincipal
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    description: '014'
  }
  scope: existingStorageAccount2
}

@description('Role Assignment for Azure Storage: File Data Privileged Contributor for Azure OpenAI MI')
resource roleAssignmentStorageFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId, openAIServicePrincipal)
  properties: {
    principalId: openAIServicePrincipal
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    description: '019b'
  }
  scope: existingStorageAccount
}
@description('Role Assignment for Azure Storage 2: File Data Privileged Contributor for Azure OpenAI MI')
resource roleAssignmentStorageFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageFileDataContributorRoleId, openAIServicePrincipal)
  properties: {
    principalId: openAIServicePrincipal
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    description: '019a'
  }
  scope: existingStorageAccount2
}

// --------------- Users & SP -> OPENAI  ---------------- //

@description('Users to Azure AI Services: Cognitive Services Contributor for users. All, except: Access quota, Make inference API call with Microsoft Entra ID')
resource cognitiveServicesContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingOpenAIResource.id, cognitiveServicesContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'023: cognitiveServicesContributor role to USER with OID  ${userObjectIds[i]} for : ${existingOpenAIResource.name} to call data on data plane'
  }
  scope:existingOpenAIResource
}]
resource cognitiveServicesContributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingOpenAIResource.id, cognitiveServicesContributorRoleId, servicePrincipleObjecId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: servicePrincipleObjecId
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesContributor role to project service principal OID:${servicePrincipleObjecId} to ${existingOpenAIResource.name}'
  }
  scope:existingOpenAIResource
}
@description('Users to Azure AI Services: Cognitive Services Usage Reader for users. Only Access quota (Minimal permission to view Cognitive Services usages)')
resource cognitiveServicesUsagesReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingOpenAIResource.id, cognitiveServicesUsagesReaderId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUsagesReaderId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'023: cognitiveServicesUsagesReaderId role to USER with OID  ${userObjectIds[i]} for : ${existingOpenAIResource.name} to call data on data plane'
  }
  scope:existingOpenAIResource
}]
resource cognitiveServicesUsagesReaderSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingOpenAIResource.id, cognitiveServicesUsagesReaderId, servicePrincipleObjecId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUsagesReaderId)
    principalId: servicePrincipleObjecId
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesUsagesReader role to project service principal OID:${servicePrincipleObjecId} to ${existingOpenAIResource.name}'
  }
  scope:existingOpenAIResource
}

@description('Users to Azure AI Services: Cognitive Services OpenAI Contributor for users. Full access including the ability to fine-tune, deploy and generate text')
resource cognitiveServicesOpenAIContributorUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingOpenAIResource.id, cognitiveServicesOpenAIContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'023: OpenAIContributorRole to USER with OID  ${userObjectIds[i]} for : ${existingOpenAIResource.name} to call data on data plane'
  }
  scope:existingOpenAIResource
}]
resource cognitiveServicesOpenAIContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingOpenAIResource.id, cognitiveServicesOpenAIContributorRoleId, servicePrincipleObjecId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: servicePrincipleObjecId
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesOpenAIContributorRoleId to project service principal OID:${servicePrincipleObjecId} to ${existingOpenAIResource.name}'
  }
  scope:existingOpenAIResource
}

// AI Search -> OpenAI Service
resource cognitiveServicesOpenAIContributorAISearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingOpenAIResource.id, cognitiveServicesOpenAIContributorRoleId, existingAiSearch.id)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: existingAiSearch.identity.principalId
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesOpenAIContributorRoleId to project service principal OID:${existingAiSearch.identity.principalId} to ${existingAiSearch.name}'
  }
  scope:existingOpenAIResource
}

@description('Users to Azure AI Services: Cognitive Services OpenAI User:Read access to view files, models, deployments. The ability to create completion and embedding calls.')
resource roleAssignmentCognitiveServicesOpenAIUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingOpenAIResource.id, cognitiveServicesOpenAIUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'024: OpenAICognitiveServicesUSer to USER with OID  ${userObjectIds[i]} for : ${existingOpenAIResource.name} to list API keys'
  }
  scope:existingOpenAIResource
}]
resource roleAssignmentCognitiveServicesOpenAISP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingOpenAIResource.id, cognitiveServicesOpenAIUserRoleId, servicePrincipleObjecId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: servicePrincipleObjecId
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesOpenAIUserRoleId to project service principal OID:${servicePrincipleObjecId} to ${existingOpenAIResource.name}'
  }
  scope:existingOpenAIResource
}

output roleAssignmentSearchIndexDataContributorGUID string = guid(existingAiSearch.id, searchIndexDataContributorRoleId, openAIServicePrincipal)
output roleAssignmentSearchServiceContributorGUID string = guid(existingAiSearch.id, searchServiceContributorRoleId, openAIServicePrincipal)
output roleAssignmentStorageBlobDataContributorGUID1 string = guid(existingStorageAccount.id, storageBlobDataContributorRoleId, openAIServicePrincipal)
output roleAssignmentStorageFileDataContributorGUID1 string = guid(existingStorageAccount.id, storageFileDataContributorRoleId, openAIServicePrincipal)
output roleAssignmentStorageBlobDataContributorGUID2 string = guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, openAIServicePrincipal)
output roleAssignmentStorageFileDataContributorGUID2 string = guid(existingStorageAccount2.id, storageFileDataContributorRoleId, openAIServicePrincipal)
