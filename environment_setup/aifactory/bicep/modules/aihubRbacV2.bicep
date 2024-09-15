// Parameters for resource and principal IDs
param storageAccountName string // Resource ID for Azure Storage Account
param aiServicesPrincipalId string // Principal ID for Azure AI services/OpenAI
param aiSearchName string // Resource ID for Azure AI Search
param resourceGroupId string // Resource group ID where resources are located
param userObjectId string // Specific user's object ID for "User to Service Table"
param aiOpenAIChatName string // Azure OpenAI resource ID for chat model
param aiOpenAIEmbeddingName string // Azure OpenAI resource ID for embedding model

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

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2021-08-01' existing = {
  name: storageAccountName
}

resource existingAiSearch 'Microsoft.Search/searchServices@2021-04-01-preview' existing = {
  name: aiSearchName
}

resource existingAiOpenAIChat 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: aiOpenAIChatName
}

resource existingAiOpenAIEmbedding 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: aiOpenAIEmbeddingName
}

// Role Assignments for Azure AI services/OpenAI
resource roleAssignmentSearchIndexDataReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataReaderRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
  }
  scope: existingAiSearch
}

resource roleAssignmentSearchIndexDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
  }
  scope: existingAiSearch
}

resource roleAssignmentSearchIndexUserDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, userObjectId)
  properties: {
    principalId: userObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
  }
  scope: existingAiSearch
}

resource roleAssignmentSearchServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
  }
  scope: existingAiSearch
}

resource roleAssignmentStorageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
  }
  scope: existingStorageAccount
}

// Role Assignments for Azure OpenAI Resources
resource roleAssignmentCognitiveServicesOpenAIContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiOpenAIChat.id, cognitiveServicesOpenAIContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
  }
  scope: existingAiOpenAIChat
}

resource roleAssignmentCognitiveServicesOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiOpenAIEmbedding.id, cognitiveServicesOpenAIUserRoleId, userObjectId)
  properties: {
    principalId: userObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
  }
  scope: existingAiOpenAIEmbedding
}

// Specific user role assignments to Azure AI services/OpenAI
resource userRoleAssignmentCognitiveServicesOpenAIContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServicesPrincipalId, cognitiveServicesOpenAIContributorRoleId, userObjectId)
  properties: {
    principalId: userObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
  }
  scope: existingAiOpenAIChat // Example scope, adjust as needed
}

resource userRoleAssignmentCognitiveServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServicesPrincipalId, cognitiveServicesUserRoleID, userObjectId)
  properties: {
    principalId: userObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleID)
  }
  scope: existingAiOpenAIChat // Example scope, adjust as needed
}


resource userRoleAssignmentContributorAiServices 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServicesPrincipalId, contributorRoleId, userObjectId)
  properties: {
    principalId: userObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
  }
  scope: existingAiOpenAIChat // Example scope, adjust as needed
}

resource userRoleAssignmentContributorAiSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, userObjectId)
  properties: {
    principalId: userObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
  }
  scope: existingAiSearch
}

resource userRoleAssignmentContributorStorageAccount 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccountName, storageBlobDataContributorRoleId, userObjectId)
  properties: {
    principalId: userObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
  }
  scope: existingStorageAccount
}

resource userRoleAssignmentContributorResourceGroup 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, contributorRoleId, userObjectId)
  properties: {
    principalId: userObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
  }
  scope: resourceGroup()
}

//Extra roles to be verified and adjusted

var aiInferenceDeploymentOperatorRoleId = '3afb7f49-54cb-416e-8c09-6dc049efa503'

resource roleAssignmentAIInferenceDeploymentOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, aiInferenceDeploymentOperatorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiInferenceDeploymentOperatorRoleId)
  }
  scope: resourceGroup()
}

var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'

resource roleAssignmentStorageBlobDataOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, storageBlobDataOwnerRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
  }
  scope: existingStorageAccount
}

var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'

resource roleAssignmentStorageFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, storageFileDataPrivilegedContributorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
  }
  scope: existingStorageAccount
}

resource roleAssignmentStorageUserFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, storageFileDataPrivilegedContributorRoleId, userObjectId)
  properties: {
    principalId: userObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
  }
  scope: existingStorageAccount
}



resource roleAssignmentKeyVaultAdministrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, keyVaultAdministrator, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultAdministrator)
  }
  // Update the scope to the specific Key Vault resource if needed
  scope:  resourceGroup()
}

var userAccessAdministratorRoleId = '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9'

resource roleAssignmentUserAccessAdministrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, userAccessAdministratorRoleId, aiServicesPrincipalId)
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', userAccessAdministratorRoleId)
  }
  scope: resourceGroup()
}



// Outputs
output roleAssignmentSearchIndexDataReaderName string = roleAssignmentSearchIndexDataReader.name
output roleAssignmentSearchIndexDataContributorName string = roleAssignmentSearchIndexDataContributor.name
output roleAssignmentSearchServiceContributorName string = roleAssignmentSearchServiceContributor.name
output roleAssignmentStorageBlobDataContributorName string = roleAssignmentStorageBlobDataContributor.name
output roleAssignmentCognitiveServicesOpenAIContributorName string = roleAssignmentCognitiveServicesOpenAIContributor.name
output roleAssignmentCognitiveServicesOpenAIUserName string = roleAssignmentCognitiveServicesOpenAIUser.name


// Outputs for GUIDs with resource names
output roleAssignmentSearchIndexDataReaderGUID string = guid(existingAiSearch.id, searchIndexDataReaderRoleId, aiServicesPrincipalId)
output roleAssignmentSearchIndexDataContributorGUID string = guid(existingAiSearch.id, searchIndexDataContributorRoleId, aiServicesPrincipalId)
output roleAssignmentSearchServiceContributorGUID string = guid(existingAiSearch.id, searchServiceContributorRoleId, aiServicesPrincipalId)
output roleAssignmentStorageBlobDataContributorGUID string = guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiServicesPrincipalId)
output roleAssignmentCognitiveServicesOpenAIContributorGUID string = guid(existingAiOpenAIChat.id, cognitiveServicesOpenAIContributorRoleId, aiServicesPrincipalId)
output roleAssignmentCognitiveServicesOpenAIUserGUID string = guid(existingAiOpenAIEmbedding.id, cognitiveServicesOpenAIUserRoleId, userObjectId)
output userRoleAssignmentCognitiveServicesOpenAIContributorGUID string = guid(aiServicesPrincipalId, cognitiveServicesOpenAIContributorRoleId, userObjectId)
output userRoleAssignmentCognitiveServicesUserGUID string = guid(aiServicesPrincipalId, cognitiveServicesUserRoleID, userObjectId)
output userRoleAssignmentContributorAiServicesGUID string = guid(aiServicesPrincipalId, contributorRoleId, userObjectId)
output userRoleAssignmentContributorAiSearchGUID string = guid(existingAiSearch.id, contributorRoleId, userObjectId)
output userRoleAssignmentContributorStorageAccountGUID string = guid(storageAccountName, contributorRoleId, userObjectId)
output userRoleAssignmentContributorResourceGroupGUID string = guid(resourceGroupId, contributorRoleId, userObjectId)
