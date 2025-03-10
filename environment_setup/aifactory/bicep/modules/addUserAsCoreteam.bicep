// This BICEP: STORAGE BLOB DATA OWNER to STORAGE account RG
// Separate BICEP: OWNER to COMMON RG(aml, dsvm, kv, adf)
// Separate BICEP: OWNER to DASHBOARD RG
// Separate powershell: AccessPolicy on COMMON Keyvault: 25-add-users-to-kv-get-list-access-policy.ps1

// OPTIONAL: OWNER to a PROJECT RG(aml, dsvm, kv, adf)
// OPTIONAL: Separete powershell: AccessPolicy on PROJECT Keyvault: 25-add-users-to-kv-get-list-access-policy.ps1

// NOT NEEDED: *READER on Bastion (in COMMON RG)
// NOT NEEDED: *CONTRIBUTOR on Keyvault (in COMMON RG)
// NOT NEEDED: *CONTRIBUTOR on Bastion NSG 
// NOT NEEDED: *networkContributorRoleDefinition on vNET 
// NOT NEEDED: Separate powershell: ACL on Datalake MASTER: 25-add-users-to-datalake-acl-rbac.ps1

@description('Resource group where user gets OWNER permission. ESML-COMMON-RG')
param common_resourcegroup_name string = ''
@description('Comma separated string of Object ID of 1 or more people to access Resource group')
param user_object_ids string
@description('Datalake storage account to get RWE on both MASTER and PROEJCTS. Note: Even if OWNER permission on RG, a user needs STORAGE BLOB DATA OWNER or STORAGE BLOB DATA CONTRIBUTOR on the storage account. Or ACLs set')
param storage_account_name_datalake string = ''
@description('Optional, but tip: Always pass the CORE-TEAMS project resource group: esml-project001-dev-rg is usually the DEFAULT (in DEV)Always pass the CORE-TEAMS project resource group: esml-project001-dev-rg is usually the DEFAULT (in DEV)')
param project_resourcegroup_name string = ''
@description('Optional: resource group, usually called: dashboards, where on subscription where Azure Dashboards are stored centrally (Dashboards hub), or locally.')
param dashboard_resourcegroup_name string = ''
param useAdGroups bool = false

var user_object_ids_array = array(split(replace(user_object_ids,' ',''),','))
var user_object_ids_array_Safe = user_object_ids == ''? []: user_object_ids_array

@description('This is the built-in Storage Blob Data Contributor role. See https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/storage#storage-blob-data-contributor')
resource storageBlobDataContributor 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
}

@description('This is the built-in Storage Blob Data Owner role. See https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/storage#storage-blob-data-owner')
resource storageBlobDataOwner 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
}

// RG: Always pass the CORE-TEAMS project resource group: esml-project001-dev-rg is usually the DEFAULT (in DEV)
resource project_resourcegroup 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: project_resourcegroup_name
  scope: subscription()
}

module projectRGOwnerPermissions './ownerRbac.bicep' = if(project_resourcegroup_name!= ''){
  scope: project_resourcegroup
  name: 'projectRGOwnerPerm4coremteamXY'
  params: {
   user_object_ids: user_object_ids_array_Safe
   useAdGroups:useAdGroups
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
   user_object_ids: user_object_ids_array_Safe
   useAdGroups:useAdGroups
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
   user_object_ids: user_object_ids_array_Safe
   useAdGroups:useAdGroups
  }
  dependsOn:[
    dashboard_resourcegroup
  ]
}

resource resCommonDatalakeStorage 'Microsoft.Storage/storageAccounts@2021-04-01' existing = {
  name: storage_account_name_datalake
}

resource readerUserBastion 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids_array_Safe)):{
  name: guid('${user_object_ids_array_Safe[i]}-reader-${storage_account_name_datalake}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: storageBlobDataOwner.id
    principalId: user_object_ids_array_Safe[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Storage Blob Data Owner to USER with OID  ${user_object_ids_array_Safe[i]} for storage account datalake: ${storage_account_name_datalake}'
  }
  scope:resCommonDatalakeStorage
}]


