// Docs: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/use-your-data-securely#create-shared-private-link

// Parameters for resource and principal IDs
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param aiSearchName string // Resource ID for Azure AI Search
param resourceGroupId string // Resource group ID where resources are located
param userObjectIds array // Specific user's object ID's
@secure()
param servicePrincipleObjectId string // Service Principle Object ID
param aiServicesName string // AIServices name, e.g. AIStudio name
param aiHubName string
param aiHubProjectName string

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
resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName2
}

resource existingAiSearch 'Microsoft.Search/searchServices@2021-04-01-preview' existing = {
  name: aiSearchName
}

resource existingAiServicesResource 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: aiServicesName
}
resource existingAIHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = {
  name: aiHubName
}
resource existingAIHubProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = {
  name: aiHubName
}


// --------------- SEARCH ---------------- //

@description('Role Assignment for Azure AI Search: SearchIndexDataContributor for users. 	Grants full access to Azure Cognitive Search index data')
resource searchIndexDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'020: SearchIndexUserDataContributor to USER with OID  ${userObjectIds[i]} for : ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]
resource searchIndexDataContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'searchIndexDataContributorRoleId to project service principal OID: ${servicePrincipleObjectId} to ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}

@description('Role Assignment for Azure AI Search: Search Service Contributor for users. Lets you manage Search services, but not access to them.')
resource searchServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'022: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]

resource searchServiceContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'searchServiceContributorRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}

// --------------- AI SERVICES  ---------------- //

/* 001
@description('Users to Azure AI Services: Cognitive Services Contributor for users. All, except: Access quota, Make inference API call with Microsoft Entra ID')
resource cognitiveServicesContributorRoleU 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: cognitiveServicesContributor role to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to call data on data plane'
  }
  scope:existingAiServicesResource
}]
resource cognitiveServicesContributorRoleSPS 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiServicesResource.id, cognitiveServicesContributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesContributor role to project service principal OID:${servicePrincipleObjectId} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}

*/

/*
@description('Users to Azure AI Services: Cognitive Services Usage Reader for users. Only Access quota (Minimal permission to view Cognitive Services usages)')
resource cognitiveServicesUsagesReaderU 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesUsagesReaderId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUsagesReaderId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: cognitiveServicesUsagesReaderId role to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to call data on data plane'
  }
  scope:existingAiServicesResource
}]
resource cognitiveServicesUsagesReaderSPU 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiServicesResource.id, cognitiveServicesUsagesReaderId, servicePrincipleObjecId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUsagesReaderId)
    principalId: servicePrincipleObjecId
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesUsagesReader role to project service principal OID:${servicePrincipleObjecId} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}
*/

@description('Users to Azure AI Services: Cognitive Services OpenAI Contributor for users. Full access including the ability to fine-tune, deploy and generate text')
resource cognitiveServicesOpenAIContributorUsersU 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'023: OpenAIContributorRole to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to call data on data plane'
  }
  scope:existingAiServicesResource
}]
resource cognitiveServicesOpenAIContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesOpenAIContributorRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}

/*
@description('Users to Azure AI Services: Cognitive Services OpenAI User:Read access to view files, models, deployments. The ability to create completion and embedding calls.')
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
resource roleAssignmentCognitiveServicesOpenAISP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIUserRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesOpenAIUserRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}
*/

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

@description('Role Assignment for Azure Storage 2: StorageBlobDataContributor for users. Grants read/write/delete permissions to Blob storage resources')
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
resource userStorageBlobDataContributorRole2SP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'storageBlobDataContributorRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}

@description('Azure Storage 2: FileDataPrivilegedContributor. Allows for read, write, delete, and modify ACLs on files/directories in Azure file shares by overriding existing ACLs/NTFS permissions. This role has no built-in equivalent on Windows file servers.')
resource roleAssignmentStorageUserFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount2.id, storageFileDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'028b: FileDataPrivilegedContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}]

resource roleAssignmentStorageUserFileDataPrivilegedContributor2SP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorageAccount2.id, storageFileDataContributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'storageFileDataContributorRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}

//  AI Hub & AI Project //
// --------------- AI Hub - specific ---------------- //
@description('')
resource azureAIDeveloperRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAIHub.id, azureAIDeveloperRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'043 AzureAIDeveloper role to USER with OID  ${userObjectIds[i]} for : ${existingAIHub.name}'
  }
  scope:existingAIHub
}]

resource azureAIDeveloperRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAIHub.id, azureAIDeveloperRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureAIDeveloperRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAIHub.name}'
  }
  scope:existingAIHub
}

// --------------- AI Project - specific ---------------- //

@description('AI Project: azureAIAdministrator:')
resource azureAIAdministratorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAIHubProject.id, azureAIAdministrator, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'044 azureAIAdministrator role to USER with OID  ${userObjectIds[i]} for : ${existingAIHub.name}'
  }
  scope:existingAIHubProject
}]
resource azureAIAdministratorAssignmentSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAIHubProject.id, azureAIAdministrator, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureAIAdministrator to project service principal OID:${servicePrincipleObjectId} to ${existingAIHub.name}'
  }
  scope:existingAIHubProject
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
    description:'044 AzureAIInferenceDeploymentOperator role to USER with OID  ${userObjectIds[i]} for ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}]

resource azureAIInferenceDeploymentOperatorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, azureAIInferenceDeploymentOperatorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureAIInferenceDeploymentOperatorRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}

// --------------- RG:AI Hub + Project --//
@description('RG:AI Hub, AI Project: Azure ML Data scientist: Can perform all actions within an AML workspace, except for creating or deleting compute resources and modifying the workspace itself.')
resource azureMLDataScientistRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAIHub.id, azureMLDataScientistRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'041 AzureMLDataScientist role to USER with OID  ${userObjectIds[i]} for : ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}]

resource azureMLDataScientistRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, azureMLDataScientistRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureMLDataScientistRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAIHub.name} on RG level'
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
    description:'042 AzureMachineLearningWorkspaceConnectionSecretsReader role to USER with OID  ${userObjectIds[i]} for : ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}]

resource amlWorkspaceConnectionSecretsReaderSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'azureMachineLearningWorkspaceConnectionSecretsReaderRoleId to project service principal OID:${servicePrincipleObjectId} to ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}

// --------------- RG:CONTRIBUTOR//
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

