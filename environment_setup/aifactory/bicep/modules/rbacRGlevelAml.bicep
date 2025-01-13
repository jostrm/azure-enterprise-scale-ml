// Parameters
@description('The list of user object IDs to assign roles to.')
param userObjectIds array

@description('The object ID of the service principal.')
@secure()
param servicePrincipleObjectId string

@description('The resource group ID.')
param resourceGroupId string

// ############## RG level ##############

var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // User -> RG
var roleBasedAccessControlAdministratorRG = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
var acrPushRoleId = '8311e382-0749-4cb8-b61a-304f252e45ec' // SP, user -> RG
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // EP, App service or Function app -> RG
// ############## RG LEVEL END

// --------------- RG:User Access Admin//
@description('Role Assignment for ResoureGroup: RoleBasedAccessControlAdministrator for users.')
resource roleBasedAccessControlAdminRGRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'030: RoleBasedAccessControlAdministrator on RG to USER with OID  ${userObjectIds[i]} for : ${resourceGroupId}'
  }
  scope:resourceGroup()
}]
resource roleBasedAccessControlAdminRGRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, roleBasedAccessControlAdministratorRG, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBasedAccessControlAdministratorRG)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'roleBasedAccessControlAdministrator to project service principal OID:${servicePrincipleObjectId} for RG: ${resourceGroupId}'
  }
  scope:resourceGroup()
}

// --------------- RG: Container Registry, PULL //
@description('Role Assignment for ResoureGroup: acrPushRoleId for users.')
resource acrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, acrPushRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'030: acrPush role on RG to USER with OID  ${userObjectIds[i]} for RG: ${resourceGroupId}'
  }
  scope:resourceGroup()
}]

resource acrPushSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, acrPushRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'acrPush role to project service principal OID:${servicePrincipleObjectId} for RG: ${resourceGroupId}'
  }
  scope:resourceGroup()
}
// --------------- USERS END ---------------- //


// --------------- RG:CONTRIBUTOR//
/*
@description('Role Assignment for ResoureGroup: CONTRIBUTOR for users.')
resource contributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(resourceGroupId, contributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'029: CONTRIBUTOR on RG to USER with OID  ${userObjectIds[i]} for ${resourceGroupId}'
  }
  scope:resourceGroup()
}]

resource contributorRoleSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, contributorRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'contributorRoleId to project service principal OID:${servicePrincipleObjectId} for ${resourceGroupId}'
  }
  scope:resourceGroup()
}
*/
