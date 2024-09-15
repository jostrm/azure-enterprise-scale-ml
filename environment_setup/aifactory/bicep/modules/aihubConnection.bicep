param aiHubName string
@description('Resource ID of the AI Services  endpoint')
param targetAIServicesEndpoint string
@description('Resource ID of the AI Services resource')
param targetAIServiceResourceId string
param parentAIHubResourceId string 
param apiVersion string = '2024-08-01-preview'

resource parentAMLWorkspaceAIHubObject 'Microsoft.MachineLearningServices/workspaces@2024-07-01-preview' existing = {
  name: parentAIHubResourceId
}

resource aiServicesConnection 'Microsoft.MachineLearningServices/workspaces/connections@2024-01-01-preview' = {
  name: '${aiHubName}-connection-AIServices'
  parent: parentAMLWorkspaceAIHubObject
  properties: {
    category: 'AIServices'
    target: targetAIServicesEndpoint
    isSharedToAll: true
    authType: 'AAD'
    //authType: 'ApiKey'
    //credentials: {
    //  key: '${listKeys(targetOpenAIServiceResourceId, apiVersion).key1}'
    //}
    metadata: {
      ApiType: 'Azure'
      ResourceId: targetAIServiceResourceId
    }
  }
}

