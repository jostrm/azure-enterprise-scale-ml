@description('Specifies the name of the application insight resources')
param name string

@description('Specifies the tags that should be applied to the application insights resources')
param tags object

@description('Specifies the location where application insights should be deployed')
param location string

resource applicationInsights 'Microsoft.Insights/components@2020-02-02-preview' = {
  name: name
  tags: tags
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    DisableIpMasking: false
    DisableLocalAuth: false
    Flow_Type: 'Bluefield'
    ForceCustomerStorageForProfiler: false
    ImmediatePurgeDataOn30Days: true
    IngestionMode: 'ApplicationInsights'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Disabled'
    Request_Source: 'rest'
  }
}

output ainsId string = applicationInsights.id
