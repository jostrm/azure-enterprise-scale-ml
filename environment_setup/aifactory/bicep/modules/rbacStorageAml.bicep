// Docs: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/use-your-data-securely#create-shared-private-link

// Parameters for resource and principal IDs
param storageAccountName string // Name of Azure Storage Account
param resourceGroupId string // Resource group ID where resources are located
param userObjectIds array // Specific user's object ID's
@secure()
param servicePrincipleObjectId string // Service Principle Object ID
param azureMLworkspaceName string

// ############## RG level ##############

// Container Registry (EP, WebApp, Azure Function)
var acrPushRoleId = '8311e382-0749-4cb8-b61a-304f252e45ec' // SP, user -> RG
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // EP, App service or Function app -> RG

var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // User -> RG
var roleBasedAccessControlAdministratorRG = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'

// ############## RG LEVEL END

// Search
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // User, SP, AI Services, etc -> AI Search
//Lets you manage Search services, but not access to them.
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // SP, User, Search, AIHub, AIProject, App Service/FunctionApp -> AI Search

// Azure ML (AI Hub, AIProject)
var azureMLDataScientistRoleId = 'f6c7c914-8db3-469d-8ca1-694a8f32e121' // SP, user -> AI Hub, AI Project (RG)
var azureAIDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee'  // SP, user -> AI Hub
var azureAIInferenceDeploymentOperatorRoleId = '3afb7f49-54cb-416e-8c09-6dc049efa503'  // User -> AI project
var azureAIAdministrator = 'b78c5d69-af96-48a3-bf8d-a8b4d589de94' // AI Project (to all underlying resources)

// AzureML: Managed Online Endpoints & User & SP
var azureMachineLearningWorkspaceConnectionSecretsReaderRoleId = 'ea01e6af-a1c1-4350-9563-ad00f8c72ec5'  // SP, user, EP -> AI Hub, AI Project (RG)
var azureMLMetricsWriter ='635dd51f-9968-44d3-b7fb-6d9a6bd613ae' // EP -> AI project

// Custom Vision
var cognitiveServicesCustomVisionContributorRoleId = 'c1ff6cc2-c111-46fe-8896-e0ef812ad9f3' // User, AI hub, AI project -> Custom Visiom

// Storage
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'

// Cognitive Services: OpenAI, AI services
// See table: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/role-based-access-control
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // SP, User, Search, AIHub, AIProject -> AI services, OpenAI
var cognitiveServicesOpenAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442' // All.  except: Access quota, create new Azure OpenAI, regenerate key under EP, content filter, add data source "on your data"

var cognitiveServicesContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442' // All, except: Access quota | Make inference API call with Microsoft Entra ID
var cognitiveServicesUsagesReaderId = 'bba48692-92b0-4667-a9ad-c31c7b334ac2' // Only Access quota (Minimal permission to view Cognitive Services usages)

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource existingAmlWorkspace 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = {
  name: azureMLworkspaceName
}
// --------------- STORAGE ---------------- //
@description('Role Assignment for Azure Storage 1: StorageBlobDataContributor for users. Grants read/write/delete permissions to Blob storage resources')
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

resource userStorageBlobDataContributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'storageBlobDataContributorRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}

@description('Azure Storage 1: FileDataPrivilegedContributor. Allows for read, write, delete, and modify ACLs on files/directories in Azure file shares by overriding existing ACLs/NTFS permissions. This role has no built-in equivalent on Windows file servers.')
resource roleAssignmentStorageUserFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'028a: FileDataPrivilegedContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]

resource roleAssignmentStorageUserFileDataPrivilegedContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'storageFileDataContributorRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}

//  Azure ML -> AI Hub & AI Project //
// --------------- AI Hub - specific ---------------- //
@description('')
resource azureAIDeveloperRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAmlWorkspace.id, azureAIDeveloperRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'043 AzureAIDeveloper role to USER with OID  ${userObjectIds[i]} for : ${existingAmlWorkspace.name}'
  }
  scope:existingAmlWorkspace
}]

resource azureAIDeveloperRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAmlWorkspace.id, azureAIDeveloperRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureAIDeveloperRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAmlWorkspace.name}'
  }
  scope:existingAmlWorkspace
}

// --------------- Azure ML specific ---------------- //

