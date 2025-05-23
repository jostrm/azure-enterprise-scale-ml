metadata description = 'Creates role assignments for Redis Cache.'
param usersOrAdGroupArray array
param servicePrincipleAndMIArray array
param redisName string
param useAdGroups bool

// Redis Cache built-in roles
// https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles

// Lets you manage Redis caches, but not access to them.
var redisContributorRoleId = 'e0f68234-74aa-48ed-b826-c38b57376e17' // Redis Cache Contributor

// 	View all resources, but does not allow you to make any changes.
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'       // Reader role
// Grants full access to manage all resources
var contributorId = 'fcfef8a3-163d-4692-937a-460c785b8fdb'        // Contributor role - error'fcfef8a3163d4692937a460c785b8fdb'

resource redis 'Microsoft.Cache/redis@2023-08-01' existing = {
  name: redisName
}

/*
// Contributor: Role assignments for users or AD groups
resource userRedisRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in usersOrAdGroupArray: {
  name: guid(redis.id, contributorId, principalId)
  scope: redis
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorId)
    principalId: principalId
    principalType:useAdGroups? 'Group':'User'
  }
}]

// Admin: Role assignments for service principals and managed identities
resource spRedisRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in servicePrincipleAndMIArray: {
  name: guid(redis.id, contributorId, principalId) // Updated to use redisAdminRoleId
  scope: redis
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorId) // Updated to use redisAdminRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

output redisRoleAssignments array = [for i in range(0, length(usersOrAdGroupArray)): {
  id: userRedisRoleAssignment[i].id
  name: userRedisRoleAssignment[i].name
}]

*/

@description('Specify name of Built-In access policy to use as assignment.')
@allowed([
  'Data Owner'
  'Data Contributor'
  'Data Reader'
])
param builtInAccessPolicyName string = 'Data Contributor'

@description('Specify name of custom access policy to create.')
param builtInAccessPolicyAssignmentName string = 'builtInAccessPolicyAssignment-${uniqueString(resourceGroup().id)}'

@description('Specify the valid objectId(usually it is a GUID) of the Microsoft Entra Service Principal or Managed Identity or User Principal to which the built-in access policy would be assigned.')
param builtInAccessPolicyAssignmentObjectId string = newGuid()

@description('Specify human readable name of principal Id of the Microsoft Entra Application name or Managed Identity name used for built-in policy assignment.')
param builtInAccessPolicyAssignmentObjectAlias string = 'builtInAccessPolicyApplication-${uniqueString(resourceGroup().id)}'

@description('Specify name of custom access policy to create.')
param customAccessPolicyName string = 'customAccessPolicy-${uniqueString(resourceGroup().id)}'

@description('Specify the valid permissions for the customer access policy to create. For details refer to https://aka.ms/redis/ConfigureAccessPolicyPermissions')
param customAccessPolicyPermissions string = '+@connection +get +hget allkeys'

@description('Specify name of custom access policy to create.')
param customAccessPolicyAssignmentName string = 'customAccessPolicyAssignment-${uniqueString(resourceGroup().id)}'

@description('Specify the valid objectId(usually it is a GUID) of the Microsoft Entra Service Principal or Managed Identity or User Principal to which the custom access policy would be assigned.')
param customAccessPolicyAssignmentObjectId string = newGuid()

@description('Specify human readable name of principal Id of the Microsoft Entra Application name or Managed Identity name used for custom policy assignment.')
param customAccessPolicyAssignmentObjectAlias string = 'customAccessPolicyApplication-${uniqueString(resourceGroup().id)}'

resource redisCacheBuiltInAccessPolicyAssignment 'Microsoft.Cache/redis/accessPolicyAssignments@2023-08-01' = {
  name: builtInAccessPolicyAssignmentName
  parent: redis
  properties: {
    accessPolicyName: builtInAccessPolicyName
    objectId: builtInAccessPolicyAssignmentObjectId
    objectIdAlias: builtInAccessPolicyAssignmentObjectAlias
  }
}

resource redisCacheCustomAccessPolicy 'Microsoft.Cache/redis/accessPolicies@2023-08-01' = {
  name: customAccessPolicyName
  parent: redis
  properties: {
    permissions: customAccessPolicyPermissions
  }
  dependsOn: [
    redisCacheBuiltInAccessPolicyAssignment
  ]
}

resource redisCacheCustomAccessPolicyAssignment 'Microsoft.Cache/redis/accessPolicyAssignments@2023-08-01' = {
  name: customAccessPolicyAssignmentName
  parent: redis
  properties: {
    accessPolicyName: customAccessPolicyName
    objectId: customAccessPolicyAssignmentObjectId
    objectIdAlias: customAccessPolicyAssignmentObjectAlias
  }
  dependsOn: [
    redisCacheCustomAccessPolicy
  ]
}

