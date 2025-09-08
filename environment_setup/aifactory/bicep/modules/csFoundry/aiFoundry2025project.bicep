@minLength(3)
@maxLength(12)
@description('The name of the environment. Use alphanumeric characters only.')
param name string

@description('Specifies the location for all the Azure resources. Defaults to the location of the resource group.')
param location string

@description('Name of the customers existing CosmosDB Resource')
param cosmosDBname string 

@description('Name of the customers existing Azure Storage Account')
param storageName string

@description('Foundry Account Name')
param aiFoundryV2Name string

@description('Azure Search Service Name')
param aiSearchName string

@description('Name of the first project')
param defaultProjectName string = name
param defaultProjectDisplayName string = name
param defaultProjectDescription string = 'AI Factory created this default project for AI Foundry with enterprise grade security and your corp networking.'

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: aiFoundryV2Name
  }

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageName
}

resource aiSearchService 'Microsoft.Search/searchServices@2024-06-01-preview' existing =  if (!empty(aiSearchName)) {
  name: aiSearchName
}

resource cosmosDBAccount 'Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview' existing = if (!empty(cosmosDBname)) {
  name: cosmosDBname
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  name: defaultProjectName
  parent: foundryAccount
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: defaultProjectDisplayName
    description: defaultProjectDescription
  }
}

resource project_connection_azure_storage 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  name: storageName
  parent: project
  properties: {
    category: 'AzureBlob'
    target: storageAccount.properties.primaryEndpoints.blob
    // target: storageAccountTarget
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: storageAccount.id
      location: storageAccount.location
      accountName: storageAccount.name
      containerName: '${name}proj'
    }
  }
}

resource project_connection_azureai_search 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = if (!empty(aiSearchName)) {
  name: aiSearchService.name
  parent: project
  properties: {
    category: 'CognitiveSearch'
    target: 'https://${aiSearchService.name}.search.windows.net/'
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: aiSearchService.id
      #disable-next-line BCP318
      location: aiSearchService.location
    }
  }
}

resource project_connection_cosmosdb 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = if  (!empty(cosmosDBname)) {
  name: cosmosDBname
  parent: project
  properties: {
    category: 'CosmosDB'
    #disable-next-line BCP318
    target: cosmosDBAccount.properties.documentEndpoint
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: cosmosDBAccount.id
      #disable-next-line BCP318
      location: cosmosDBAccount.location
    }
  }
}

output projectId string = project.id
output projectName string = project.name
output projectPrincipalId string = project.identity.principalId
#disable-next-line BCP053
output projectWorkspaceId string = project.properties.internalId
// return the BYO connection names
output cosmosDBConnection string = cosmosDBname
output azureStorageConnection string = storageName
output aiSearchConnection string = aiSearchName
