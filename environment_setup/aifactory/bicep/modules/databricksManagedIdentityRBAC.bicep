param location string
param managedIdentityName string
param databricksName string
// TODO: Check if the permission can be more specific
// get Owner permission using built in assignments
// https://docs.microsoft.com/en-us/azure/active-directory/roles/permissions-reference
// https://docs.microsoft.com/en-us/azure/role-based-access-control/built-in-roles
var ownerRoleId = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'


resource mIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2018-11-30' = {
  name: managedIdentityName
  location: location
}

resource databricks4Project 'Microsoft.Databricks/workspaces@2021-04-01-preview' existing = {
  name: databricksName
}


resource roleAssignment 'Microsoft.Authorization/roleAssignments@2020-08-01-preview' = {
  name: guid('${managedIdentityName}-${mIdentity.id}-${ownerRoleId}-${resourceGroup().id}')
  scope: databricks4Project
  properties: {
    principalType: 'ServicePrincipal'
    principalId: mIdentity.properties.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', ownerRoleId)
    description: 'OWNER to ManagedIdentity ${managedIdentityName}on resource group workspace'
  }
}

output mIdentityId string = mIdentity.id
output mIdentityClientId string = mIdentity.properties.clientId
