param functionPrincipalId string
param storageAccountName string
param storageAccountName2 string = ''
param aiSearchName string = ''
param openAIName string = ''

// Get resource references
resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: storageAccountName
}

resource storageAccount2 'Microsoft.Storage/storageAccounts@2022-09-01' existing = if (!empty(storageAccountName2)) {
  name: storageAccountName2
}

resource aiSearch 'Microsoft.Search/searchServices@2022-09-01' existing = if (!empty(aiSearchName)) {
  name: aiSearchName
}

resource openAI 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = if (!empty(openAIName)) {
  name: openAIName
}

// Grant Storage Blob Data Contributor role to Function App on storage accounts
resource storageBlobDataContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionPrincipalId, 'storageBlobDataContributor')
  scope: storageAccount
  properties: {
    principalId: functionPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
    principalType: 'ServicePrincipal'
  }
}

resource storageBlobDataContributorRoleAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(storageAccountName2)) {
  name: guid(storageAccount2.id, functionPrincipalId, 'storageBlobDataContributor')
  scope: storageAccount2
  properties: {
    principalId: functionPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
    principalType: 'ServicePrincipal'
  }
}

// Grant Cognitive Services User role to Function App on OpenAI resource
resource openAIUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(openAIName)) {
  name: guid(openAI.id, functionPrincipalId, 'cognitiveServicesUser')
  scope: openAI
  properties: {
    principalId: functionPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908') // Cognitive Services User
    principalType: 'ServicePrincipal'
  }
}

// Grant Search Index Data Contributor role to Function App on AI Search
resource searchIndexDataContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiSearchName)) {
  name: guid(aiSearch.id, functionPrincipalId, 'searchIndexDataContributor')
  scope: aiSearch
  properties: {
    principalId: functionPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7') // Search Index Data Contributor
    principalType: 'ServicePrincipal'
  }
}

resource searchServiceContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiSearchName)) {
  name: guid(aiSearch.id, functionPrincipalId, 'searchServiceContributor')
  scope: aiSearch
  properties: {
    principalId: functionPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0') // Search Service Contributor
    principalType: 'ServicePrincipal'
  }
}
