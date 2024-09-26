// Docs: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/use-your-data-securely#create-shared-private-link

// Parameters for resource and principal IDs
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param aiSearchName string // Resource ID for Azure AI Search
param resourceGroupId string // Resource group ID where resources are located
param userObjectIds array // Specific user's object ID's for "User to Service Table"
param aiServicesName string // AIServices name, e.g. AIStudio name
param openAIName string
param contentSafetyName string

// Role Definition IDs
var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesOpenAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var roleBasedAccessControlAdminForWebApp = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'

var congnitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Azure content safety
var readerRole = 'acdd72a7-3385-48ef-bd42-f606fba81ae7' // Azure content safety
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // many services

// Maybe
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2021-08-01' existing = {
  name: storageAccountName
}
resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2021-08-01' existing = {
  name: storageAccountName2
}

resource existingAiSearch 'Microsoft.Search/searchServices@2021-04-01-preview' existing = {
  name: aiSearchName
}

resource existingAiServicesResource 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: aiServicesName
}
resource existingOpenAI 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: openAIName
}
resource existingContentSafety 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: contentSafetyName
}


// --------------- USERS START ---------------- //

// USERES to AI SEARCH
resource roleAssignmentSearchIndexUserDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'020: SearchIndexUserDataContributor to USER with OID  ${userObjectIds[i]} for : ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]

resource roleAssignmentSearchContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiSearch.id, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'021: Contributor to USER with OID  ${userObjectIds[i]} for : ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]

resource userRoleAssignmentContributorAiSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'022: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]

// USERS to AIServices
resource roleAssignmentCognitiveServicesOpenAICotributorUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: OpenAIContributorRole to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to call data on data plane'
  }
  scope:existingAiServicesResource
}]

resource roleAssignmentCognitiveServicesOpenAIUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'024: OpenAICognitiveServicesUSer to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to list API keys'
  }
  scope:existingAiServicesResource
}]


resource userRoleAssignmentContributorAiServices 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'025: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]

// USERS to OpenAI

resource openAICogUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingOpenAI.id, congnitiveServicesUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', congnitiveServicesUserRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'- Cognitive services User (read and list keys) to USER with OID  ${userObjectIds[i]} for : ${existingOpenAI.name} to call data on data plane'
  }
  scope:existingOpenAI
}]

resource openAIServicesOpenAICotributorUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingOpenAI.id, cognitiveServicesOpenAIContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: OpenAIContributorRole to USER with OID  ${userObjectIds[i]} for : ${existingOpenAI.name} to call data on data plane'
  }
  scope:existingOpenAI
}]

resource openAICognitiveServicesOpenAIUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingOpenAI.id, cognitiveServicesOpenAIUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'024: OpenAICognitiveServicesUSer to USER with OID  ${userObjectIds[i]} for : ${existingOpenAI.name} to list API keys'
  }
  scope:existingOpenAI
}]

resource openAIRoleAssignmentContributorAiServices 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingOpenAI.id, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'025: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingOpenAI.name}'
  }
  scope:existingOpenAI
}]

resource openAIRoleBasedAccessControlAdmin 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingOpenAI.id, roleBasedAccessControlAdminForWebApp, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdminForWebApp)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'025: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingOpenAI.name}'
  }
  scope:existingOpenAI
}]

// USERS to ContentSafety: Cognitive Services Users and Reader.

resource contentSafetyServicesOpenAICotributorUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingContentSafety.id, congnitiveServicesUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', congnitiveServicesUserRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: OpenAIContributorRole to USER with OID  ${userObjectIds[i]} for : ${existingContentSafety.name} to call data on data plane'
  }
  scope:existingContentSafety
}]


resource contentSafetyCognitiveServicesOpenAIUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingContentSafety.id, readerRole, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRole)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'024: OpenAICognitiveServicesUSer to USER with OID  ${userObjectIds[i]} for : ${existingContentSafety.name} to list API keys'
  }
  scope:existingContentSafety
}]

/*
resource contentSafetyRoleAssignmentContributorAiServices 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingContentSafety.id, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'025: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingContentSafety.name}'
  }
  scope:existingContentSafety
}]

*/


// USERS to STORAGE

resource userRoleAssignmentContributorStorage1 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount.id, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'026a: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]
resource userRoleAssignmentContributorStorage2 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount2.id, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'026b: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}]

resource userStorageBlobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'027a: StorageBlobDataContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]
resource userStorageBlobDataContributorRole2 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'027b: StorageBlobDataContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}]

resource roleAssignmentStorageUserFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount.id, storageFileDataPrivilegedContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'028a: FileDataPrivilegedContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]
resource roleAssignmentStorageUserFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount2.id, storageFileDataPrivilegedContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'028b: FileDataPrivilegedContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}]

// RG
resource userRoleAssignmentContributorStorageAccount 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'029: CONTRIBUTOR on RG to USER with OID  ${userObjectIds[i]} for : ${resourceGroupId}'
  }
  scope:resourceGroup()
}]

// --------------- USERS END ---------------- //

