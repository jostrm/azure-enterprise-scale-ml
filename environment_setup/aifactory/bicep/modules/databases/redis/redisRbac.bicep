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
var contributorId = 'fcfef8a3-163d-4692-937a-460c785b8fdb'        // Contributor role

resource redis 'Microsoft.Cache/redis@2023-08-01' existing = {
  name: redisName
}

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
