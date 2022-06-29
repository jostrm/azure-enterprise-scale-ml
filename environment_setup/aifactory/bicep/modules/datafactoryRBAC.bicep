param userPrincipalId string
param datafactoryName string
var contributorRole = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
//param projectSP string

@description('Additional optional Object ID of more people to access Resource group')
param additionalUserIds array
var main_principal_2_array = array(userPrincipalId)
var all_principals = union(main_principal_2_array,additionalUserIds)

resource datafactoryRes 'Microsoft.DataFactory/factories@2018-06-01' existing = {
  name: datafactoryName
}

resource contributorUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(all_principals)):{
  name: guid('${all_principals[i]}-${contributorRole}-${datafactoryName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/${contributorRole}'
    principalId: all_principals[i]
    principalType: 'User'
    description:'Contributor to USER with OID  ${all_principals[i]} for Databricks: ${datafactoryName}'
  }
  scope:datafactoryRes
}]
