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
param storageName2 string

@description('Foundry Account Name')
param aiFoundryV2Name string

@description('Azure Search Service Name')
param aiSearchName string
param enablePublicAccessWithPerimeter bool = false

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
resource storageAccount2 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageName2
}

resource aiSearchService 'Microsoft.Search/searchServices@2024-06-01-preview' existing =  if (!empty(aiSearchName)) {
  name: aiSearchName
}

resource cosmosDBAccount 'Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview' existing = if (!empty(cosmosDBname)) {
  name: cosmosDBname
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-07-01-preview' = {
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

resource project_connection_azure_storage 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' = {
  name: storageName
  parent: project
  properties: {
    category: 'AzureStorageAccount'
    target: storageAccount.properties.primaryEndpoints.blob
    useWorkspaceManagedIdentity: true
    peRequirement: enablePublicAccessWithPerimeter?'NotRequired':'Required'
    peStatus: enablePublicAccessWithPerimeter? 'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: storageAccount.id
      location: storageAccount.location
      accountName: storageAccount.name
      //containerName: 'default'
    }
  }
  dependsOn:[
    project
  ]
}
resource project_connection_azure_storage2 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' = {
  name: storageName2
  parent: project
  properties: {
    category: 'AzureStorageAccount'
    // target: storageAccountTarget
    //category: 'AzureStorageAccount'
    target: storageAccount2.properties.primaryEndpoints.blob
    useWorkspaceManagedIdentity: true
    peRequirement: enablePublicAccessWithPerimeter?'NotRequired':'Required'
    peStatus: enablePublicAccessWithPerimeter? 'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: storageAccount2.id
      location: storageAccount2.location
      accountName: storageAccount2.name
      containerName: 'default'
    }
  }
  dependsOn:[
    project_connection_azure_storage
  ]
}

resource project_connection_azureai_search 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' = if (!empty(aiSearchName)) {
  name: aiSearchService.name
  parent: project
  properties: {
    category: 'CognitiveSearch'
    target: 'https://${aiSearchService.name}.search.windows.net/'
    authType: 'AAD'
    isSharedToAll: true
    useWorkspaceManagedIdentity: true
    peRequirement: enablePublicAccessWithPerimeter?'NotRequired':'Required'
    peStatus: enablePublicAccessWithPerimeter? 'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
    metadata: {
      ApiType: 'Azure'
      ResourceId: aiSearchService.id
      #disable-next-line BCP318
      location: aiSearchService.location
    }
  }
  dependsOn:[
    project_connection_azure_storage2
  ]
}

resource project_connection_cosmosdb 'Microsoft.CognitiveServices/accounts/projects/connections@2025-07-01-preview' = if  (!empty(cosmosDBname)) {
  name: cosmosDBname
  parent: project
  properties: {
    category: 'CosmosDB'
    #disable-next-line BCP318
    target: cosmosDBAccount.properties.documentEndpoint
    authType: 'AAD'
    isSharedToAll: true
    useWorkspaceManagedIdentity: true
    peRequirement: enablePublicAccessWithPerimeter?'NotRequired':'Required'
    peStatus: enablePublicAccessWithPerimeter? 'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
    metadata: {
      ApiType: 'Azure'
      ResourceId: cosmosDBAccount.id
      #disable-next-line BCP318
      location: cosmosDBAccount.location
    }
  }
  dependsOn:[
    project_connection_azureai_search
  ]
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
