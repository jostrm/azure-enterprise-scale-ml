param aiSearchMIObjectId string // Object ID of the Managed Identity for Azure AI Search
// Parameters for resource
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param aiServicesName string // AIServices name, e.g. AIStudio name
param openAIName string // Azure OpenAI

// Role Definition IDs: Cognitive Services OpenAI Contributor
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesOpenAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // ID for the built-in Contributor role
var cognitiveServicesUserRoleID = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Placeholder ID for the Cognitive Services User role
var keyVaultAdministrator = '00482a5a-887f-4fb3-b363-3b7fe8e74483'

var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2021-08-01' existing = {
  name: storageAccountName
}
resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2021-08-01' existing = {
  name: storageAccountName2
}

resource existingAiServicesResource 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: aiServicesName
}

resource existingOpenAI 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: openAIName
}

// Search -> Storage
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

/*

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

// Search -> RG

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
*/

// Search -> AIServices
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

// Search -> OpenAI
resource openAIAssignmentCognitiveServicesOpenAIContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingOpenAI.id, cognitiveServicesOpenAIContributorRoleId, aiSearchMIObjectId)
  properties: {
    principalId: aiSearchMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    description: '018'
  }
  scope: existingOpenAI
}

// Search -> Storage

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


// Outputs
output roleAssignmentStorageBlobDataContributorName string = roleAssignmentStorageBlobDataContributor.name
output roleAssignmentCognitiveServicesOpenAIContributorName string = roleAssignmentCognitiveServicesOpenAIContributor.name


// Outputs for GUIDs with resource names
output roleAssignmentStorageBlobDataContributorGUID string = guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiSearchMIObjectId)
output roleAssignmentCognitiveServicesOpenAIContributorGUID string = guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, aiSearchMIObjectId)
