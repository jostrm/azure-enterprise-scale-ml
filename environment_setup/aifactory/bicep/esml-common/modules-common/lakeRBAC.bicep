param amlPrincipalId string = ''
param aiHubPrincipleId string = ''
param projectTeamGroupOrUser string[] = []
param adfPrincipalId string
param useAdGroups bool = false

var readerRoleDefinitionId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
//var contributorRole = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

param datalakeName string
resource datalakeFromCommon 'Microsoft.Storage/storageAccounts@2021-04-01' existing = {
  name: datalakeName
}

resource readerAML 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = if(!empty(amlPrincipalId)) {
  name: guid('${readerRoleDefinitionId}-reader-${amlPrincipalId}-${resourceGroup().id}')
  properties: {
    roleDefinitionId:subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleDefinitionId)
    principalId: amlPrincipalId
    principalType: 'ServicePrincipal'
    description: 'READER to AML Managed Identity: ${amlPrincipalId} for Azure ML Studio to get access to datalake: ${datalakeName}'
  }
  scope:datalakeFromCommon
}
resource lakeAIFoundry 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = if(!empty(aiHubPrincipleId)) {
  name: guid('${storageBlobDataContributor}-contributor-${aiHubPrincipleId}-${resourceGroup().id}')
  properties: {
    roleDefinitionId:subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
    principalId: aiHubPrincipleId
    principalType: 'ServicePrincipal'
    description: 'storageBlobDataContributor to Managed Identity: ${aiHubPrincipleId} for Azure AI Foundry to get access to datalake: ${datalakeName}'
  }
  scope:datalakeFromCommon
}

resource readerUserGroup 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(projectTeamGroupOrUser)):{
  name: guid('${projectTeamGroupOrUser[i]}-reader-${readerRoleDefinitionId}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleDefinitionId)
    principalId: projectTeamGroupOrUser[i]
    principalType:useAdGroups? 'Group':'User'
    description:'READER to USER or Group with OID  ${projectTeamGroupOrUser[i]} for lake: ${datalakeName}'
  }
  scope:datalakeFromCommon
}]


resource storageBlobDataContributorADF 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = if(!empty(adfPrincipalId)) {
  name: guid('${storageBlobDataContributor}-reader-${adfPrincipalId}-${resourceGroup().id}')
  properties: {
    roleDefinitionId:subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
    principalId: adfPrincipalId
    principalType:'ServicePrincipal'
    description: 'READER to ADF Managed Identity: ${adfPrincipalId} for Azure Datafactory to get accesst to datalake: ${datalakeName}'
  }
  scope:datalakeFromCommon
}

