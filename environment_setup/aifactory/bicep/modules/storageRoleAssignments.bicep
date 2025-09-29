@description('Storage account name')
param storageAccountName string

@description('Principal ID of the managed identity to grant access to')
param principalId string

@description('Only create role assignments if principal ID is provided')
var shouldCreateRoles = !empty(principalId)

// Reference to existing storage account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

// Role assignment for Storage Blob Data Contributor
resource roleAssignmentBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(shouldCreateRoles) {
  name: guid(storageAccount.id, principalId, 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Role assignment for Storage Queue Data Contributor
resource roleAssignmentQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(shouldCreateRoles) {
  name: guid(storageAccount.id, principalId, '974c5e8b-45b9-4653-ba55-5f855dd0fb88')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '974c5e8b-45b9-4653-ba55-5f855dd0fb88') // Storage Queue Data Contributor
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Role assignment for Storage File Data SMB Share Contributor
resource roleAssignmentFile 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(shouldCreateRoles) {
  name: guid(storageAccount.id, principalId, '69566ab7-960f-475b-8e7c-b3118f30c6bd')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '69566ab7-960f-475b-8e7c-b3118f30c6bd') // Storage File Data SMB Share Contributor
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Also add Storage Account Contributor for general operations
resource roleAssignmentAccountContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(shouldCreateRoles) {
  name: guid(storageAccount.id, principalId, '17d1049b-9a84-46fb-8f53-869881c3d3ab')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '17d1049b-9a84-46fb-8f53-869881c3d3ab') // Storage Account Contributor
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output storageAccountId string = storageAccount.id
output assignedRoles array = [
  'Storage Blob Data Contributor'
  'Storage Queue Data Contributor' 
  'Storage File Data SMB Share Contributor'
  'Storage Account Contributor'
]
