metadata description = 'Creates a role assignment for a service principal.'
param usersOrAdGroupArray array
param servicePrincipleAndMIArray array
param cosmosName string

var roleDefinitionReader = '00000000-0000-0000-0000-000000000001' // Cosmos DB Built-in Data Reader
var roleDefinitionContributor = '00000000-0000-0000-0000-000000000002' // Cosmos DB Built-in Data Contributor

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-12-01-preview' existing = {
  name: cosmosName
}

// Role assignments for users or AD groups
// We need batchSize(1) here because sql role assignments have to be done sequentially
@batchSize(1)
resource userSqlRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [for principalId in usersOrAdGroupArray: {
  name: guid(cosmos.id, roleDefinitionContributor, principalId)
  parent: cosmos
  properties:{
    principalId: principalId
    roleDefinitionId:'${cosmos.id}/sqlRoleDefinitions/${roleDefinitionContributor}'
    scope: cosmos.id
  }
}]

// Role assignments for service principals and managed identities
// We need batchSize(1) here because sql role assignments have to be done sequentially
@batchSize(1)
resource spSqlRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [for principalId in servicePrincipleAndMIArray: {
  name: guid(cosmos.id, roleDefinitionContributor, principalId)
  parent: cosmos
  properties:{
    principalId: principalId
    roleDefinitionId:  '${cosmos.id}/sqlRoleDefinitions/${roleDefinitionContributor}'
    scope: cosmos.id
  }
}]


