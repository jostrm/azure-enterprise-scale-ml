@description('Specifies the name of the application insight resources')
param name string

@description('Specifies the tags that should be applied to the application insights resources')
param tags object

@description('Specifies the location where application insights should be deployed')
param location string

param logWorkspaceName string
param logWorkspaceNameRG string
param enablePublicAccessWithPerimeter bool = false
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: logWorkspaceName
  scope:resourceGroup(logWorkspaceNameRG)
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: name
  tags: tags
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId:logAnalyticsWorkspace.id
    //DisableIpMasking: false  // tomten
    //DisableLocalAuth: false  // tomten
    //Flow_Type: 'Bluefield' // todo1
    //ForceCustomerStorageForProfiler: false  // tomten
    //ImmediatePurgeDataOn30Days: true // Not available in Sweden Central. Error: ImmediatePurgeDataOn30Days cannot be set on current api-version
    //IngestionMode: 'LogAnalytics' // Cannot set ApplicationInsights as IngestionMode on consolidated applications // tomten
    // publicNetworkAccessForIngestion: 'Enabled' // tomten
    // publicNetworkAccessForQuery: 'Disabled' // tomtem
    // Request_Source: 'rest' // tomten
  }
}

output ainsId string = applicationInsights.id
output name string = applicationInsights.name
