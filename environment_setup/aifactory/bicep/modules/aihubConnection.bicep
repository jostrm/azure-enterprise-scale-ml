param aiHubName string
@description('Resource ID of the AI Services  endpoint')
param targetAIServicesEndpoint string
@description('Resource ID of the AI Services resource')
param targetAIServiceResourceId string
param parentAIHubResourceId string 
param apiVersion string = '2024-08-01-preview'
param category string = 'AIServices' // 'AIServices', 'CognitiveSearch'

resource parentAMLWorkspaceAIHubObject 'Microsoft.MachineLearningServices/workspaces@2024-07-01-preview' existing = {
  name: aiHubName // TODO - check if this is correct? NAME instead of ID? 
}

resource aiServicesConnection 'Microsoft.MachineLearningServices/workspaces/connections@2024-07-01-preview' = {
  name: 'connectionAIServicesToHub' // name: '${aiHubName}/${connectionAIServicesToHub}' and no parent
  parent: parentAMLWorkspaceAIHubObject
  properties: {
    category: category
    target: targetAIServicesEndpoint
    //useWorkspaceManagedIdentity: true
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
    peRequirement: 'Required'
    peStatus: 'Active'
  }
}