@description('AI Project: azureAIAdministrator:')
resource azureAIAdministratorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAmlWorkspace.id, azureAIAdministrator, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'044 azureAIAdministrator role to USER with OID  ${userObjectIds[i]} for : ${existingAmlWorkspace.name}'
  }
  scope:existingAmlWorkspace
}]
resource azureAIAdministratorAssignmentSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAmlWorkspace.id, azureAIAdministrator, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureAIAdministrator to project service principal OID:${servicePrincipleObjectId} to ${existingAmlWorkspace.name}'
  }
  scope:existingAmlWorkspace
}

// ----------------RG LEVEL---------------------//

// --------------- RG: AI Project//
@description('RG:AI Project: AzureAIInferenceDeploymentOperator:Can perform all actions required to create a resource deployment within a resource group. ')
resource azureAIInferenceDeploymentOperatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureAIInferenceDeploymentOperatorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'044 AzureAIInferenceDeploymentOperator role to USER with OID  ${userObjectIds[i]} for ${existingAmlWorkspace.name} on RG level'
  }
  scope:resourceGroup()
}]

resource azureAIInferenceDeploymentOperatorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, azureAIInferenceDeploymentOperatorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureAIInferenceDeploymentOperatorRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAmlWorkspace.name} on RG level'
  }
  scope:resourceGroup()
}

// --------------- RG:AI Hub + Project --//
@description('RG:AI Hub, AI Project: Azure ML Data scientist: Can perform all actions within an AML workspace, except for creating or deleting compute resources and modifying the workspace itself.')
resource azureMLDataScientistRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAmlWorkspace.id, azureMLDataScientistRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'041 AzureMLDataScientist role to USER with OID  ${userObjectIds[i]} for : ${existingAmlWorkspace.name} on RG level'
  }
  scope:resourceGroup()
}]

resource azureMLDataScientistRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, azureMLDataScientistRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureMLDataScientistRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAmlWorkspace.name} on RG level'
  }
  scope:resourceGroup()
}

@description('RG:AI Hub, AI Project: AzureMachineLearningWorkspaceConnectionSecretsReader: Can perform all actions within an AML workspace, except for creating or deleting compute resources and modifying the workspace itself.')
resource amlWorkspaceConnectionSecretsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'042 AzureMachineLearningWorkspaceConnectionSecretsReader role to USER with OID  ${userObjectIds[i]} for : ${existingAmlWorkspace.name} on RG level'
  }
  scope:resourceGroup()
}]

resource amlWorkspaceConnectionSecretsReaderSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureMachineLearningWorkspaceConnectionSecretsReaderRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAmlWorkspace.name} on RG level'
  }
  scope:resourceGroup()
}

// --------------- RG:CONTRIBUTOR//
/*
@description('Role Assignment for ResoureGroup: CONTRIBUTOR for users.')
resource contributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'029: CONTRIBUTOR on RG to USER with OID  ${userObjectIds[i]} for ${resourceGroupId}'
  }
  scope:resourceGroup()
}]

resource contributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, contributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'contributorRoleId to project service principal OID:${servicePrincipleObjectId} for ${resourceGroupId}'
  }
  scope:resourceGroup()
}
*/

// --------------- RG:User Access Admin//
@description('Role Assignment for ResoureGroup: RoleBasedAccessControlAdministrator for users.')
resource roleBasedAccessControlAdminRGRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'030: RoleBasedAccessControlAdministrator on RG to USER with OID  ${userObjectIds[i]} for : ${resourceGroupId}'
  }
  scope:resourceGroup()
}]
resource roleBasedAccessControlAdminRGRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'roleBasedAccessControlAdministrator to project service principal OID:${servicePrincipleObjectId} for RG: ${resourceGroupId}'
  }
  scope:resourceGroup()
}

// --------------- RG: Container Registry, PULL //
@description('Role Assignment for ResoureGroup: acrPushRoleId for users.')
resource acrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, acrPushRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'030: acrPush role on RG to USER with OID  ${userObjectIds[i]} for RG: ${resourceGroupId}'
  }
  scope:resourceGroup()
}]

resource acrPushSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, acrPushRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'acrPush role to project service principal OID:${servicePrincipleObjectId} for RG: ${resourceGroupId}'
  }
  scope:resourceGroup()
}
// --------------- USERS END ---------------- //
