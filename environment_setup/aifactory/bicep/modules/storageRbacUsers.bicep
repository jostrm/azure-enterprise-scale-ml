// Storage RBAC assignments for users and service principals
// Extracted from aihubRbacUsers.bicep to keep storage roles isolated

param storageAccountName string
param storageAccountName2 string = ''
param userObjectIds array
param servicePrincipleAndMIArray array
param useAdGroups bool = false

var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2023-05-01' existing = if(!empty(storageAccountName2)) {
  name: storageAccountName2
}

// Storage 1 - Blob
@description('Role Assignment for Azure Storage 1: StorageBlobDataContributor for users. Grants read/write/delete permissions to Blob storage resources')
resource userStorageBlobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '008 - StorageBlobDataContributor to USER with OID ${userObjectIds[i]} for ${existingStorageAccount.name}'
  }
  scope: existingStorageAccount
}]

resource userStorageBlobDataContributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '009 - storageBlobDataContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount.name}'
  }
  scope: existingStorageAccount
}]

// Storage 1 - File
@description('Azure Storage 1: FileDataPrivilegedContributor. Allows for read, write, delete, and modify ACLs on files/directories in Azure file shares.')
resource roleAssignmentStorageUserFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '010 - FileDataPrivilegedContributor to USER with OID ${userObjectIds[i]} for ${existingStorageAccount.name}'
  }
  scope: existingStorageAccount
}]

resource roleAssignmentStorageUserFileDataPrivilegedContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '011 - storageFileDataContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount.name}'
  }
  scope: existingStorageAccount
}]

// Storage 2 - Blob
@description('Role Assignment for Azure Storage 2: StorageBlobDataContributor for users. Grants read/write/delete permissions to Blob storage resources')
resource userStorageBlobDataContributorRole2 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(storageAccountName2)) {
  name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '012 - StorageBlobDataContributor to USER with OID ${userObjectIds[i]} for ${existingStorageAccount2.name}'
  }
  scope: existingStorageAccount2
}]

resource userStorageBlobDataContributorRole2SP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(storageAccountName2)) {
  name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '013 - storageBlobDataContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount2.name}'
  }
  scope: existingStorageAccount2
}]

// Storage 2 - File
@description('Azure Storage 2: FileDataPrivilegedContributor. Allows for read, write, delete, and modify ACLs on files/directories in Azure file shares.')
resource roleAssignmentStorageUserFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(storageAccountName2)) {
  name: guid(existingStorageAccount2.id, storageFileDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '014 - FileDataPrivilegedContributor to USER with OID ${userObjectIds[i]} for ${existingStorageAccount2.name}'
  }
  scope: existingStorageAccount2
}]

resource roleAssignmentStorageUserFileDataPrivilegedContributor2SP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(storageAccountName2)) {
  name: guid(existingStorageAccount2.id, storageFileDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '015 - storageFileDataContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount2.name}'
  }
  scope: existingStorageAccount2
}]

// Storage 1 - Queue
@description('Role Assignment for Azure Storage: StorageQueueDataContributor for users. Grants read/write/delete permissions to Queue storage resources for Azure Functions')
resource userStorageQueueDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount.id, storageQueueDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '016 - Storage Queue Data Contributor to USER with OID ${userObjectIds[i]} for ${existingStorageAccount.name}'
  }
  scope: existingStorageAccount
}]

resource userStorageQueueDataContributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingStorageAccount.id, storageQueueDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '017 - Storage Queue Data Contributor to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount.name}'
  }
  scope: existingStorageAccount
}]

// Storage 2 - Queue
@description('Role Assignment for Azure Storage 2: StorageQueueDataContributor for users. Grants read/write/delete permissions to Queue storage resources for Azure Functions')
resource userStorageQueueDataContributorRole2 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(storageAccountName2)) {
  name: guid(existingStorageAccount2.id, storageQueueDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '018 - Storage Queue Data Contributor to USER with OID ${userObjectIds[i]} for ${existingStorageAccount2.name}'
  }
  scope: existingStorageAccount2
}]

resource userStorageQueueDataContributorRole2SP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(storageAccountName2)) {
  name: guid(existingStorageAccount2.id, storageQueueDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '019 - Storage Queue Data Contributor to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount2.name}'
  }
  scope: existingStorageAccount2
}]
