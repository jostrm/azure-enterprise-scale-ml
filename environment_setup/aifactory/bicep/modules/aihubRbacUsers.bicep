// Docs: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/use-your-data-securely#create-shared-private-link

// Parameters for resource and principal IDs
param storageAccountName string // Name of Azure Storage Account
param storageAccountName2 string // Name of Azure Storage Account
param resourceGroupId string // Resource group ID where resources are located
param userObjectIds array // Specific user's object ID's
param aiServicesName string // AIServices name, e.g. AIStudio name
param aiHubName string
param aiHubProjectName string
param useAdGroups bool = false // Use AD groups for role assignments
param servicePrincipleAndMIArray array // Service Principle Object ID, User created MAnaged Identity
param disableContributorAccessForUsers bool = false // Disable contributor access for users

param idempotency string = utcNow() // '' // Idempotency variable to ensure unique role assignment names

// ############## RG level ##############

// Container Registry (EP, WebApp, Azure Function)
var acrPushRoleId = '8311e382-0749-4cb8-b61a-304f252e45ec' // SP, user -> RG
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // EP, App service or Function app -> RG

var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // User -> RG
var roleBasedAccessControlAdministratorRG = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'

var aiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d' // User to RG level, to all underlying resources (aiservices, AIF_v2_agents)
// ############## RG LEVEL END

// Azure ML (AI Hub, AIProject)
var azureMLDataScientistRoleId = 'f6c7c914-8db3-469d-8ca1-694a8f32e121' // SP, user -> AI Hub, AI Project (RG)
var azureAIDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee'  // SP, user -> AI Hub, AI Project -> AIServices
var azureAIInferenceDeploymentOperatorRoleId = '3afb7f49-54cb-416e-8c09-6dc049efa503'  // User -> AI project
var azureAIAdministrator = 'b78c5d69-af96-48a3-bf8d-a8b4d589de94' // Users -> AI Project (to all underlying resources)

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

var cognitiveServicesContributorRoleId = '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68' // All, except: Access quota | Make inference API call with Microsoft Entra ID
var cognitiveServicesUsagesReaderId = 'bba48692-92b0-4667-a9ad-c31c7b334ac2' // Only Access quota (Minimal permission to view Cognitive Services usages)

// SDK API auth
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' // User, SP to AI services/OpenAI or on RG

// Existing resources for scoping role assignments
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName2
}

resource existingAiServicesResource 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: aiServicesName
}
resource existingAIHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = {
  name: aiHubName
}
resource existingAIHubProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = {
  name: aiHubProjectName
}

// Needed for Agents in AI Hub's AIproject
resource aiDeveloperOnAIServicesFromAIProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiServicesResource.id, azureAIDeveloperRoleId, existingAIHubProject.id)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: existingAIHubProject.identity.principalId
    principalType: 'ServicePrincipal'
    description:'Azure AI Developer On AIServices From AIProject MI OID of: ${existingAIHubProject.name} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}
// Needed for Agents in AI Hub project, END

// 002
@description('Users to Azure AI Services: Cognitive Services Usage Reader for users. Only Access quota (Minimal permission to view Cognitive Services usages)')
resource cognitiveServicesUsagesReaderU 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesUsagesReaderId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUsagesReaderId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'023: cognitiveServicesUsagesReaderId role to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to call data on data plane'
  }
  scope:existingAiServicesResource
}]
resource cognitiveServicesUsagesReaderSPU 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesUsagesReaderId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUsagesReaderId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesUsagesReader role to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]
// 002

@description('Users to Azure AI Services: Cognitive Services OpenAI Contributor for users. Full access including the ability to fine-tune, deploy and generate text')
resource cognitiveServicesOpenAIContributorUsersU 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'023: OpenAIContributorRole to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to call data on data plane'
  }
  scope:existingAiServicesResource
}]
resource cognitiveServicesOpenAIContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesOpenAIContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]

@description('Users to Azure AI Services: Cognitive Services OpenAI User:Read access to view files, models, deployments. The ability to create completion and embedding calls.')
resource roleAssignmentCognitiveServicesOpenAIUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'024: OpenAICognitiveServicesUSer to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to list API keys'
  }
  scope:existingAiServicesResource
}]
resource roleAssignmentCognitiveServicesOpenAISP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIUserRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesOpenAIUserRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]

