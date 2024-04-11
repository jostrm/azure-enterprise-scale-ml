// Separate BICEP: OWNER to COMMON RG(aml, dsvm, kv, adf)
// Separete BICEP: OWNER to DASHBOARD RG
// Separate powershell: ACL on Datalake: 25-add-users-to-datalake-acl-rbac.ps1
// Separete powershell: AccessPolicy on COMMON Keyvault: 25-add-users-to-kv-get-list-access-policy.ps1

// OPTIONAL: OWNER to a PROJECT RG(aml, dsvm, kv, adf)

// NOT NEEDED: *READER on Bastion (in COMMON RG)
// NOT NEEDED:  *CONTRIBUTOR on Keyvault (in COMMON RG)
// NOT NEEDED: *CONTRIBUTOR on Bastion NSG
// NOT NEEDED: *networkContributorRoleDefinition on vNET


@description('Optional: resource group where user gets OWNER permission. ESML-COMMON-RG')
param common_resourcegroup_name string = ''
@description('Optional: resource group where user gets OWNER permission. ESML-PROJECT001-RG')
param project_resourcegroup_name string = ''
@description('Optional: resource group, usually called: dashboards, where on subscription where Azure Dashboards are stored centrally (Dashboards hub), or locally.')
param dashboard_resourcegroup_name string = ''
param user_object_ids array

// Owner
@description('This is the built-in Owner role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource ownerRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'
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

// RG's
resource project_resourcegroup 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: project_resourcegroup_name
  scope: subscription()
}

module projectRGOwnerPermissions './ownerRbac.bicep' = if(project_resourcegroup_name!= ''){
  scope: project_resourcegroup
  name: 'projectRGOwnerPerm4coremteamXY'
  params: {
   user_object_ids: user_object_ids
  }
  dependsOn:[
    project_resourcegroup
  ]
}

module projectVmAdminRGPermissions4Coreteam './rbacGeneric.bicep' = {
  scope: project_resourcegroup
  name: 'projectVmAdminRGPermissions4Coreteam'
  params: {
   user_object_ids: user_object_ids
   role_definition_id: vmAdminLoginRoleDefinition.id
  }
  dependsOn:[
    project_resourcegroup
  ]
}

resource common_resourcegroup 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: common_resourcegroup_name
  scope: subscription()
}

module commonRGOwnerPermissions './ownerRbac.bicep' = if(common_resourcegroup_name!= ''){
  scope: common_resourcegroup
  name: 'commonRGOwnerPermissions4coreteamXY'
  params: {
   user_object_ids: user_object_ids
  }
  dependsOn:[
    common_resourcegroup
  ]
}

module commonVmAdminRGPermissions4Coreteam './rbacGeneric.bicep' = {
  scope: common_resourcegroup
  name: 'commonVmAdminRGPermissions4Coreteam'
  params: {
   user_object_ids: user_object_ids
   role_definition_id: vmAdminLoginRoleDefinition.id
  }
  dependsOn:[
    common_resourcegroup
  ]
}

resource dashboard_resourcegroup 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: dashboard_resourcegroup_name
  scope: subscription()
}

module dashboardRGcontributorPermissions './ownerRbac.bicep' = if(dashboard_resourcegroup_name!= ''){
  scope: dashboard_resourcegroup
  name: 'dashboardRGcontributorPermissions4CoreXY'
  params: {
   user_object_ids: user_object_ids
  }
  dependsOn:[
    dashboard_resourcegroup
  ]
}


