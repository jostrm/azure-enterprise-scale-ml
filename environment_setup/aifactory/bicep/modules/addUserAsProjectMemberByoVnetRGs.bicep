// Separate BICEP: CONTRIBUTOR to PROJECT RG(aml, dsvm, kv, adf)
// Separete BICEP: CONTRIBUTOR to DASHBOARD RG
// *READER on Bastion (in COMMON RG)
// *READER on DATALAKE STORAGE (in COMMON RG)
// *READER on Keyvault (in PROJECT RG)
// *CONTRIBUTOR on Bastion NSG
// *networkContributorRoleDefinition on vNET
// Separate powershell: ACL on Datalake: 25-add-users-to-datalake-acl-rbac.ps1
// Separete powershell: AccessPolicy on Keyvault: 25-add-users-to-kv-get-list-access-policy.ps1

@description('Optional: resource group, usually called: dashboards, where on subscription where Azure Dashboards are stored centrally (Dashboards hub), or locally.')
param dashboard_resourcegroup_name string = 'dashboards'
param storage_account_name_datalake string
param bastion_service_name string
param project_resourcegroup_name string
param user_object_ids string

var user_object_ids_array = array(split(replace(user_object_ids,' ',''),','))
var user_object_ids_array_Safe = user_object_ids == ''? []: user_object_ids_array

// READER
var readerRoleDefinitionId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
@description('This is the built-in READER role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource readerRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: readerRoleDefinitionId
}

// contributor
@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource contributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
}

// VM Administator Login
@description('This is the built-in VM Administator Login role. See https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/compute#virtual-machine-administrator-login')
resource vmAdminLoginRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: '1c0163c0-47e6-4577-8991-ea5c82e286e4'
}

// Bastion "bastion-uks-dev-001" - READER

resource resBastion4project 'Microsoft.Network/bastionHosts@2021-05-01' existing = {
  name: bastion_service_name
}

resource readerUserBastion 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids_array_Safe)):{
  name: guid('${user_object_ids_array_Safe[i]}-reader-${bastion_service_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: readerRoleDefinition.id
    principalId: user_object_ids_array_Safe[i]
    principalType: 'User'
    description:'Reader to USER with OID  ${user_object_ids_array_Safe[i]} for Bastion service: ${bastion_service_name}'
  }
  scope:resBastion4project
}]

// DATA LAKE - READER
resource common_datalake 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storage_account_name_datalake
}
resource readerDatalakeStorage 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids_array_Safe)):{
  name: guid('${user_object_ids_array_Safe[i]}-reader-${bastion_service_name}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: readerRoleDefinition.id
    principalId: user_object_ids_array_Safe[i]
    principalType: 'User'
    description:'Reader to USER with OID  ${user_object_ids_array_Safe[i]} for DATALAKE storage: ${storage_account_name_datalake}'
  }
  scope:common_datalake
}]

// RG's 

resource project_resourcegroup 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: project_resourcegroup_name
  scope: subscription()
}

module projectRGcontributorPermissions './contributorRbacSimple.bicep' = {
  scope: project_resourcegroup
  name: 'projectRGcontributorPermissions123'
  params: {
   user_object_ids: user_object_ids_array_Safe
  }
  dependsOn:[
    project_resourcegroup
  ]
}

module projectVmAdminRGcontributorPermissions './rbacGeneric.bicep' = {
  scope: project_resourcegroup
  name: 'projectVmAdminRGcontributorPermissions'
  params: {
   user_object_ids: user_object_ids_array_Safe
   role_definition_id: vmAdminLoginRoleDefinition.id
  }
  dependsOn:[
    project_resourcegroup
  ]
}

resource dashboard_resourcegroup 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: dashboard_resourcegroup_name
  scope: subscription()
}

module dashboardRGcontributorPermissions './contributorRbacSimple.bicep' = {
  scope: resourceGroup(dashboard_resourcegroup_name)
  name: 'dashboardRGcontributorPermissions3456'
  params: {
   user_object_ids: user_object_ids_array_Safe
  }
  dependsOn:[
    dashboard_resourcegroup
  ]
}
