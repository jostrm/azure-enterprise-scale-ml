// ============== TROUBLE SHOOT (RoleAssignmentExists) ==============
// Q: Where to get Guids -> Azure Devops/Github error message. 
// Q: Where to get input variable values -> Azure portal, deployment tab, and INPUT
/* Remove manually all assignements on scopes, rerun.

existingAiServicesResource, existingAiHubResource, existingAiHubProjectResource,existingStorageAccount,existingStorageAccount2,resourceGroup

*/

// ============== RBAC CONDITIONS ==============
// This template implements conditional role assignments that prevent users from assigning
// privileged administrator roles (Owner, User Access Administrator, RBAC Administrator).
// This follows the "Allow user to assign all roles except privileged administrator roles" pattern.
// The condition uses Azure ABAC (Attribute-Based Access Control) to restrict role assignments.
// ============================================

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
param disableContributorAccessForUsers bool = false // Disable Contributor access for users
param disableRBACAdminOnRGForUsers bool = false // Disable Role Based Access Control Administrator for users on resource group
@description('Contributor role ID for RBAC assignments. Default is the built-in Contributor role.')
param contributorRoleId string = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

// ############## RG level ##############

// Container Registry (EP, WebApp, Azure Function)
var acrPushRoleId = '8311e382-0749-4cb8-b61a-304f252e45ec' // SP, user -> RG
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // EP, App service or Function app -> RG

// contributorRoleId is now a parameter
var roleBasedAccessControlAdministratorRG = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'

// Privileged administrator roles that should be excluded from RBAC assignments
var ownerRoleId = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635' // Owner
var userAccessAdministratorRoleId = '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9' // User Access Administrator  
var rbacAdministratorRoleId = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168' // Role Based Access Control Administrator

// Condition to prevent assignment of privileged administrator roles (Owner, UAA, RBAC)
var excludePrivilegedRolesCondition = '((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/write\'} AND @Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${ownerRoleId}, ${userAccessAdministratorRoleId}, ${rbacAdministratorRoleId}})))'

var aiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d' // User to RG level, to all underlying resources (aiservices, AIF_v2_agents)
var aiProjectManagerRoleId = 'eadc314b-1a2d-4efa-be10-5d325db5065e' // Azure AI Project Manager - manage AI projects and resources
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
// Storage role IDs moved to storageRbacUsers.bicep
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // For Azure Functions and queue processing

// Cognitive Services: OpenAI, AI services
// See table: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/role-based-access-control
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // SP, User, Search, AIHub, AIProject -> AI services, OpenAI
var cognitiveServicesOpenAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442' // All.  except: Access quota, create new Azure OpenAI, regenerate key under EP, content filter, add data source "on your data"

var cognitiveServicesContributorRoleId = '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68' // All, except: Access quota | Make inference API call with Microsoft Entra ID
var cognitiveServicesUsagesReaderId = 'bba48692-92b0-4667-a9ad-c31c7b334ac2' // Only Access quota (Minimal permission to view Cognitive Services usages)

// SDK API auth
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' // User, SP to AI services/OpenAI or on RG

// Existing resources for scoping role assignments
resource existingAiServicesResource 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = if(!empty(aiServicesName)) {
  name: aiServicesName
}
resource existingAIHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if(!empty(aiHubName)) {
  name: aiHubName
}
resource existingAIHubProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if(!empty(aiHubProjectName)) {
  name: aiHubProjectName
}

// Culprit.
// Needed for Agents in AI Hub's AIproject
resource aiDeveloperOnAIServicesFromAIProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(!empty(aiHubProjectName) && !empty(aiServicesName)) {
  name: guid(existingAiServicesResource.id, azureAIDeveloperRoleId, existingAIHubProject.id)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: existingAIHubProject.identity.principalId!
    principalType: 'ServicePrincipal'
    description:'001 - Azure AI Developer On AIServices From AIProject MI OID of: ${existingAIHubProject.name} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}
// Needed for Agents in AI Hub project, END

//  AI Hub & AI Project //
// --------------- AI Hub - specific ---------------- //
resource azureAIDeveloperRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(aiHubName)) {
  name: guid(existingAIHub.id, azureAIDeveloperRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'020 - AzureAIDeveloper role to USER with OID  ${userObjectIds[i]} for : ${existingAIHub.name}'
  }
  scope:existingAIHub
}]

