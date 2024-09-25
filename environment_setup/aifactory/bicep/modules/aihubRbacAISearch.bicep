param aiSearchMIObjectId string // Object ID of the Managed Identity for Azure AI Search
// Parameters for resource
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param aiSearchName string // Resource ID for Azure AI Search
param resourceGroupId string // Resource group ID where resources are located
param userObjectIds array // Specific user's object ID's for "User to Service Table"
param aiServicesName string // AIServices name, e.g. AIStudio name
param openAIName string // Azure OpenAI

// Role Definition IDs
var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesOpenAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // ID for the built-in Contributor role
var cognitiveServicesUserRoleID = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Placeholder ID for the Cognitive Services User role
var keyVaultAdministrator = '00482a5a-887f-4fb3-b363-3b7fe8e74483'

// Maybe
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'

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

// --------------- SP for Azure AI services -START ---------------- //

resource roleAssignmentSearchIndexDataReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataReaderRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
    description: '010'
  }
  scope: existingAiSearch
}

resource roleAssignmentSearchIndexDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    description: '011'
  }
  scope: existingAiSearch
}
resource roleAssignmentSearchServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    description: '012'
  }
  scope: existingAiSearch
}

resource roleAssignmentStorageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    description: '013'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageBlobDataContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    description: '014'
  }
  scope: existingStorageAccount2
}

//Extra roles to be verified and adjusted

var aiInferenceDeploymentOperatorRoleId = '3afb7f49-54cb-416e-8c09-6dc049efa503'

resource roleAssignmentAIInferenceDeploymentOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, aiInferenceDeploymentOperatorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiInferenceDeploymentOperatorRoleId)
    description: '015'
  }
  scope: resourceGroup()
}

resource roleAssignmentKeyVaultAdministrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, keyVaultAdministrator, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultAdministrator)
    description: '016'
  }
  scope:resourceGroup()
}

var userAccessAdministratorRoleId = '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9'

resource roleAssignmentUserAccessAdministrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, userAccessAdministratorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', userAccessAdministratorRoleId)
    description: '017'
  }
  scope: resourceGroup()
}


resource roleAssignmentCognitiveServicesOpenAIContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    description: '018'
  }
  scope: existingAiServicesResource
}

resource roleAssignmentStorageFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageFileDataPrivilegedContributorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    description: '019b'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageFileDataPrivilegedContributorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    description: '019a'
  }
  scope: existingStorageAccount2
}


// --------------- AIServices MI END ---------------- //

// --------------- USERS START ---------------- //

// SEARCH
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


// AI SERVICES
resource userRoleAssignmentContributorAiSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, searchServiceContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'022: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name}'
  }
  scope:existingAiSearch
}]

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

// Outputs
output roleAssignmentSearchIndexDataReaderName string = roleAssignmentSearchIndexDataReader.name
output roleAssignmentSearchIndexDataContributorName string = roleAssignmentSearchIndexDataContributor.name
output roleAssignmentSearchServiceContributorName string = roleAssignmentSearchServiceContributor.name
output roleAssignmentStorageBlobDataContributorName string = roleAssignmentStorageBlobDataContributor.name
output roleAssignmentCognitiveServicesOpenAIContributorName string = roleAssignmentCognitiveServicesOpenAIContributor.name


// Outputs for GUIDs with resource names
output roleAssignmentSearchIndexDataReaderGUID string = guid(existingAiSearch.id, searchIndexDataReaderRoleId, aiSearchMIObjectId)
output roleAssignmentSearchIndexDataContributorGUID string = guid(existingAiSearch.id, searchIndexDataContributorRoleId, aiSearchMIObjectId)
output roleAssignmentSearchServiceContributorGUID string = guid(existingAiSearch.id, searchServiceContributorRoleId, aiSearchMIObjectId)
output roleAssignmentStorageBlobDataContributorGUID string = guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiSearchMIObjectId)
output roleAssignmentCognitiveServicesOpenAIContributorGUID string = guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, aiSearchMIObjectId)
