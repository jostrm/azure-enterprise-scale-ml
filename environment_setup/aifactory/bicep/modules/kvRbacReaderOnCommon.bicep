param common_kv_name string
@description('Additional optional Object ID of more people to access Resource group')
param user_object_ids array
param bastion_service_name string
param addBastion bool = false
param useAdGroups bool = false

@description('Key Vault role level: user = Key Vault Secrets User, officer = Key Vault Secrets Officer, admin = Key Vault Administrator')
@allowed(['user', 'officer', 'admin'])
param kvRoleLevel string = 'admin'

var secretsUserRoleDefinitionId = '4633458b-17de-408a-b874-0445c86b69e6'
var secretsOfficerRoleDefinitionId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var adminRoleDefinitionId = '00482a5a-887f-4fb3-b363-3b7fe8e74483'
var selectedRoleId = kvRoleLevel == 'admin' ? adminRoleDefinitionId : (kvRoleLevel == 'officer' ? secretsOfficerRoleDefinitionId : secretsUserRoleDefinitionId)
var selectedRoleLabel = kvRoleLevel == 'admin' ? 'KeyVaultAdministrator' : (kvRoleLevel == 'officer' ? 'KeyVaultSecretsOfficer' : 'KeyVaultSecretsUser')

resource kvRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: selectedRoleId
}

resource commonKvReader 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: common_kv_name
}
resource readerUserCommonKv 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)):{
  name: guid('${user_object_ids[i]}-${selectedRoleLabel}-${common_kv_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: kvRoleDefinition.id
    principalId: user_object_ids[i]
    principalType:useAdGroups? 'Group':'User'
    description:'${selectedRoleLabel} to USER with OID  ${user_object_ids[i]} for keyvault: ${common_kv_name}'
  }
  scope:commonKvReader
}]

// Bastion "bastion-uks-dev-001" - READER

resource resBastion4project 'Microsoft.Network/bastionHosts@2021-05-01' existing = if (addBastion) {
  name: bastion_service_name
}

resource readerUserBastion 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)): if (addBastion) {
  name: guid('${user_object_ids[i]}-reader-${bastion_service_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: kvRoleDefinition.id
    principalId: user_object_ids[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Reader to USER with OID  ${user_object_ids[i]} for Bastion service: ${bastion_service_name}'
  }
  scope:resBastion4project
}]