// --------------- STORAGE ---------------- //
@description('Role Assignment for Azure Storage 1: StorageBlobDataContributor for users. Grants read/write/delete permissions to Blob storage resources')
resource userStorageBlobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount.id, storageBlobDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'027a: StorageBlobDataContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]

resource userStorageBlobDataContributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
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
resource roleAssignmentStorageUserFileDataPrivilegedContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'028a: FileDataPrivilegedContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]

resource roleAssignmentStorageUserFileDataPrivilegedContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01'= [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingStorageAccount.id, storageFileDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'storageFileDataContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount.name}'
  }
  scope:existingStorageAccount
}]

@description('Role Assignment for Azure Storage 2: StorageBlobDataContributor for users. Grants read/write/delete permissions to Blob storage resources')
resource userStorageBlobDataContributorRole2 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'027b: StorageBlobDataContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}]
resource userStorageBlobDataContributorRole2SP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingStorageAccount2.id, storageBlobDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'storageBlobDataContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}]

@description('Azure Storage 2: FileDataPrivilegedContributor. Allows for read, write, delete, and modify ACLs on files/directories in Azure file shares by overriding existing ACLs/NTFS permissions. This role has no built-in equivalent on Windows file servers.')
resource roleAssignmentStorageUserFileDataPrivilegedContributor2 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingStorageAccount2.id, storageFileDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'028b: FileDataPrivilegedContributor to USER with OID  ${userObjectIds[i]} for : ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}]

resource roleAssignmentStorageUserFileDataPrivilegedContributor2SP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingStorageAccount2.id, storageFileDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageFileDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'storageFileDataContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingStorageAccount2.name}'
  }
  scope:existingStorageAccount2
}]

//  AI Hub & AI Project //
// --------------- AI Hub - specific ---------------- //
@description('')
resource azureAIDeveloperRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAIHub.id, azureAIDeveloperRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'043 AzureAIDeveloper role to USER with OID  ${userObjectIds[i]} for : ${existingAIHub.name}'
  }
  scope:existingAIHub
}]

resource azureAIDeveloperRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01'  = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAIHub.id, azureAIDeveloperRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureAIDeveloperRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAIHub.name}'
  }
  scope:existingAIHub
}]

// --------------- AI Project - specific ---------------- //

@description('AI Project: azureAIAdministrator:')
resource azureAIAdministratorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAIHubProject.id, azureAIAdministrator, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'044 azureAIAdministrator role to USER with OID  ${userObjectIds[i]} for : ${existingAIHubProject.name}'
  }
  scope:existingAIHubProject
}]
resource azureAIAdministratorAssignmentSP 'Microsoft.Authorization/roleAssignments@2022-04-01'= [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAIHubProject.id, azureAIAdministrator, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureAIAdministrator to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAIHubProject.name}'
  }
  scope:existingAIHubProject
}]

// Azure AI Developer
@description('AI Project: Azure AI Developer:')
resource aiDevOnAIProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAIHubProject.id, azureAIDeveloperRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'azureAIDeveloperRoleId role to USER with OID  ${userObjectIds[i]} for : ${existingAIHubProject.name}'
  }
  scope:existingAIHubProject
}]
resource aiDevOnAIProjectSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAIHubProject.id, azureAIDeveloperRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureAIDeveloperRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAIHubProject.name}'
  }
  scope:existingAIHubProject
}]

// 2025-05-25 - cognitiveServicesContributorRoleId on AI FOUNDRY_v2 (AI Services)

@description('AI Services: Azure Cognitive services contributor')
resource cogServiceContribOnAIProjectUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'cognitiveServicesContributorRoleId role to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]
@description('AI Services: Azure Cognitive services contributor')
resource cogServiceContribOnAIProjectSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(existingAiServicesResource.id, cognitiveServicesContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]

// end

// ----------------RG LEVEL---------------------//

// 2025-03-25 - Azure AI User
@description('RG:AI Project: AzureAIInferenceDeploymentOperator:Can perform all actions required to create a resource deployment within a resource group. ')
resource aiUserUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, aiUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiUserRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Azure AI User role to USER with OID  ${userObjectIds[i]} for RG level'
  }
  scope:resourceGroup()
}]

