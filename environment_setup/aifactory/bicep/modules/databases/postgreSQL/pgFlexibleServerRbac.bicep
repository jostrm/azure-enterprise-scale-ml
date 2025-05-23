metadata description = 'Creates role assignments for PostgreSQL Flexible Server.'
param usersOrAdGroupArray array
param servicePrincipleAndMIArray array
param postgreSqlServerName string
param useAdGroups bool
param resourceCreatedNow bool = false

var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // Contributor
var postgreSqlReaderRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'       // Reader role
var postgreSqlContributorRoleId = 'a9f2b5d7-5c0c-4d8e-bd6f-3f9c0f9d5f9b' // PostgreSQL DB Contributor

resource postgreSqlServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = {
  name: postgreSqlServerName
}
resource userPostgreSqlRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in usersOrAdGroupArray: {
  name: guid(postgreSqlServer.id, contributorRoleId, principalId)
  scope: postgreSqlServer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: principalId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

resource spPostgreSqlRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in servicePrincipleAndMIArray:{
  name: guid(postgreSqlServer.id, contributorRoleId, principalId) // Updated to use Admin role
  scope: postgreSqlServer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId) // Updated to use Admin role
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]
