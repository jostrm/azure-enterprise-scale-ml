param aiDocsIntelMIObjectId string // Object ID of the Managed Identity for Azure AI Search
// Parameters for resource
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param docsServiceName string
param userObjectIds array // Specific user's object ID's for "User to Service Table"
param useAdGroups bool = false // Use AD groups for role assignments
param servicePrincipleAndMIArray array // Service Principle Object ID, User created MAnaged Identity

// Role Definition IDs: Cognitive Services OpenAI Contributor
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
//var congnitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var cognitiveServicesContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442' 
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName2
}
resource docsService 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: docsServiceName
}

// Search -> Storage-Blob
resource roleAssignmentStorageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, aiDocsIntelMIObjectId)
  properties: {
    principalId: aiDocsIntelMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    description: '013'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageBlobDataContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageBlobDataOwnerRoleId, aiDocsIntelMIObjectId)
  properties: {
    principalId: aiDocsIntelMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    description: '014'
  }
  scope: existingStorageAccount2
}

// AI docs -> Storage-File

resource roleAssignmentStorageFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageFileDataPrivilegedContributorRoleId, aiDocsIntelMIObjectId)
  properties: {
    principalId: aiDocsIntelMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    description: '019b'
  }
  scope: existingStorageAccount
}
resource roleAssignmentStorageFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageFileDataPrivilegedContributorRoleId, aiDocsIntelMIObjectId)
  properties: {
    principalId: aiDocsIntelMIObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataPrivilegedContributorRoleId)
    description: '019a'
  }
  scope: existingStorageAccount2
}

// USERS to Docs

resource docsServiceOpenAICotributorUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(docsService.id, cognitiveServicesContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'023: cognitiveServicesContributor role to USER with OID  ${userObjectIds[i]} for : ${docsService.name} to call data on data plane'
  }
  scope:docsService
}]

// MI and SP to Speech

resource searchIndexDataContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(docsService.id, cognitiveServicesContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesContributorRoleId to project service principal OID: ${servicePrincipleAndMIArray[i]} to ${docsService.name}'
  }
  scope:docsService
}]


// Outputs
output roleAssignmentStorageBlobDataContributorName string = roleAssignmentStorageBlobDataContributor.name
output roleAssignmentStorageBlobDataContributorName2 string = roleAssignmentStorageBlobDataContributor2.name

