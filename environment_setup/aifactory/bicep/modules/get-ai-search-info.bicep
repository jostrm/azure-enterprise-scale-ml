// ================================================================
// GET AI SEARCH INFO MODULE
// This module retrieves information about an existing AI Search service
// including its system-assigned managed identity principal ID
// ================================================================

@description('The name of the AI Search service')
param aiSearchName string

// Reference the existing AI Search service
resource aiSearchService 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: aiSearchName
}

@description('The principal ID of the AI Search service system-assigned managed identity')
output principalId string = aiSearchService.identity.principalId

@description('The resource ID of the AI Search service')
output resourceId string = aiSearchService.id

@description('The name of the AI Search service')
output name string = aiSearchService.name
