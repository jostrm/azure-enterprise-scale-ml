// ============================================================================
// Azure Monitor Private Link Scope (AMPLS) Module
// ============================================================================
// This module creates an Azure Monitor Private Link Scope for secure monitoring
// in a hub/spoke network architecture

@description('Name of the Azure Monitor Private Link Scope')
param amplsName string

@description('Location for the AMPLS resource')
param location string

@description('Tags to apply to the AMPLS resource')
param tags object = {}

@description('Access mode for ingestion - controls how data can be ingested')
@allowed(['Open', 'PrivateOnly'])
param ingestionAccessMode string = 'PrivateOnly'

@description('Access mode for query - controls how data can be queried')
@allowed(['Open', 'PrivateOnly'])
param queryAccessMode string = 'PrivateOnly'

@description('Array of Log Analytics workspaces to connect to AMPLS')
param logAnalyticsWorkspaces array = []

@description('Array of Application Insights components to connect to AMPLS')
param applicationInsightsComponents array = []

@description('Array of Data Collection Endpoints to connect to AMPLS')
param dataCollectionEndpoints array = []

@description('Enable network isolation for maximum security')
param enableNetworkIsolation bool = true

// Create the Azure Monitor Private Link Scope
resource ampls 'microsoft.insights/privateLinkScopes@2021-07-01-preview' = {
  name: amplsName
  location: location
  tags: tags
  properties: {
    accessModeSettings: {
      ingestionAccessMode: ingestionAccessMode
      queryAccessMode: queryAccessMode
    }
  }
}

// Connect Log Analytics Workspaces to AMPLS
resource logAnalyticsConnections 'microsoft.insights/privateLinkScopes/scopedResources@2021-07-01-preview' = [for (workspace, index) in logAnalyticsWorkspaces: {
  name: 'law-${index}'
  parent: ampls
  properties: {
    linkedResourceId: workspace.id
  }
}]

// Connect Application Insights Components to AMPLS
resource applicationInsightsConnections 'microsoft.insights/privateLinkScopes/scopedResources@2021-07-01-preview' = [for (appInsights, index) in applicationInsightsComponents: {
  name: 'ai-${index}'
  parent: ampls
  properties: {
    linkedResourceId: appInsights.id
  }
}]

// Connect Data Collection Endpoints to AMPLS
resource dataCollectionEndpointConnections 'microsoft.insights/privateLinkScopes/scopedResources@2021-07-01-preview' = [for (dce, index) in dataCollectionEndpoints: {
  name: 'dce-${index}'
  parent: ampls
  properties: {
    linkedResourceId: dce.id
  }
}]

// Outputs
output amplsId string = ampls.id
output amplsName string = ampls.name
output amplsResourceId string = ampls.id
output ingestionAccessMode string = ampls.properties.accessModeSettings.ingestionAccessMode
output queryAccessMode string = ampls.properties.accessModeSettings.queryAccessMode
