// Docs: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/use-your-data-securely#create-shared-private-link

// Parameters for resource and principal IDs
param storageAccountName string // Name of Azure Storage Account
param userObjectIds array // Specific user's object ID's
param servicePrincipleAndMIArray array // Service Principle Object ID, User created MAnaged Identity
param azureMLworkspaceName string
param useAdGroups bool = false
param user2Storage bool = true

// Azure ML (AI Hub, AIProject)
var azureMLDataScientistRoleId = 'f6c7c914-8db3-469d-8ca1-694a8f32e121' // SP, user -> AI Hub, AI Project (RG)
var azureAIDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee'  // SP, user -> AI Hub
var azureAIInferenceDeploymentOperatorRoleId = '3afb7f49-54cb-416e-8c09-6dc049efa503'  // User -> AI project
var azureAIAdministrator = 'b78c5d69-af96-48a3-bf8d-a8b4d589de94' // AI Project (to all underlying resources)

// AzureML: Managed Online Endpoints & User & SP
var azureMachineLearningWorkspaceConnectionSecretsReaderRoleId = 'ea01e6af-a1c1-4350-9563-ad00f8c72ec5'  // SP, user, EP -> AI Hub, AI Project (RG)
var azureMLMetricsWriter ='635dd51f-9968-44d3-b7fb-6d9a6bd613ae' // EP -> AI project

// Storage
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource existingAmlWorkspace 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = {
  name: azureMLworkspaceName
}
// --------------- STORAGE ---------------- //
@description('Role Assignment for Azure Storage 1: StorageBlobDataContributor for users. Grants read/write/delete permissions to Blob storage resources')
resource userStorageBlobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if (user2Storage){
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'027a: StorageBlobDataContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]

resource userStorageBlobDataContributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if (user2Storage){
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'storageBlobDataContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]

@description('Azure Storage 1: FileDataPrivilegedContributor. Allows for read, write, delete, and modify ACLs on files/directories in Azure file shares by overriding existing ACLs/NTFS permissions. This role has no built-in equivalent on Windows file servers.')
resource roleAssignmentStorageUserFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if (user2Storage){
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'028a: FileDataPrivilegedContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]

resource roleAssignmentStorageUserFileDataPrivilegedContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if (user2Storage){
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'storageFileDataContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]

//  Azure ML -> AI Hub & AI Project //
// --------------- AI Hub - specific ---------------- //
@description('')
resource azureAIDeveloperRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAmlWorkspace.id, azureAIDeveloperRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'043 AzureAIDeveloper role to USER with OID  ${userObjectIds[i]} for : ${existingAmlWorkspace.name}'
  }
  scope:existingAmlWorkspace
}]

resource azureAIDeveloperRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAmlWorkspace.id, azureAIDeveloperRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureAIDeveloperRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAmlWorkspace.name}'
  }
  scope:existingAmlWorkspace
}]

// --------------- Azure ML specific ---------------- //

@description('AI Project: azureAIAdministrator:')
resource azureAIAdministratorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAmlWorkspace.id, azureAIAdministrator, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'044 azureAIAdministrator role to USER with OID  ${userObjectIds[i]} for : ${existingAmlWorkspace.name}'
  }
  scope:existingAmlWorkspace
}]
resource azureAIAdministratorAssignmentSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAmlWorkspace.id, azureAIAdministrator, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureAIAdministrator to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAmlWorkspace.name}'
  }
  scope:existingAmlWorkspace
}]

// ----------------RG LEVEL---------------------//

// --------------- RG: AI Project//
@description('RG:AI Project: AzureAIInferenceDeploymentOperator:Can perform all actions required to create a resource deployment within a resource group. ')
resource azureAIInferenceDeploymentOperatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAmlWorkspace.id, azureAIInferenceDeploymentOperatorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'044 AzureAIInferenceDeploymentOperator role to USER with OID  ${userObjectIds[i]} for ${existingAmlWorkspace.name} on RG level'
  }
  scope:existingAmlWorkspace
}]

resource azureAIInferenceDeploymentOperatorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAmlWorkspace.id, azureAIInferenceDeploymentOperatorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureAIInferenceDeploymentOperatorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAmlWorkspace.name} on RG level'
  }
  scope:existingAmlWorkspace
}]

// --------------- RG:AI Hub + Project --//

@description('RG:AI Hub, AI Project: Azure ML Data scientist: Can perform all actions within an AML workspace, except for creating or deleting compute resources and modifying the workspace itself.')
resource azureMLDataScientistRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAmlWorkspace.id, azureMLDataScientistRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'041 AzureMLDataScientist role to USER with OID  ${userObjectIds[i]} for : ${existingAmlWorkspace.name} on RG level'
  }
  scope:existingAmlWorkspace
}]


/*  Tenant ID, application ID, principal ID, and scope are not allowed to be updated
resource azureMLDataScientistRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, azureMLDataScientistRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureMLDataScientistRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAmlWorkspace.name} on RG level'
  }
  scope:resourceGroup()
} */

@description('RG:AI Hub, AI Project: AzureMachineLearningWorkspaceConnectionSecretsReader: Can perform all actions within an AML workspace, except for creating or deleting compute resources and modifying the workspace itself.')
resource amlWorkspaceConnectionSecretsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAmlWorkspace.id, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'042 AzureMachineLearningWorkspaceConnectionSecretsReader role to USER with OID  ${userObjectIds[i]} for : ${existingAmlWorkspace.name} on RG level'
  }
  scope:existingAmlWorkspace
}]

resource amlWorkspaceConnectionSecretsReaderSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAmlWorkspace.id, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureMachineLearningWorkspaceConnectionSecretsReaderRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAmlWorkspace.name} on RG level'
  }
  scope:existingAmlWorkspace
}]
