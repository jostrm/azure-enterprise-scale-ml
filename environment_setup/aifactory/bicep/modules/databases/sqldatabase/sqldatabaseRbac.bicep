metadata description = 'Creates role assignments for Azure SQL Server and SQL Database.'
param usersOrAdGroupArray array
param servicePrincipleAndMIArray array
param sqlServerName string
param useAdGroups bool
param contributorRoleId string = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

// Azure SQL built-in roles
// https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles

//SQL DB Contributor: Lets you manage SQL databases, but not access to them. Also, you can't manage their security-related policies or their parent SQL servers.
var sqlContributorRoleId = '9b7fa17d-e63e-47b0-bb0a-15c516ac86ec' // SQL DB Contributor
var sqlDatabaseAdminRoleId = 'dbaa88c4-8eeb-4f5a-9e09-3c5b2e2f7ef5' // Database Administrator (placeholder, update if needed)

var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'       // Reader role
var contributorId = contributorRoleId        // Contributor role

resource sqlServer 'Microsoft.Sql/servers@2022-05-01-preview' existing = {
  name: sqlServerName
}

// Contributor: Role assignments for users or AD groups
resource userSqlRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in usersOrAdGroupArray: {
  name: guid(sqlServer.id, contributorId, principalId)
  scope: sqlServer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorId)
    principalId: principalId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

// Admin: Role assignments for service principals and managed identities
resource spSqlRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in servicePrincipleAndMIArray: {
  name: guid(sqlServer.id, contributorId, principalId)
  scope: sqlServer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

output sqlRoleAssignments array = [for i in range(0, length(usersOrAdGroupArray)): {
  id: userSqlRoleAssignment[i].id
  name: userSqlRoleAssignment[i].name
}]
