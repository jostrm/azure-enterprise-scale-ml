param aiHubName string
@description('Resource ID of the AI Services endpoint')
param targetOpenAIServiceEndpointId string
@description('Resource ID of the AI Services resource')
param targetOpenAIServiceResourceId string
param parentAIHubResourceId string 

resource parentAMLWorkspaceAIHubObject 'Microsoft.MachineLearningServices/workspaces@2024-07-01-preview' existing = {
  name: parentAIHubResourceId
}

resource aiServicesConnection 'Microsoft.MachineLearningServices/workspaces/connections@2024-01-01-preview' = {
  name: '${aiHubName}-connection-AIServices'
  parent: parentAMLWorkspaceAIHubObject
  properties: {
    category: 'AIServices'
    target: targetOpenAIServiceEndpointId
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: '${listKeys(targetOpenAIServiceResourceId, '2021-10-01').key1}'
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: targetOpenAIServiceResourceId
    }
  }
}

