param amlPrincipalId string
param userPrincipalId string
param adfPrincipalId string

var readerRoleDefinitionId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
//var contributorRole = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

param datalakeName string
resource datalakeFromCommon 'Microsoft.Storage/storageAccounts@2021-04-01' existing = {
  name: datalakeName
}

resource readerAML 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid('${readerRoleDefinitionId}-reader-${amlPrincipalId}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/${readerRoleDefinitionId}'
    principalId: amlPrincipalId
    principalType: 'ServicePrincipal'
    description: 'READER to ServicePrincipal ${amlPrincipalId} for Azure ML Studio to get access to datalake: ${datalakeName}'
  }
  scope:datalakeFromCommon
}
resource readerUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid('${readerRoleDefinitionId}-reader-${userPrincipalId}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/${readerRoleDefinitionId}'
    principalId: userPrincipalId
    principalType: 'User'
    description: 'READER to USER ${userPrincipalId} for AD-user to get access to datalake: ${datalakeName}'
  }
  scope:datalakeFromCommon
}
resource storageBlobDataContributorADF 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid('${readerRoleDefinitionId}-storageBlobDataContributor-${adfPrincipalId}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/${storageBlobDataContributor}'
    principalId: adfPrincipalId
    principalType:'ServicePrincipal'
    description: 'READER to ServicePrincipal ${adfPrincipalId} for Azure Datafactory to get accesst to datalake: ${datalakeName}'
  }
  scope:datalakeFromCommon
}
