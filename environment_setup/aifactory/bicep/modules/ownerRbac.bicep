@description('Object ID array of 1 or more people to access Resource group')
param user_object_ids array

@description('This is the built-in Owner role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource ownerRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'
}

resource contributorRole2user 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)):{
  name: guid('${user_object_ids[i]}-contributor-${resourceGroup().id}')
  properties: {
    roleDefinitionId: ownerRoleDefinition.id
    principalId: user_object_ids[i]
    principalType: 'User'
    description: 'Contributor to user to get Contributor on resource group: ${resourceGroup().name}'
  }
}]
