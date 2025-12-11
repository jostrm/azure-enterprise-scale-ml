targetScope = 'resourceGroup'

@description('Name of the existing Azure AI Search service that will request the shared private link')
param aiSearchName string

@description('Resource ID of the Azure AI Foundry account that will receive the shared private link request')
param aiFoundryResourceId string

@description('Azure region for the shared private link request')
param location string

@description('Optional message included with the shared private link request')
param requestMessage string = 'Azure AI Search shared private link to Azure AI Foundry'

resource aiSearchService 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: aiSearchName
}

resource sharedPrivateLink 'Microsoft.Search/searchServices/sharedPrivateLinkResources@2025-05-01' = if (!empty(aiFoundryResourceId) && !empty(aiSearchName)) {
  name: 'shared-pe-foundry-openai'
  parent: aiSearchService
  properties: {
    privateLinkResourceId: aiFoundryResourceId
    groupId: 'openai_account'
    requestMessage: requestMessage
    resourceRegion: location
  }
}
resource sharedPrivateLink2 'Microsoft.Search/searchServices/sharedPrivateLinkResources@2025-05-01' = if (!empty(aiFoundryResourceId) && !empty(aiSearchName)) {
  name: 'shared-pe-foundry-cogsvc'
  parent: aiSearchService
  properties: {
    privateLinkResourceId: aiFoundryResourceId
    groupId: 'cognitiveservices_account'
    requestMessage: requestMessage
    resourceRegion: location
  }
  dependsOn: [
    sharedPrivateLink
  ]
}


output sharedPrivateLinkName string = !empty(aiFoundryResourceId) && !empty(aiSearchName) ? sharedPrivateLink.name : ''
output sharedPrivateLinkName2 string = !empty(aiFoundryResourceId) && !empty(aiSearchName) ? sharedPrivateLink2.name : ''
