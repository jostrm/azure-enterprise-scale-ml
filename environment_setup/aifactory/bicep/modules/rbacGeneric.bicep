@description('ObjectId')
param objectId string
@description('roleDefinition ID')
param roleDefinitionId string
@description('bicep resource XYZ ')
param scopeResourceName string

/*
resource scopeObject 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: scopeResourceName
}

resource rbacRole 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid('${roleDefinitionId}-rbac-${resourceGroup().name}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/${roleDefinitionId}'
    principalId: objectId
  }
  scope:scopeObject
}
*/
