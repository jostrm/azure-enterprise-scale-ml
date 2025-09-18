// Helper module to get Application Insights information
targetScope = 'resourceGroup'

@description('Application Insights name')
param appInsightsName string

// Reference existing Application Insights resource
resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

// Outputs - these will be available since the resource exists
@description('Application Insights instrumentation key')
output instrumentationKey string = applicationInsights.properties.InstrumentationKey

@description('Application Insights connection string')
output connectionString string = applicationInsights.properties.ConnectionString

@description('Application Insights resource ID')
output resourceId string = applicationInsights.id

@description('Application Insights name')
output name string = applicationInsights.name

@description('Application Insights app ID')
output appId string = applicationInsights.properties.AppId

// Modern outputs for Logic Apps integration
@description('Application Insights workspace ID (for Log Analytics integration)')
output workspaceResourceId string = applicationInsights.properties.WorkspaceResourceId

@description('Direct resource reference (most modern approach)')
output resourceReference object = {
  id: applicationInsights.id
  name: applicationInsights.name
  instrumentationKey: applicationInsights.properties.InstrumentationKey
  connectionString: applicationInsights.properties.ConnectionString
}
