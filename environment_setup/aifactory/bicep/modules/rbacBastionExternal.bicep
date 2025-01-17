@description('Additional optional Object ID of more people to access Resource group')
param user_object_ids array
param bastion_service_name string

var readerRoleDefinitionId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource readerRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: readerRoleDefinitionId
}

resource resBastion4project 'Microsoft.Network/bastionHosts@2021-05-01' existing = {
  name: bastion_service_name
}

resource readerUserBastion 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)):{
  name: guid('${user_object_ids[i]}-reader-${bastion_service_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: readerRoleDefinition.id
    principalId: user_object_ids[i]
    principalType: 'User'
    description:'Reader to USER with OID  ${user_object_ids[i]} for Bastion service: ${bastion_service_name}'
  }
  scope:resBastion4project
}]
