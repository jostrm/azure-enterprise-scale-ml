// ============================================================================
// Azure Monitor Private Link Scope - Simplified Hub Deployment
// ============================================================================
// This module deploys AMPLS in a hub/spoke architecture
// Deploy DCE and AMPLS resources separately to avoid conditional logic issues

targetScope = 'resourceGroup'

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

@description('Hub virtual network configuration')
param hubVnetName string
param hubVnetResourceGroup string
param hubSubnetName string = 'snet-monitoring'

@description('Existing Log Analytics Workspaces to connect')
param logAnalyticsWorkspaces array = []

@description('Existing Application Insights to connect')
param applicationInsightsComponents array = []

@description('Private DNS Zone configuration')
param privateDnsZoneResourceIds object = {
  monitor: ''
  oms: ''
  ods: ''
  agentsvc: ''
}

@description('Access modes for AMPLS')
@allowed(['Open', 'PrivateOnly'])
param ingestionAccessMode string = 'PrivateOnly'

@allowed(['Open', 'PrivateOnly'])
param queryAccessMode string = 'PrivateOnly'

// ============================================================================
// COMPUTED VARIABLES
// ============================================================================

var amplsName = 'ampls-${locationSuffix}-${env}${commonResourceSuffix}'
var privateEndpointName = 'pe-ampls-${locationSuffix}-${env}${commonResourceSuffix}'
var dceName = 'dce-${locationSuffix}-${env}${commonResourceSuffix}'

// Reference to hub subnet
resource hubVnet 'Microsoft.Network/virtualNetworks@2024-01-01' existing = {
  name: hubVnetName
  scope: resourceGroup(hubVnetResourceGroup)
}

resource hubSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-01-01' existing = {
  name: hubSubnetName
  parent: hubVnet
}

// ============================================================================
// DATA COLLECTION ENDPOINTS
// ============================================================================

module dataCollectionEndpoint 'dataCollectionEndpoint.bicep' = {
  name: 'deploy-dce-${take(uniqueString(resourceGroup().id), 6)}'
  params: {
    dceName: dceName
    location: location
    tags: tags
    dceDescription: 'Data Collection Endpoint for Azure Monitor Private Link - ${env} environment'
    kind: 'Linux'
    enablePublicNetworkAccess: false
  }
}

// ============================================================================
// AZURE MONITOR PRIVATE LINK SCOPE
// ============================================================================

module azureMonitorPrivateLinkScope 'ampls.bicep' = {
  name: 'deploy-ampls-${take(uniqueString(resourceGroup().id), 6)}'
  params: {
    amplsName: amplsName
    location: location
    tags: tags
    ingestionAccessMode: ingestionAccessMode
    queryAccessMode: queryAccessMode
    logAnalyticsWorkspaces: logAnalyticsWorkspaces
    applicationInsightsComponents: applicationInsightsComponents
    dataCollectionEndpoints: [
      {
        id: dataCollectionEndpoint.outputs.dceId
      }
    ]
    enableNetworkIsolation: true
  }
  dependsOn: [
    dataCollectionEndpoint
  ]
}

// ============================================================================
// PRIVATE ENDPOINTS
// ============================================================================

module amplsPrivateEndpoint 'amplsPrivateEndpoint.bicep' = {
  name: 'deploy-pe-ampls-${take(uniqueString(resourceGroup().id), 6)}'
  params: {
    privateEndpointName: privateEndpointName
    location: location
    tags: tags
    subnetId: hubSubnet.id
    amplsId: azureMonitorPrivateLinkScope.outputs.amplsId
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-monitor-azure-com'
        privateDnsZoneResourceId: privateDnsZoneResourceIds.monitor
      }
      {
        name: 'privatelink-oms-opinsights-azure-com'
        privateDnsZoneResourceId: privateDnsZoneResourceIds.oms
      }
      {
        name: 'privatelink-ods-opinsights-azure-com'
        privateDnsZoneResourceId: privateDnsZoneResourceIds.ods
      }
      {
        name: 'privatelink-agentsvc-azure-automation-net'
        privateDnsZoneResourceId: privateDnsZoneResourceIds.agentsvc
      }
    ]
    enablePrivateDnsZoneGroup: true
  }
  dependsOn: [
    azureMonitorPrivateLinkScope
  ]
}

// ============================================================================
// OUTPUTS
// ============================================================================

@description('Azure Monitor Private Link Scope information')
output ampls object = {
  id: azureMonitorPrivateLinkScope.outputs.amplsId
  name: azureMonitorPrivateLinkScope.outputs.amplsName
  resourceId: azureMonitorPrivateLinkScope.outputs.amplsResourceId
  ingestionAccessMode: azureMonitorPrivateLinkScope.outputs.ingestionAccessMode
  queryAccessMode: azureMonitorPrivateLinkScope.outputs.queryAccessMode
}

@description('Data Collection Endpoint information')
output dataCollectionEndpoint object = {
  id: dataCollectionEndpoint.outputs.dceId
  name: dataCollectionEndpoint.outputs.dceName
  resourceId: dataCollectionEndpoint.outputs.dceResourceId
  logsIngestionEndpoint: dataCollectionEndpoint.outputs.logsIngestionEndpoint
  metricsIngestionEndpoint: dataCollectionEndpoint.outputs.metricsIngestionEndpoint
}

@description('Private Endpoint information')
output privateEndpoint object = {
  id: amplsPrivateEndpoint.outputs.privateEndpointId
  name: amplsPrivateEndpoint.outputs.privateEndpointName
  ipAddresses: amplsPrivateEndpoint.outputs.privateEndpointIpAddresses
}

@description('AMPLS deployment completed successfully')
output deploymentComplete bool = true