resource azureAIDeveloperRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01'  = [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(aiHubName)) {
  name: guid(existingAIHub.id, azureAIDeveloperRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'021 - azureAIDeveloperRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAIHub.name}'
  }
  scope:existingAIHub
}]

// --------------- AI Project - specific ---------------- //

@description('AI Project: azureAIAdministrator:')
resource azureAIAdministratorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(aiHubProjectName)) {
  name: guid(existingAIHubProject.id, azureAIAdministrator, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'022 - azureAIAdministrator role to USER with OID  ${userObjectIds[i]} for : ${existingAIHubProject.name}'
  }
  scope:existingAIHubProject
}]
resource azureAIAdministratorAssignmentSP 'Microsoft.Authorization/roleAssignments@2022-04-01'= [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(aiHubProjectName)) {
  name: guid(existingAIHubProject.id, azureAIAdministrator, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'023 - azureAIAdministrator to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAIHubProject.name}'
  }
  scope:existingAIHubProject
}]

// Azure AI Developer
@description('AI Project: Azure AI Developer:')
resource aiDevOnAIProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(aiHubProjectName)) {
  name: guid(existingAIHubProject.id, azureAIDeveloperRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'024 - azureAIDeveloperRoleId role to USER with OID  ${userObjectIds[i]} for : ${existingAIHubProject.name}'
  }
  scope:existingAIHubProject
}]
resource aiDevOnAIProjectSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(aiHubProjectName)) {
  name: guid(existingAIHubProject.id, azureAIDeveloperRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'025 - azureAIDeveloperRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAIHubProject.name}'
  }
  scope:existingAIHubProject
}]

// 2025-05-25 - cognitiveServicesContributorRoleId on AI FOUNDRY_v2 (AI Services)

@description('AI Services: Azure Cognitive services contributor')
resource cogServiceContribOnAIProjectUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(aiServicesName)) {
  name: guid(existingAiServicesResource.id, cognitiveServicesContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'026 - cognitiveServicesContributorRoleId role to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]
@description('AI Services: Azure Cognitive services contributor')
resource cogServiceContribOnAIProjectSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(aiServicesName)) {
  name: guid(existingAiServicesResource.id, cognitiveServicesContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'027 - cognitiveServicesContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]

// end

resource cognitiveServicesUsagesReaderU 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(aiServicesName)) {
  name: guid(existingAiServicesResource.id, cognitiveServicesUsagesReaderId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUsagesReaderId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'002 - cognitiveServicesUsagesReaderId role to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to call data on data plane'
  }
  scope:existingAiServicesResource
}]
resource cognitiveServicesUsagesReaderSPU 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(aiServicesName)) {
  name: guid(existingAiServicesResource.id, cognitiveServicesUsagesReaderId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUsagesReaderId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'003 - cognitiveServicesUsagesReader role to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]
// 002

@description('Users to Azure AI Services: Cognitive Services OpenAI Contributor for users. Full access including the ability to fine-tune, deploy and generate text')
resource cognitiveServicesOpenAIContributorUsersU 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(aiServicesName)) {
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'004 - OpenAIContributorRole to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to call data on data plane'
  }
  scope:existingAiServicesResource
}]
resource cognitiveServicesOpenAIContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(aiServicesName)) {
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'005 - cognitiveServicesOpenAIContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]

@description('Users to Azure AI Services: Cognitive Services OpenAI User:Read access to view files, models, deployments. The ability to create completion and embedding calls.')
resource roleAssignmentCognitiveServicesOpenAIUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!empty(aiServicesName)) {
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'006 - OpenAICognitiveServicesUSer to USER with OID  ${userObjectIds[i]} for : ${existingAiServicesResource.name} to list API keys'
  }
  scope:existingAiServicesResource
}]
resource roleAssignmentCognitiveServicesOpenAISP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): if(!empty(aiServicesName)) {
  name: guid(existingAiServicesResource.id, cognitiveServicesOpenAIUserRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'007 - cognitiveServicesOpenAIUserRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAiServicesResource.name}'
  }
  scope:existingAiServicesResource
}]

// --------------- USERS END ---------------- //

