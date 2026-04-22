param common_kv_name string
@description('Additional optional Object ID of more people to access Resource group')
param user_object_ids array
param bastion_service_name string
param addBastion bool = false
param useAdGroups bool = false
param servicePrincipleAndMIArray array = []
@description('Name of the VNet in the common resource group for Reader role assignment')
param vNetName string = ''

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

// VNet - Reader role (acdd72a7-3385-48ef-bd42-f606fba81ae7)
// Required for users/AD groups to view VNet configuration in the portal
resource readerRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = if (!empty(vNetName)) {
  scope: subscription()
  name: 'acdd72a7-3385-48ef-bd42-f606fba81ae7' // Built-in Reader role
}

resource vNet 'Microsoft.Network/virtualNetworks@2021-03-01' existing = if (!empty(vNetName)) {
  name: vNetName
}

resource readerUserVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)): if (!empty(vNetName)) {
  name: guid('${user_object_ids[i]}-reader-${vNetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: readerRoleDefinition.id
    principalId: user_object_ids[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: 'Reader to USER with OID ${user_object_ids[i]} for VNet: ${vNetName}'
  }
  scope: vNet
}]

resource readerSPVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(servicePrincipleAndMIArray)): if (!empty(vNetName)) {
  name: guid('${servicePrincipleAndMIArray[i]}-reader-${vNetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: readerRoleDefinition.id
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: 'Reader to SP/MI with OID ${servicePrincipleAndMIArray[i]} for VNet: ${vNetName}'
  }
  scope: vNet
}]
