param webAppPrincipalId string
param storageAccountName string
param storageAccountName2 string
param aiSearchName string = ''
param openAIName string = ''
param aiServicesName string = ''

// Get resource references
resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: storageAccountName
}

resource storageAccount2 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: storageAccountName2
}

resource aiSearch 'Microsoft.Search/searchServices@2022-09-01' existing = if (!empty(aiSearchName)) {
  name: aiSearchName
}

resource openAI 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = if (!empty(openAIName)) {
  name: openAIName
}
resource aiServices 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = if (!empty(aiServicesName)) {
  name: aiServicesName
}

// Grant Storage Blob Data Reader role to WebApp on storage accounts
resource storageBlobDataReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, webAppPrincipalId, 'storageBlobDataReader')
  scope: storageAccount
  properties: {
    principalId: webAppPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1') // Storage Blob Data Reader
    principalType: 'ServicePrincipal'
  }
}

resource storageBlobDataReaderRoleAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount2.id, webAppPrincipalId, 'storageBlobDataReader')
  scope: storageAccount2
  properties: {
    principalId: webAppPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1') // Storage Blob Data Reader
    principalType: 'ServicePrincipal'
  }
}

// Grant Cognitive Services User role to WebApp on OpenAI resource
resource openAIUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(openAIName)) {
  name: guid(openAI.id, webAppPrincipalId, 'cognitiveServicesUser')
  scope: openAI
  properties: {
    principalId: webAppPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908') // Cognitive Services User
    principalType: 'ServicePrincipal'
  }
}
resource aiServicesUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiServicesName)) {
  name: guid(aiServices.id, webAppPrincipalId, 'cognitiveServicesUser')
  scope: aiServices
  properties: {
    principalId: webAppPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908') // Cognitive Services User
    principalType: 'ServicePrincipal'
  }
}

// Grant Search Index Data Reader role to WebApp on AI Search
resource searchIndexDataReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiSearchName)) {
  name: guid(aiSearch.id, webAppPrincipalId, 'searchIndexDataReader')
  scope: aiSearch
  properties: {
    principalId: webAppPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f') // Search Index Data Reader
    principalType: 'ServicePrincipal'
  }
}

resource searchServiceContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiSearchName)) {
  name: guid(aiSearch.id, webAppPrincipalId, 'searchServiceContributor')
  scope: aiSearch
  properties: {
    principalId: webAppPrincipalId
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0') // Search Service Contributor
    principalType: 'ServicePrincipal'
  }
}
