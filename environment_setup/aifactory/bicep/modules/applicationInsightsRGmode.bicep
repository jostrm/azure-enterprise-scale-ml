@description('Specifies the name of the application insight resources')
param name string

@description('Specifies the tags that should be applied to the application insights resources')
param tags object

@description('Specifies the location where application insights should be deployed')
param location string

@description('Specifies the location where application insights should be deployed')
param logAnalyticsWorkspaceID string

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: name
  tags: tags
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId:logAnalyticsWorkspaceID
    DisableIpMasking: false
    DisableLocalAuth: false
    Flow_Type: 'Bluefield'
    ForceCustomerStorageForProfiler: false
    //ImmediatePurgeDataOn30Days: true // Not available in Sweden Central. Error: ImmediatePurgeDataOn30Days cannot be set on current api-version
    IngestionMode: 'LogAnalytics' // Cannot set ApplicationInsights as IngestionMode on consolidated applications
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Disabled'
    Request_Source: 'rest'
  }
}

output ainsId string = applicationInsights.id
output name string = applicationInsights.name