resource aiUserSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, aiUserRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiUserRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'Azure AI User to project service principal OID:${servicePrincipleAndMIArray[i]} to RG level'
  }
  scope:resourceGroup()
}]

// 2024-> 
@description('RG:AI Project: AzureAIInferenceDeploymentOperator:Can perform all actions required to create a resource deployment within a resource group. ')
resource cogServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, cognitiveServicesUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'044 cognitiveServicesUserRoleId role to USER with OID  ${userObjectIds[i]} for RG level'
  }
  scope:resourceGroup()
}]

resource cogServicesUserSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, cognitiveServicesUserRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'cognitiveServicesUserRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to RG level'
  }
  scope:resourceGroup()
}]


// --------------- RG: AI Project//
@description('RG:AI Project: AzureAIInferenceDeploymentOperator:Can perform all actions required to create a resource deployment within a resource group. ')
resource azureAIInferenceDeploymentOperatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureAIInferenceDeploymentOperatorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'044 AzureAIInferenceDeploymentOperator role to USER with OID  ${userObjectIds[i]} for ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}]

resource azureAIInferenceDeploymentOperatorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, azureAIInferenceDeploymentOperatorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureAIInferenceDeploymentOperatorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}]

// --------------- RG:AI Hub + Project --//

// NB! Worked before - even if name: guid(existingAIHub.id, azureMLDataScientistRoleId, userObjectIds[i]) but it was or scope: resourceGroup()
@description('RG:AI Hub, AI Project: Azure ML Data scientist: Can perform all actions within an AML workspace, except for creating or deleting compute resources and modifying the workspace itself.')
resource azureMLDataScientistRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureMLDataScientistRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'041 AzureMLDataScientist role to USER with OID  ${userObjectIds[i]} for : ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}]

resource azureMLDataScientistRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, azureMLDataScientistRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureMLDataScientistRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}]

@description('RG:AI Hub, AI Project: AzureMachineLearningWorkspaceConnectionSecretsReader: Can perform all actions within an AML workspace, except for creating or deleting compute resources and modifying the workspace itself.')
resource amlWorkspaceConnectionSecretsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'042 AzureMachineLearningWorkspaceConnectionSecretsReader role to USER with OID  ${userObjectIds[i]} for : ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}]

resource amlWorkspaceConnectionSecretsReaderSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'azureMachineLearningWorkspaceConnectionSecretsReaderRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAIHub.name} on RG level'
  }
  scope:resourceGroup()
}]

// --------------- RG:CONTRIBUTOR//
@description('Role Assignment for ResoureGroup: CONTRIBUTOR for users.')
resource contributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!disableContributorAccessForUsers){
  name: guid(resourceGroupId, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'029: CONTRIBUTOR on RG to USER with OID  ${userObjectIds[i]} for ${resourceGroupId}'
  }
  scope:resourceGroup()
}]

resource contributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, contributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'contributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} for ${resourceGroupId}'
  }
  scope:resourceGroup()
}]

// --------------- RG:User Access Admin//
@description('Role Assignment for ResoureGroup: RoleBasedAccessControlAdministrator for users.')
resource roleBasedAccessControlAdminRGRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'030: RoleBasedAccessControlAdministrator on RG to USER with OID  ${userObjectIds[i]} for : ${resourceGroupId}'
  }
  scope:resourceGroup()
}]
resource roleBasedAccessControlAdminRGRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01'= [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'roleBasedAccessControlAdministrator to project service principal OID:${servicePrincipleAndMIArray[i]} for RG: ${resourceGroupId}'
  }
  scope:resourceGroup()
}]

// --------------- RG: Container Registry, PULL //
@description('Role Assignment for ResoureGroup: acrPushRoleId for users.')
resource acrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, acrPushRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'030: acrPush role on RG to USER with OID  ${userObjectIds[i]} for RG: ${resourceGroupId}'
  }
  scope:resourceGroup()
}]

resource acrPushSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, acrPushRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'acrPush role to project service principal OID:${servicePrincipleAndMIArray[i]} for RG: ${resourceGroupId}'
  }
  scope:resourceGroup()
}]
// --------------- USERS END ---------------- //

