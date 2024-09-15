param name string 
param logAnalyticsWorkspaceOpInsightResourceId string

resource azureOpenAIRef 'Microsoft.CognitiveServices/accounts@2022-03-01' existing = {
  name: name
}

resource openAIDiagSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${name}-diagnosticSettings'
  scope: azureOpenAIRef
  properties: {
    workspaceId: logAnalyticsWorkspaceOpInsightResourceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
    logAnalyticsDestinationType: null
  }
}
