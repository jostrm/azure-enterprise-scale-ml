@description('Specifies the name the datafactory resource')
param vNetName string
param common_bastion_subnet_name string
param bastion_service_name string
param common_kv_name string

var readerRoleDefinitionId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource readerRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: readerRoleDefinitionId
}

@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource networkContributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: '4d97b98b-1d4f-4787-a291-c67834d212e7'
}

@description('Additional optional Object ID of more people to access Resource group')
param additionalUserIds array
var all_principals = additionalUserIds

// vNet - Network Contributor: Reader was not enough. Network Contributor is needed, to be able to JOIN subnets
// subet - Microsoft.Network/virtualNetworks/subnets/join/action
resource vNetNameResource 'Microsoft.Network/virtualNetworks@2021-03-01' existing = {
  name: vNetName
}

resource networkContributorUserVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(all_principals)):{
  name: guid('${all_principals[i]}-nwContributor-${vNetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: networkContributorRoleDefinition.id
    principalId: all_principals[i]
    principalType: 'User'
    description:'Network Contributor to USER with OID  ${all_principals[i]} for vNet: ${vNetName}'
  }
  scope:vNetNameResource
}]


// NSG - contributor
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

// Bastion "bastion-uks-dev-001" - READER

resource resBastion4project 'Microsoft.Network/bastionHosts@2021-05-01' existing = {
  name: bastion_service_name
}

resource readerUserBastion 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(all_principals)):{
  name: guid('${all_principals[i]}-reader-${bastion_service_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: readerRoleDefinition.id
    principalId: all_principals[i]
    principalType: 'User'
    description:'Reader to USER with OID  ${all_principals[i]} for Bastion service: ${bastion_service_name}'
  }
  scope:resBastion4project
}]

// Common Keyvault "bastion-uks-dev-001" - READER
resource commonKvReader 'Microsoft.KeyVault/vaults@2019-09-01' existing = {
  name: common_kv_name
}
resource readerUserCommonKv 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(all_principals)):{
  name: guid('${all_principals[i]}-reader-${common_kv_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: readerRoleDefinition.id
    principalId: all_principals[i]
    principalType: 'User'
    description:'Reader to USER with OID  ${all_principals[i]} for keyvault: ${common_kv_name}'
  }
  scope:commonKvReader
}]

