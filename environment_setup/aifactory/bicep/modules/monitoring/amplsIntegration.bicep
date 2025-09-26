// ============================================================================
// AMPLS Integration with AI Factory Foundation
// ============================================================================
// This module integrates Azure Monitor Private Link Scope with the existing
// AI Factory foundation deployment, following hub/spoke architecture

@description('Environment identifier (dev, test, prod)')
@allowed(['dev', 'test', 'prod'])
param env string

@description('Location for all resources')
param location string

@description('Location suffix for naming (e.g., weu, eus2)')
param locationSuffix string

@description('Common resource naming suffix')
param commonResourceSuffix string

@description('Tags to apply to all resources')
param tags object = {}

@description('Private DNS subscription and resource group (from foundation)')
param privDnsSubscription string
param privDnsResourceGroup string

@description('Hub virtual network configuration')
param hubVnetName string
param hubVnetResourceGroup string

@description('Monitoring subnet name in hub')
param monitoringSubnetName string = 'snet-monitoring'

@description('Existing monitoring resources to connect to AMPLS')
param existingLogAnalyticsWorkspaceIds array = []
param existingApplicationInsightsIds array = []

@description('AMPLS configuration')
@allowed(['Open', 'PrivateOnly'])
param ingestionAccessMode string = 'PrivateOnly'

@allowed(['Open', 'PrivateOnly'])
param queryAccessMode string = 'PrivateOnly'

@description('Deploy to hub resource group (where private DNS zones are)')
param deployToHubResourceGroup bool = true

// ============================================================================
// COMPUTED VARIABLES
// ============================================================================

var targetResourceGroup = deployToHubResourceGroup ? privDnsResourceGroup : resourceGroup().name
var targetSubscription = deployToHubResourceGroup ? privDnsSubscription : subscription().subscriptionId

// Private DNS Zone resource IDs
var privateDnsZoneResourceIds = {
  monitor: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.monitor.azure.com'
  oms: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.oms.opinsights.azure.com'
  ods: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.ods.opinsights.azure.com'
  agentsvc: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.agentsvc.azure-automation.net'
}

// Convert existing resource IDs to the format expected by AMPLS module
var logAnalyticsWorkspaces = [for workspaceId in existingLogAnalyticsWorkspaceIds: {
  id: workspaceId
}]

var applicationInsightsComponents = [for appInsightsId in existingApplicationInsightsIds: {
  id: appInsightsId
}]

// ============================================================================
// AMPLS DEPLOYMENT
// ============================================================================

module amplsDeployment 'amplsHubSimple.bicep' = {
  name: 'ampls-integration-${take(uniqueString(subscription().subscriptionId, resourceGroup().id), 6)}'
  scope: resourceGroup(targetSubscription, targetResourceGroup)
  params: {
    env: env
    location: location
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    tags: tags
    hubVnetName: hubVnetName
    hubVnetResourceGroup: hubVnetResourceGroup
    hubSubnetName: monitoringSubnetName
    logAnalyticsWorkspaces: logAnalyticsWorkspaces
    applicationInsightsComponents: applicationInsightsComponents
    privateDnsZoneResourceIds: privateDnsZoneResourceIds
    ingestionAccessMode: ingestionAccessMode
    queryAccessMode: queryAccessMode
  }
}

// ============================================================================
// OUTPUTS
// ============================================================================

@description('AMPLS deployment information')
output amplsInfo object = amplsDeployment.outputs.ampls

@description('Data Collection Endpoint information')
output dceInfo object = amplsDeployment.outputs.dataCollectionEndpoint

@description('Private Endpoint information')
output privateEndpointInfo object = amplsDeployment.outputs.privateEndpoint

@description('AMPLS Resource Group')
output amplsResourceGroup string = targetResourceGroup

@description('AMPLS Subscription')
output amplsSubscription string = targetSubscription

@description('AMPLS integration completed')
output integrationComplete bool = amplsDeployment.outputs.deploymentComplete
