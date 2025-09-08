param aiSearchName string // Resource ID for Azure AI Search
param userObjectIds array // Specific user's object ID's
param servicePrincipleAndMIArray array // Service Principle Object ID, User created MAnaged Identity
param useAdGroups bool = false // Use AD Groups instead of Users for RBAC assignments

resource existingAiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' existing = if(!empty(aiSearchName)) {
  name: aiSearchName
}

// Search
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // User, SP, AI Services, etc -> AI Search
//Lets you manage Search services, but not access to them.
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // SP, User, Search, AIHub, AIProject, App Service/FunctionApp -> AI Search
var azureAIDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee' // Azure AI Developer - CRITICAL for Chat with data


// --------------- SEARCH ---------------- //

@description('Role Assignment for Azure AI Search: SearchIndexDataContributor for users. 	Grants full access to Azure Cognitive Search index data')
resource searchIndexDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):if(!empty(aiSearchName)){
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'020: SearchIndexUserDataContributor to USER with OID  ${userObjectIds[i]} for : ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]
resource searchIndexDataReaderAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):if(!empty(aiSearchName)){
  name: guid(existingAiSearch.id, searchIndexDataReader, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReader)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'021: searchIndexDataReader to USER with OID  ${userObjectIds[i]} for : ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]

resource searchIndexDataContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)):if(!empty(aiSearchName)){
  name: guid(existingAiSearch.id, searchIndexDataContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'searchIndexDataContributorRoleId to project service principal OID: ${servicePrincipleAndMIArray[i]} to ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]

@description('Role Assignment for Azure AI Search: Search Service Contributor for users. Lets you manage Search services, but not access to them.')
resource searchServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):if(!empty(aiSearchName)){
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'022: CONTRIBUTOR to USER with OID  ${userObjectIds[i]} for : ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]

@description('Role Assignment for Azure AI Search: Azure AI Developer for users. CRITICAL for Chat with data scenarios.')
resource azureAIDeveloperUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):if(!empty(aiSearchName)){
  name: guid(existingAiSearch.id, azureAIDeveloperRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'023: Azure AI Developer to USER with OID  ${userObjectIds[i]} for : ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]

resource searchServiceContributorSP 'Microsoft.Authorization/roleAssignments@2022-04-01'  = [for i in range(0, length(servicePrincipleAndMIArray)):if(!empty(aiSearchName)){
  name: guid(existingAiSearch.id, searchServiceContributorRoleId, servicePrincipleAndMIArray[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'searchServiceContributorRoleId to project service principal OID:${servicePrincipleAndMIArray[i]} to ${existingAiSearch.name}'
  }
  scope:existingAiSearch
}]
