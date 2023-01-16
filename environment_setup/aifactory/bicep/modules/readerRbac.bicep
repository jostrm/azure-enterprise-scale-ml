@description('Specifies the objectId of the person that ordered the resources')
param userId string

@description('Specifies the email address of the person that ordered the resources')
param userEmail string

@description('This is the built-in Reader role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#reader')
resource readerRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
}

resource readerRole 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid('${userEmail}-reader-${resourceGroup().name}')
  properties: {
    roleDefinitionId:  readerRoleDefinition.id
    principalId: userId
  }
}
