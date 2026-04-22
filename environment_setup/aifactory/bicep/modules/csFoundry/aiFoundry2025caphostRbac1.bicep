// Assigns Role Cosmos DB Operator to the Project Principal ID
@description('Name of the CosmosDB Account resource')
param cosmosAccountName string
@description('Name of the CosmosDB SQL Database in the account')
param cosmosSQLDBName string = 'enterprise_memory'

@description('Principal ID of the AI project')
param projectPrincipalId string

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-12-01-preview' existing = {
  name: cosmosAccountName
  scope: resourceGroup()
}

resource cosmosDBOperatorRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '230815da-be43-4aae-9cb4-875f7bd000aa'
  scope: resourceGroup()
}

resource cosmosDBOperatorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cosmosAccount
  name: guid(projectPrincipalId, cosmosDBOperatorRole.id, cosmosAccount.id)
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: cosmosDBOperatorRole.id
    principalType: 'ServicePrincipal'
  }
}

// Cosmos DB Built-in Data Reader (account-level) – grants readMetadata on the account, 
// required by AI Foundry project MI to load agents (prevents 403 on readMetadata).
var cosmosDataReaderRoleDefinitionId = resourceId(
  'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions',
  cosmosAccountName,
  '00000000-0000-0000-0000-000000000001' // Cosmos DB Built-in Data Reader
)

resource cosmosDataReaderRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-12-01-preview' = {
  parent: cosmosAccount
  name: guid(projectPrincipalId, cosmosDataReaderRoleDefinitionId, cosmosAccount.id)
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: cosmosDataReaderRoleDefinitionId
    scope: cosmosAccount.id
  }
}
