// Assigns Role Cosmos DB Operator to the Project Principal ID
@description('Name of the CosmosDB Account resource')
param cosmosAccountName string
@description('Name of the CosmosDB SQL Database in the account')
param cosmosSQLDBName string = 'enterprise_memory'
@description('Principal ID of the AI project')
param projectPrincipalId string
@description('Name of the storage account')
param storageName string
@description('Workspace Id of the AI Project')
param projectWorkspaceId string

// Reference existing storage account
resource storage 'Microsoft.Storage/storageAccounts@2022-05-01' existing = {
  name: storageName
  scope: resourceGroup()
}

// Storage Blob Data Owner Role
resource storageBlobDataOwner 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'  // Built-in role ID
  scope: resourceGroup()
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-12-01-preview' existing = {
  name: cosmosAccountName
  scope: resourceGroup()
}

var userThreadName = '${projectWorkspaceId}-thread-message-store'
var systemThreadName = '${projectWorkspaceId}-system-thread-message-store'
var entityStoreName = '${projectWorkspaceId}-agent-entity-store'

// Reference existing database
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-12-01-preview' existing = {
  parent: cosmosAccount
  name: cosmosSQLDBName
}

resource containerUserMessageStore  'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' existing = {
  parent: database
  name: userThreadName
}

#disable-next-line BCP081
resource containerSystemMessageStore 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' existing = {
  parent: database
  name: systemThreadName
}

#disable-next-line BCP081
resource containerEntityStore 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-12-01-preview' existing = {
  parent: database
  name: entityStoreName
}


var roleDefinitionId = resourceId(
  'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions', 
  cosmosAccountName, 
  '00000000-0000-0000-0000-000000000002'
)

var scopeSystemContainer = '/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroup().name}/providers/Microsoft.DocumentDB/databaseAccounts/${cosmosAccountName}/dbs/enterprise_memory/colls/${systemThreadName}'
var scopeUserContainer = '/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroup().name}/providers/Microsoft.DocumentDB/databaseAccounts/${cosmosAccountName}/dbs/enterprise_memory/colls/${userThreadName}'
var scopeEntityContainer = '/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroup().name}/providers/Microsoft.DocumentDB/databaseAccounts/${cosmosAccountName}/dbs/enterprise_memory/colls/${entityStoreName}'

resource containerRoleAssignmentUserContainer 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2022-05-15' = {
  parent: cosmosAccount
  name: guid(projectWorkspaceId, containerUserMessageStore.id, roleDefinitionId, projectPrincipalId)
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: roleDefinitionId
    scope: scopeUserContainer
  }
}

resource containerRoleAssignmentSystemContainer 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2022-05-15' = {
  parent: cosmosAccount
  name: guid(projectWorkspaceId, containerSystemMessageStore.id, roleDefinitionId, projectPrincipalId)
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: roleDefinitionId
    scope: scopeSystemContainer
  }
}
  
  resource containerRoleAssignmentEntityContainer 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2022-05-15' = {
    parent: cosmosAccount
    name: guid(projectWorkspaceId, containerEntityStore.id, roleDefinitionId, projectPrincipalId)
    properties: {
      principalId: projectPrincipalId
      roleDefinitionId: roleDefinitionId
      scope: scopeEntityContainer
    }
  }

// Storage
var conditionStr= '((!(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read\'})  AND  !(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/filter/action\'}) AND  !(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/write\'}) ) OR (@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringStartsWithIgnoreCase \'${projectWorkspaceId}\' AND @Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringLikeIgnoreCase \'*-azureml-agent\'))'

// Assign Storage Blob Data Owner role
resource storageBlobDataOwnerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storageBlobDataOwner.id, storage.id)
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: storageBlobDataOwner.id
    principalType: 'ServicePrincipal'
    conditionVersion: '2.0'
    condition: conditionStr
  }
}
