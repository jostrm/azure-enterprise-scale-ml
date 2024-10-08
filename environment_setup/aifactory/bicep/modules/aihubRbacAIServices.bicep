param aiServicesPrincipalId string // Principal ID for Azure AI services
// Parameters for resource and principal IDs
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param aiSearchName string // Resource ID for Azure AI Search
param resourceGroupId string // Resource group ID where resources are located
param aiServicesName string // AIServices name, e.g. AIStudio name
param openAIName string // OpenAI name, e.g. OpenAI name
param contentSafetyName string

// Role Definition IDs
var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesOpenAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'
var keyVaultAdministrator = '00482a5a-887f-4fb3-b363-3b7fe8e74483'

var congnitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Azure content safety
var readerRole = 'acdd72a7-3385-48ef-bd42-f606fba81ae7' // Azure content safety

// Maybe
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'

// AI Serivices add-ons
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var userAccessAdministratorRoleId = '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9'
var aiInferenceDeploymentOperatorRoleId = '3afb7f49-54cb-416e-8c09-6dc049efa503'

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

resource existingOpenAI 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: openAIName
}

resource existingContentSafety 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: contentSafetyName
}
// --------------- SP for Azure AI services -START ---------------- //

// Q: Is this needed? To have access from AIServices to OpenAIContributor? E.g. set permission on itself?

resource roleAssignmentCognitiveServicesOpenAIContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingOpenAI.id, cognitiveServicesOpenAIContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    description: '018'
  }
  scope: existingOpenAI
}

//Q end

//->  Content safety
resource contentSafetyReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingContentSafety.id, readerRole, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRole)
    description: '018'
  }
  scope: existingContentSafety
}

resource contentSafetyCongnitiveServicesUserRoleId 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingContentSafety.id, congnitiveServicesUserRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', congnitiveServicesUserRoleId)
    description: '018'
  }
  scope: existingContentSafety
}

// -> AI Search
resource roleAssignmentSearchIndexDataReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataReaderRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
    description: '010'
  }
  scope: existingAiSearch
}

resource roleAssignmentSearchIndexDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    description: '011'
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

// -> Storage START

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
  name: guid(existingStorageAccount.id, storageFileDataPrivilegedContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    description: '019b'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageFileDataPrivilegedContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    description: '019a'
  }
  scope: existingStorageAccount2
}

// -> Storage END

// -> PROJECT RG START
resource roleAssignmentAIInferenceDeploymentOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, aiInferenceDeploymentOperatorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiInferenceDeploymentOperatorRoleId)
    description: '015'
  }
  scope: resourceGroup()
}

resource roleAssignmentKeyVaultAdministrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, keyVaultAdministrator, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultAdministrator)
    description: '016'
  }
  scope:resourceGroup()
}

resource roleAssignmentUserAccessAdministrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, userAccessAdministratorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', userAccessAdministratorRoleId)
    description: '017'
  }
  scope: resourceGroup()
}

// -> PROJECT RG END

// --------------- AIServices MI END ---------------- //

// Outputs
output roleAssignmentSearchIndexDataReaderName string = roleAssignmentSearchIndexDataReader.name
output roleAssignmentSearchIndexDataContributorName string = roleAssignmentSearchIndexDataContributor.name
output roleAssignmentSearchServiceContributorName string = roleAssignmentSearchServiceContributor.name
output roleAssignmentStorageBlobDataContributorName string = roleAssignmentStorageBlobDataContributor.name


// Outputs for GUIDs with resource names
output roleAssignmentSearchIndexDataReaderGUID string = guid(existingAiSearch.id, searchIndexDataReaderRoleId, aiServicesPrincipalId)
output roleAssignmentSearchIndexDataContributorGUID string = guid(existingAiSearch.id, searchIndexDataContributorRoleId, aiServicesPrincipalId)
output roleAssignmentSearchServiceContributorGUID string = guid(existingAiSearch.id, searchServiceContributorRoleId, aiServicesPrincipalId)
output roleAssignmentStorageBlobDataContributorGUID string = guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiServicesPrincipalId)
