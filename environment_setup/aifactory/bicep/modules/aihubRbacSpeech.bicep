param aiSpeechMIObjectId string // Object ID of the Managed Identity
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param speechServiceName string
param userObjectIds array // Specific user's object ID's for "User to Service Table"

// Role Definition IDs: Cognitive Services OpenAI Contributor
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var congnitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' 
var readerRole = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2021-08-01' existing = {
  name: storageAccountName
}
resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2021-08-01' existing = {
  name: storageAccountName2
}
resource speechService 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: speechServiceName
}

//  -> Storage-Blob
resource roleAssignmentStorageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiSpeechMIObjectId)
  properties: {
    principalId: aiSpeechMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    description: '013'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageBlobDataContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageBlobDataOwnerRoleId, aiSpeechMIObjectId)
  properties: {
    principalId: aiSpeechMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    description: '014'
  }
  scope: existingStorageAccount2
}

//  -> Storage-File

resource roleAssignmentStorageFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageFileDataPrivilegedContributorRoleId, aiSpeechMIObjectId)
  properties: {
    principalId: aiSpeechMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    description: '019b'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageBlobDataOwnerRoleId, aiSpeechMIObjectId)
  properties: {
    principalId: aiSpeechMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    description: '019a'
  }
  scope: existingStorageAccount2
}

// USERS to Speech

resource speechServiceOpenAICotributorUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(speechService.id, congnitiveServicesUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', congnitiveServicesUserRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: CognitiveServicesUser to USER with OID  ${userObjectIds[i]} for : ${speechService.name} to call data on data plane'
  }
  scope:speechService
}]

resource speechServiceReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(speechService.id, readerRole, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRole)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: Reader to USER with OID  ${userObjectIds[i]} for : ${speechService.name} to call data on data plane'
  }
  scope:speechService
}]


// Outputs
output roleAssignmentStorageBlobDataContributorName string = roleAssignmentStorageBlobDataContributor.name
output roleAssignmentStorageBlobDataContributorName2 string = roleAssignmentStorageBlobDataContributor2.name

