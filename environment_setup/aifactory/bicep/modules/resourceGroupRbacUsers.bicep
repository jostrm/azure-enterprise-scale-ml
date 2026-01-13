// Resource group–level RBAC assignments for users and service principals
// Extracted from aihubRbacUsers.bicep to keep RG scope roles isolated

param resourceGroupId string
param userObjectIds array
param servicePrincipleAndMIArray array
param useAdGroups bool = false
param disableContributorAccessForUsers bool = false
param disableRBACAdminOnRGForUsers bool = false
param aiHubName string = ''

var acrPushRoleId = '8311e382-0749-4cb8-b61a-304f252e45ec'
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
var roleBasedAccessControlAdministratorRG = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
var aiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var azureAIInferenceDeploymentOperatorRoleId = '3afb7f49-54cb-416e-8c09-6dc049efa503'
var azureMLDataScientistRoleId = 'f6c7c914-8db3-469d-8ca1-694a8f32e121'
var azureMachineLearningWorkspaceConnectionSecretsReaderRoleId = 'ea01e6af-a1c1-4350-9563-ad00f8c72ec5'

// Exclude privileged admin roles when assigning RBAC administrator
var ownerRoleId = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'
var userAccessAdministratorRoleId = '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9'
var rbacAdministratorRoleId = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
var excludePrivilegedRolesCondition = '((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/write\'} AND @Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${ownerRoleId}, ${userAccessAdministratorRoleId}, ${rbacAdministratorRoleId}})))'

// Azure AI User
@description('RG: AI Project: Azure AI User roles for creating deployments in the resource group')
resource aiUserUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, aiUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiUserRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '028 - Azure AI User role to USER with OID ${userObjectIds[i]} at RG scope'
  }
  scope: resourceGroup()
}]

resource aiUserSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, aiUserRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiUserRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '029 - Azure AI User to project service principal OID:${servicePrincipleAndMIArray[i]} at RG scope'
  }
  scope: resourceGroup()
}]

// Cognitive Services user
@description('RG: AI Project: Cognitive Services user role for basic SDK access')
resource cogServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, cognitiveServicesUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '030 - cognitiveServicesUserRoleId to USER with OID ${userObjectIds[i]} at RG scope'
  }
  scope: resourceGroup()
}]

resource cogServicesUserSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, cognitiveServicesUserRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '031 - cognitiveServicesUserRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} at RG scope'
  }
  scope: resourceGroup()
}]

// AI inference deployment operator
@description('RG: AI Project: AzureAIInferenceDeploymentOperator for deployments within the RG')
resource azureAIInferenceDeploymentOperatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureAIInferenceDeploymentOperatorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: empty(aiHubName)
      ? '032 - AzureAIInferenceDeploymentOperator role to USER with OID ${userObjectIds[i]} at RG scope'
      : '032 - AzureAIInferenceDeploymentOperator role to USER with OID ${userObjectIds[i]} at RG scope for ${aiHubName}'
  }
  scope: resourceGroup()
}]

resource azureAIInferenceDeploymentOperatorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, azureAIInferenceDeploymentOperatorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: empty(aiHubName)
      ? '033 - azureAIInferenceDeploymentOperatorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} at RG scope'
      : '033 - azureAIInferenceDeploymentOperatorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} at RG scope for ${aiHubName}'
  }
  scope: resourceGroup()
}]

// Azure ML Data Scientist
@description('RG: AI Hub / AI Project: Azure ML Data Scientist role at RG scope')
resource azureMLDataScientistRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureMLDataScientistRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: empty(aiHubName)
      ? '034 - AzureMLDataScientist role to USER with OID ${userObjectIds[i]} at RG scope'
      : '034 - AzureMLDataScientist role to USER with OID ${userObjectIds[i]} at RG scope for ${aiHubName}'
  }
  scope: resourceGroup()
}]

resource azureMLDataScientistRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, azureMLDataScientistRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: empty(aiHubName)
      ? '035 - azureMLDataScientistRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} at RG scope'
      : '035 - azureMLDataScientistRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} at RG scope for ${aiHubName}'
  }
  scope: resourceGroup()
}]

// AML workspace connection secrets reader
@description('RG: AI Hub / AI Project: AML workspace connection secrets reader at RG scope')
resource amlWorkspaceConnectionSecretsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: empty(aiHubName)
      ? '036 - AML Workspace Connection Secrets Reader role to USER with OID ${userObjectIds[i]} at RG scope'
      : '036 - AML Workspace Connection Secrets Reader role to USER with OID ${userObjectIds[i]} at RG scope for ${aiHubName}'
  }
  scope: resourceGroup()
}]

resource amlWorkspaceConnectionSecretsReaderSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: empty(aiHubName)
      ? '037 - AML Workspace Connection Secrets Reader to project service principal OID:${servicePrincipleAndMIArray[i]} at RG scope'
      : '037 - AML Workspace Connection Secrets Reader to project service principal OID:${servicePrincipleAndMIArray[i]} at RG scope for ${aiHubName}'
  }
  scope: resourceGroup()
}]

// Contributor
@description('Role Assignment for Resource Group: Contributor for users')
resource contributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!disableContributorAccessForUsers){
  name: guid(resourceGroupId, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '038 - CONTRIBUTOR on RG to USER with OID ${userObjectIds[i]} for ${resourceGroupId}'
  }
  scope: resourceGroup()
}]

resource contributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, contributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '039 - contributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} for ${resourceGroupId}'
  }
  scope: resourceGroup()
}]

// RBAC Admin
@description('Role Assignment for Resource Group: Role Based Access Control Administrator for users with conditions to exclude privileged roles')
resource roleBasedAccessControlAdminRGRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!disableRBACAdminOnRGForUsers){
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '040 - RoleBasedAccessControlAdministrator on RG to USER with OID ${userObjectIds[i]} for ${resourceGroupId} - excludes privileged administrator roles'
    condition: excludePrivilegedRolesCondition
    conditionVersion: '2.0'
  }
  scope: resourceGroup()
}]

resource roleBasedAccessControlAdminRGRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '041 - roleBasedAccessControlAdministrator to project service principal OID:${servicePrincipleAndMIArray[i]} for RG: ${resourceGroupId} - excludes privileged administrator roles'
    condition: excludePrivilegedRolesCondition
    conditionVersion: '2.0'
  }
  scope: resourceGroup()
}]

// ACR push
@description('Role Assignment for Resource Group: acrPush role for users')
resource acrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, acrPushRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '042 - acrPush role on RG to USER with OID ${userObjectIds[i]} for RG: ${resourceGroupId}'
  }
  scope: resourceGroup()
}]

resource acrPushSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, acrPushRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '043 - acrPush role to project service principal OID:${servicePrincipleAndMIArray[i]} for RG: ${resourceGroupId}'
  }
  scope: resourceGroup()
}]
