@description('Resource group scope RBAC for users and service principals/MIs')
param resourceGroupId string
param userObjectIds array
param servicePrincipleAndMIArray array
param useAdGroups bool = false
param disableContributorAccessForUsers bool = false
param disableRBACAdminOnRGForUsers bool = false
param aiHubName string = ''

var aiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var azureAIInferenceDeploymentOperatorRoleId = '3afb7f49-54cb-416e-8c09-6dc049efa503'
var azureMLDataScientistRoleId = 'f6c7c914-8db3-469d-8ca1-694a8f32e121'
var azureMachineLearningWorkspaceConnectionSecretsReaderRoleId = 'ea01e6af-a1c1-4350-9563-ad00f8c72ec5'
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
var roleBasedAccessControlAdministratorRG = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
var acrPushRoleId = '8311e382-0749-4cb8-b61a-304f252e45ec'

var ownerRoleId = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'
var userAccessAdministratorRoleId = '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9'
var rbacAdministratorRoleId = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
var excludePrivilegedRolesCondition = '((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/write\'} AND @Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${ownerRoleId}, ${userAccessAdministratorRoleId}, ${rbacAdministratorRoleId}})))'

@description('RG: Azure AI User for users')
resource aiUserUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, aiUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiUserRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '028 - Azure AI User role to principal ${userObjectIds[i]} at RG scope'
  }
  scope: resourceGroup()
}]

@description('RG: Azure AI User for SP/MI')
resource aiUserSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, aiUserRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aiUserRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '029 - Azure AI User to SP/MI ${servicePrincipleAndMIArray[i]} at RG scope'
  }
  scope: resourceGroup()
}]

@description('RG: Cognitive Services User for users')
resource cogServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, cognitiveServicesUserRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '030 - cognitiveServicesUserRoleId to principal ${userObjectIds[i]} at RG scope'
  }
  scope: resourceGroup()
}]

@description('RG: Cognitive Services User for SP/MI')
resource cogServicesUserSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, cognitiveServicesUserRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '031 - cognitiveServicesUserRoleId to SP/MI ${servicePrincipleAndMIArray[i]} at RG scope'
  }
  scope: resourceGroup()
}]

@description('RG: Azure AI Inference Deployment Operator for users')
resource azureAIInferenceDeploymentOperatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureAIInferenceDeploymentOperatorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '032 - AzureAIInferenceDeploymentOperator to principal ${userObjectIds[i]} at RG scope'
  }
  scope: resourceGroup()
}]

@description('RG: Azure AI Inference Deployment Operator for SP/MI')
resource azureAIInferenceDeploymentOperatorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, azureAIInferenceDeploymentOperatorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIInferenceDeploymentOperatorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '033 - azureAIInferenceDeploymentOperatorRoleId to SP/MI ${servicePrincipleAndMIArray[i]} at RG scope'
  }
  scope: resourceGroup()
}]

@description('RG: Azure ML Data Scientist for users')
resource azureMLDataScientistRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureMLDataScientistRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '034 - AzureMLDataScientist to principal ${userObjectIds[i]} for ${aiHubName}'
  }
  scope: resourceGroup()
}]

@description('RG: Azure ML Data Scientist for SP/MI')
resource azureMLDataScientistRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, azureMLDataScientistRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMLDataScientistRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '035 - azureMLDataScientistRoleId to SP/MI ${servicePrincipleAndMIArray[i]} for ${aiHubName}'
  }
  scope: resourceGroup()
}]

@description('RG: AML workspace connection secrets reader for users')
resource amlWorkspaceConnectionSecretsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '036 - AML connection secrets reader to principal ${userObjectIds[i]} for ${aiHubName}'
  }
  scope: resourceGroup()
}]

@description('RG: AML workspace connection secrets reader for SP/MI')
resource amlWorkspaceConnectionSecretsReaderSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, azureMachineLearningWorkspaceConnectionSecretsReaderRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMachineLearningWorkspaceConnectionSecretsReaderRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '037 - AML connection secrets reader to SP/MI ${servicePrincipleAndMIArray[i]} for ${aiHubName}'
  }
  scope: resourceGroup()
}]

@description('RG: Contributor for users (optional)')
resource contributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!disableContributorAccessForUsers) {
  name: guid(resourceGroupId, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '038 - Contributor on RG to principal ${userObjectIds[i]}'
  }
  scope: resourceGroup()
}]

@description('RG: Contributor for SP/MI')
resource contributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, contributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '039 - contributorRoleId to SP/MI ${servicePrincipleAndMIArray[i]} for RG'
  }
  scope: resourceGroup()
}]

@description('RG: Role Based Access Control Administrator for users (optional)')
resource roleBasedAccessControlAdminRGRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)): if(!disableRBACAdminOnRGForUsers) {
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '040 - RoleBasedAccessControlAdministrator on RG to principal ${userObjectIds[i]}'
    condition: excludePrivilegedRolesCondition
    conditionVersion: '2.0'
  }
  scope: resourceGroup()
}]

@description('RG: Role Based Access Control Administrator for SP/MI')
resource roleBasedAccessControlAdminRGRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '041 - roleBasedAccessControlAdministrator to SP/MI ${servicePrincipleAndMIArray[i]} at RG scope'
    condition: excludePrivilegedRolesCondition
    conditionVersion: '2.0'
  }
  scope: resourceGroup()
}]

@description('RG: ACR push/pull for users')
resource acrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, acrPushRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: userObjectIds[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: '042 - acrPush role on RG to principal ${userObjectIds[i]}'
  }
  scope: resourceGroup()
}]

@description('RG: ACR push/pull for SP/MI')
resource acrPushSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(resourceGroupId, acrPushRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: '043 - acrPush role to SP/MI ${servicePrincipleAndMIArray[i]} at RG scope'
  }
  scope: resourceGroup()
}]
