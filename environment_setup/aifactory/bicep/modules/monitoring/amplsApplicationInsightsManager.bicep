// ============================================================================
// AMPLS Application Insights Management Module
// ============================================================================
// This module handles adding Application Insights to AMPLS while preserving existing ones
// Uses a parameter-based approach to manage existing resources

@description('Name of the Azure Monitor Private Link Scope')
param amplsName string

@description('Location for resources')
param location string

@description('Tags to apply to resources')
param tags object = {}

@description('New Application Insights resource ID to add')
param newApplicationInsightsId string

@description('Array of existing Application Insights resource IDs already in AMPLS')
param existingApplicationInsightsIds array = []

@description('Array of existing Log Analytics Workspaces resource IDs already in AMPLS')
param existingLogAnalyticsWorkspaceIds array = []

@description('Array of existing Data Collection Endpoints resource IDs already in AMPLS')
param existingDataCollectionEndpointIds array = []

@description('Access mode for ingestion')
@allowed(['Open', 'PrivateOnly'])
param ingestionAccessMode string = 'PrivateOnly'

@description('Access mode for query')
@allowed(['Open', 'PrivateOnly'])
param queryAccessMode string = 'PrivateOnly'

// Combine existing and new Application Insights IDs
var allApplicationInsightsIds = union(existingApplicationInsightsIds, [newApplicationInsightsId])

// Convert to the format expected by AMPLS module
var applicationInsightsComponents = [for id in allApplicationInsightsIds: {
  id: id
}]

var logAnalyticsWorkspaces = [for id in existingLogAnalyticsWorkspaceIds: {
  id: id
}]

var dataCollectionEndpoints = [for id in existingDataCollectionEndpointIds: {
  id: id
}]

// Deploy or update AMPLS with all resources
module ampls 'ampls.bicep' = {
  name: 'update-ampls-${take(uniqueString(deployment().name), 6)}'
  params: {
    amplsName: amplsName
    location: location
    tags: tags
    ingestionAccessMode: ingestionAccessMode
    queryAccessMode: queryAccessMode
    logAnalyticsWorkspaces: logAnalyticsWorkspaces
    applicationInsightsComponents: applicationInsightsComponents
    dataCollectionEndpoints: dataCollectionEndpoints
    enableNetworkIsolation: true
  }
}

// Outputs
output amplsId string = ampls.outputs.amplsId
output amplsName string = ampls.outputs.amplsName
output allApplicationInsightsIds array = allApplicationInsightsIds
