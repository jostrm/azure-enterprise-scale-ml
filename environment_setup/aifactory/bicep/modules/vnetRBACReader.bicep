@description('Specifies the name the datafactory resource')
param vNetName string
param common_bastion_subnet_name string

var readerRoleDefinitionId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource readerRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: readerRoleDefinitionId
}

@description('Additional optional Object ID of more people to access Resource group')
param additionalUserIds array
var all_principals = additionalUserIds

resource vNetNameResource 'Microsoft.Network/virtualNetworks@2021-03-01' existing = {
  name: vNetName
}

resource readerUserVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(all_principals)):{
  name: guid('${all_principals[i]}-reader-${vNetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: readerRoleDefinition.id
    principalId: all_principals[i]
    principalType: 'User'
    description:'Reader to USER with OID  ${all_principals[i]} for vNet: ${vNetName}'
  }
  scope:vNetNameResource
}]

@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource contributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
}

resource nsgBastion4project 'Microsoft.Network/networkSecurityGroups@2020-06-01' existing = {
  name: 'nsg-${common_bastion_subnet_name}'
}

resource contributorUserBastionNSG 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(all_principals)):{
  name: guid('${all_principals[i]}-contributor-${common_bastion_subnet_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: all_principals[i]
    principalType: 'User'
    description:'Contributor to USER with OID  ${all_principals[i]} for Bastion NSG: ${common_bastion_subnet_name}'
  }
  scope:nsgBastion4project
}]
