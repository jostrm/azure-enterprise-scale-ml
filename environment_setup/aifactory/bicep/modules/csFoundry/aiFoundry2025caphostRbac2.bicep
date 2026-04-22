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
@description('Name of the AI Search service for vector store data plane access')
param aiSearchName string = ''
@description('RBAC level for AI Search index data access: contributor (read+write) or reader (read-only)')
@allowed(['contributor', 'reader'])
param searchRbacLevel string = 'contributor'

// Reference existing storage account
resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
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
  name: guid(storageBlobDataOwner.id, storage.id, projectPrincipalId, projectWorkspaceId)
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: storageBlobDataOwner.id
    principalType: 'ServicePrincipal'
    conditionVersion: '2.0'
    condition: conditionStr
  }
}

// ============== AI SEARCH: Search Index Data access for Capability Host vector store ==============
// The capability host uses the project MI to access indexes in AI Search (vector store connection).
// 'contributor' grants read + write (for File Search ingestion), 'reader' grants read-only.

resource aiSearchService 'Microsoft.Search/searchServices@2023-11-01' existing = if (!empty(aiSearchName)) {
  name: aiSearchName
}

var searchIndexDataContributorRoleId_caphost = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchIndexDataReaderRoleId_caphost = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchRoleId = searchRbacLevel == 'contributor' ? searchIndexDataContributorRoleId_caphost : searchIndexDataReaderRoleId_caphost

resource caphostSearchIndexDataAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiSearchName)) {
  name: guid(aiSearchService.id, projectPrincipalId, searchRoleId, 'caphost')
  scope: aiSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}
