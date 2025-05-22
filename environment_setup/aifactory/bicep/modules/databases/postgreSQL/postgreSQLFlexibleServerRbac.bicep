metadata description = 'Creates role assignments for PostgreSQL Flexible Server.'
param usersOrAdGroupArray array
param servicePrincipleAndMIArray array
param postgreSqlServerName string
param useAdGroups bool
param resourceCreatedNow bool = false

// PostgreSQL Flexible Server built-in roles
// https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles

/* Roles: Database-level (PostgreSQL Flexible Server native roles)
azure_pg_admin: This is the default administrative role created when the server is provisioned. 
It has elevated privileges but is restricted from certain operations like creating other superusers.
*/

var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // Contributor
var postgreSqlReaderRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'       // Reader role
var postgreSqlContributorRoleId = 'a9f2b5d7-5c0c-4d8e-bd6f-3f9c0f9d5f9b' // PostgreSQL DB Contributor

resource postgreSqlServer 'Microsoft.DBforPostgreSQL/flexibleServers@2025-01-01-preview' existing = {
//resource postgreSqlServer 'Microsoft.DBforPostgreSQL/flexibleServers@2025-01-01-preview' existing = if(resourceCreatedNow) {
  name: postgreSqlServerName
}

// Role assignments for users or AD groups
@onlyIfNotExists()
resource userPostgreSqlRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in usersOrAdGroupArray: {
//resource userPostgreSqlRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in usersOrAdGroupArray:  if(resourceCreatedNow) {
  name: guid(postgreSqlServer.id, contributorRoleId, principalId)
  scope: postgreSqlServer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: principalId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

// Role assignments for service principals and managed identities
/*
Service Principals cannot generate AAD_AUTH_TOKENTYPE_APP_USER tokens for role-based access 1. 
This means managed identities or service principals may not be suitable for direct database login unless explicitly supported.
*/
@onlyIfNotExists()
resource spPostgreSqlRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in servicePrincipleAndMIArray:{
//resource spPostgreSqlRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in servicePrincipleAndMIArray:  if(resourceCreatedNow) {
  name: guid(postgreSqlServer.id, contributorRoleId, principalId) // Updated to use Admin role
  scope: postgreSqlServer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId) // Updated to use Admin role
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

/*
output postgreSqlRoleAssignments array = [for i in range(0, length(usersOrAdGroupArray)): {
  id: resourceCreatedNow? userPostgreSqlRoleAssignment[i].id: ''
  name:resourceCreatedNow? userPostgreSqlRoleAssignment[i].name: ''
}]

*/
