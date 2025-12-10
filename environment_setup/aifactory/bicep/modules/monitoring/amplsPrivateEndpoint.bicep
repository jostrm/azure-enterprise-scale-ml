// ============================================================================
// Azure Monitor Private Endpoint Module
// ============================================================================
// This module creates a private endpoint for Azure Monitor Private Link Scope
// and integrates it with private DNS zones

@description('Name of the private endpoint')
param privateEndpointName string

@description('Location for the private endpoint')
param location string

@description('Tags to apply to the private endpoint')
param tags object = {}

@description('Resource ID of the subnet where the private endpoint will be created')
param subnetId string

@description('Resource ID of the Azure Monitor Private Link Scope')
param amplsId string

@description('Array of private DNS zone configurations')
param privateDnsZoneConfigs array = [
  {
    name: 'privatelink-monitor-azure-com'
    privateDnsZoneResourceId: ''
  }
  {
    name: 'privatelink-oms-opinsights-azure-com'
    privateDnsZoneResourceId: ''
  }
  {
    name: 'privatelink-ods-opinsights-azure-com'
    privateDnsZoneResourceId: ''
  }
  {
    name: 'privatelink-agentsvc-azure-automation-net'
    privateDnsZoneResourceId: ''
  }
]

@description('Enable automatic private DNS zone group')
param enablePrivateDnsZoneGroup bool = true

// Create the private endpoint for AMPLS
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${privateEndpointName}-connection'
        properties: {
          privateLinkServiceId: amplsId
          groupIds: [
            'azuremonitor'
          ]
        }
      }
    ]
  }
}

// Create private DNS zone group for automatic DNS integration
resource privateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (enablePrivateDnsZoneGroup) {
  name: 'default'
  parent: privateEndpoint
  properties: {
    privateDnsZoneConfigs: [for config in privateDnsZoneConfigs: {
      name: config.name
      properties: {
        privateDnsZoneId: config.privateDnsZoneResourceId
      }
    }]
  }
}

// Outputs
output privateEndpointId string = privateEndpoint.id
output privateEndpointName string = privateEndpoint.name
output privateEndpointIpAddresses array = privateEndpoint.properties.customDnsConfigs
