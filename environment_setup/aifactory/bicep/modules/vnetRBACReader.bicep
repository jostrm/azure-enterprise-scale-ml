@description('Specifies the name the datafactory resource')
param vNetName string
param common_bastion_subnet_name string
param servicePrincipleAndMIArray array // Service Principle Object ID, User created MAnaged Identity
@description('Additional optional Object ID of more people to access Resource group')
param user_object_ids array
param useAdGroups bool = false // Use AD groups for role assignments

@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource networkContributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: '4d97b98b-1d4f-4787-a291-c67834d212e7'
}

// vNet - Network Contributor: Reader was not enough. Network Contributor is needed, to be able to JOIN subnets
// subet - Microsoft.Network/virtualNetworks/subnets/join/action
resource vNetNameResource 'Microsoft.Network/virtualNetworks@2021-03-01' existing = {
  name: vNetName
}

resource networkContributorUserVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)):{
  name: guid('${user_object_ids[i]}-nwContributor-${vNetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: networkContributorRoleDefinition.id
    principalId: user_object_ids[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Network Contributor to USER with OID  ${user_object_ids[i]} for vNet: ${vNetName}'
  }
  scope:vNetNameResource
}]

resource networkContributorSPVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid('${servicePrincipleAndMIArray[i]}-nwContribSP-${vNetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: networkContributorRoleDefinition.id
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'Network Contributor to SERVICE PRINCIPLE with OID  ${servicePrincipleAndMIArray[i]} for vNet: ${vNetName}'
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

resource contributorUserBastionNSG 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)):{
  name: guid('${user_object_ids[i]}-contributor-${common_bastion_subnet_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: user_object_ids[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Contributor to USER with OID  ${user_object_ids[i]} for Bastion NSG: ${common_bastion_subnet_name}'
  }
  scope:nsgBastion4project
}]
