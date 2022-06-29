@description('Specifies the objectId of the person that ordered the resources')
param userId string

@description('Specifies the email address of the person that ordered the resources')
param userEmail string

resource readerRole 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid('${userEmail}-reader-${resourceGroup().name}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7'
    principalId: userId
  }
}
