// Separate BICEP: CONTRIBUTOR to PROJECT RG(aml, dsvm, kv, adf)
// Separete BICEP: CONTRIBUTOR to DASHBOARD RG
// Separete BICEP READER on Bastion (in COMMON RG)
// Separete BICEP: READER on Keyvault (in PROJECT RG)
// Separate powershell: ACL on Datalake: 25-add-users-to-datalake-acl-rbac.ps1
// Separete powershell: AccessPolicy on Keyvault: 25-add-users-to-kv-get-list-access-policy.ps1

// THIS BICEP: NSG, vNet
// *CONTRIBUTOR on Bastion NSG
// *networkContributorRoleDefinition on vNET

param vnet_name string
param vnet_resourcegroup_name string // This deployment. It is either COMMON RG, or external vNet RG
param common_bastion_subnet_name string = 'AzureBastionSubnet'
param project_service_principle_oid string
param user_object_ids string
param useAdGroups bool = false

var user_object_ids_array = array(split(replace(user_object_ids,' ',''),','))
var user_object_ids_array_Safe = user_object_ids == ''? []: user_object_ids_array
var service_principle_array = project_service_principle_oid == ''? []: array(split(project_service_principle_oid,','))

resource vnet_resourcegroup 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: vnet_resourcegroup_name
  scope: subscription()
}

module commonRGOwnerPermissions './ownerRbac.bicep' = {
  scope: vnet_resourcegroup
  name: 'commonRGOwnerPerm4coremteam123'
  params: {
   user_object_ids: user_object_ids_array_Safe
   useAdGroups:useAdGroups
  }
  dependsOn:[
    vnet_resourcegroup
  ]
}

// networkContributor
@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource networkContributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: '4d97b98b-1d4f-4787-a291-c67834d212e7'
}

// contributor
@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource contributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
}

// vNet - Network Contributor: Reader was not enough. Network Contributor is needed, to be able to JOIN subnets
// subet - Microsoft.Network/virtualNetworks/subnets/join/action
resource vNetNameResource 'Microsoft.Network/virtualNetworks@2021-03-01' existing = {
  name: vnet_name
}

resource networkContributorUserVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids_array_Safe)):{
  name: guid('${user_object_ids_array_Safe[i]}-nwContributor-${vnet_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: networkContributorRoleDefinition.id
    principalId: user_object_ids_array_Safe[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Network Contributor to USER with OID  ${user_object_ids_array_Safe[i]} for vNet: ${vnet_name}'
  }
  scope:vNetNameResource
}]

resource networkContributorSPVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(service_principle_array)):{
  name: guid('${service_principle_array[i]}-nwContribSP-${vnet_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: networkContributorRoleDefinition.id
    principalId: service_principle_array[i]
    principalType: 'ServicePrincipal'
    description:'Network Contributor to SERVICE PRINCIPLE with OID  ${service_principle_array[i]} for vNet: ${vnet_name}'
  }
  scope:vNetNameResource
}]


// NSG - contributor
resource nsgBastion4project 'Microsoft.Network/networkSecurityGroups@2020-06-01' existing = {
  name: 'nsg-${common_bastion_subnet_name}'
}

resource contributorUserBastionNSG 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids_array_Safe)):{
  name: guid('${user_object_ids_array_Safe[i]}-contributor-${common_bastion_subnet_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: user_object_ids_array_Safe[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Contributor to USER with OID  ${user_object_ids_array_Safe[i]} for Bastion NSG: ${common_bastion_subnet_name}'
  }
  scope:nsgBastion4project
}]
