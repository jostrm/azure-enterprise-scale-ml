@description('Specifies the objectId of the technical contact')
param userPrincipalId string

@description('Specifies the name the databricks resource')
param databricksName string
param useAdGroups bool = false

@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource contributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
}

@description('Additional optional Object ID of more people to access Resource group')
param additionalUserIds array
var main_principal_2_array = array(userPrincipalId)
var all_principals = union(main_principal_2_array,additionalUserIds)

resource databricks4Project 'Microsoft.Databricks/workspaces@2021-04-01-preview' existing = {
  name: databricksName
}

resource contributorUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(all_principals)):{
  name: guid('${all_principals[i]}-contributor-${databricksName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: all_principals[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Contributor to USER with OID  ${all_principals[i]} for Databricks: ${databricksName}'
  }
  scope:databricks4Project
}]
