param common_kv_name string
@description('Additional optional Object ID of more people to access Resource group')
param user_object_ids array

var readerRoleDefinitionId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource readerRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: readerRoleDefinitionId
}

resource commonKvReader 'Microsoft.KeyVault/vaults@2019-09-01' existing = {
  name: common_kv_name
}
resource readerUserCommonKv 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)):{
  name: guid('${user_object_ids[i]}-reader-${common_kv_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: readerRoleDefinition.id
    principalId: user_object_ids[i]
    principalType: 'User'
    description:'Reader to USER with OID  ${user_object_ids[i]} for keyvault: ${common_kv_name}'
  }
  scope:commonKvReader
}]
