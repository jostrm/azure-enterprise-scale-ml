@description('Additional optional Object ID of more people to access Resource group')
param user_object_ids array
param role_definition_id string
param useAdGroups bool = false

var sub_role = substring(role_definition_id,0,5)

resource contributorRole2user 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)):{
  name: guid('${user_object_ids[i]}-role${sub_role}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: role_definition_id
    principalId: user_object_ids[i]
    principalType:useAdGroups? 'Group':'User'
    description: 'Role ${role_definition_id} to user to get Contributor on resource group: ${resourceGroup().name}'
  }
}]
