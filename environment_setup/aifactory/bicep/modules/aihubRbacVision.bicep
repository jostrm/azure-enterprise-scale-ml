param aiVisionMIObjectId string // Object ID of the Managed Identity for Azure AI Search
// Parameters for resource
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param visonServiceName string
param userObjectIds array // Specific user's object ID's for "User to Service Table"

// Role Definition IDs: Cognitive Services OpenAI Contributor
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var congnitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Azure content safety
var readerRole = 'acdd72a7-3385-48ef-bd42-f606fba81ae7' // Azure content safety
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName2
}
resource visionService 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: visonServiceName
}

// Search -> Storage-Blob
resource roleAssignmentStorageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiVisionMIObjectId)
  properties: {
    principalId: aiVisionMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    description: '013'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageBlobDataContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageBlobDataOwnerRoleId, aiVisionMIObjectId)
  properties: {
    principalId: aiVisionMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    description: '014'
  }
  scope: existingStorageAccount2
}

// Search -> Storage-File

resource roleAssignmentStorageFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageFileDataPrivilegedContributorRoleId, aiVisionMIObjectId)
  properties: {
    principalId: aiVisionMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    description: '019b'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageBlobDataOwnerRoleId, aiVisionMIObjectId)
  properties: {
    principalId: aiVisionMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    description: '019a'
  }
  scope: existingStorageAccount2
}

// USERS to Vision

resource visionServiceOpenAICotributorUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(visionService.id, congnitiveServicesUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', congnitiveServicesUserRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: CognitiveServicesUser to USER with OID  ${userObjectIds[i]} for : ${visionService.name} to call data on data plane'
  }
  scope:visionService
}]

resource visionServiceReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(visionService.id, readerRole, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRole)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: Reader to USER with OID  ${userObjectIds[i]} for : ${visionService.name} to call data on data plane'
  }
  scope:visionService
}]


// Outputs
output roleAssignmentStorageBlobDataContributorName string = roleAssignmentStorageBlobDataContributor.name
output roleAssignmentStorageBlobDataContributorName2 string = roleAssignmentStorageBlobDataContributor2.name

