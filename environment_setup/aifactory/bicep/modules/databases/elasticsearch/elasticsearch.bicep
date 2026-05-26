// ================================================================
// ELASTICSEARCH (ELASTIC CLOUD) MODULE
// Deploys Azure Elastic Cloud integration
// ================================================================

@description('Elasticsearch monitor name')
param name string

@description('Azure region')
param location string

@description('Elastic Cloud SKU')
@allowed([
  'ess-consumption-2024_Monthly'
])
param skuName string = 'ess-consumption-2024_Monthly'

@description('Email associated with Elastic Cloud account')
param elasticEmail string

@description('Enable monitoring')
param monitoringEnabled bool = true

@description('Deployment size')
@allowed([
  'small'
  'medium'
  'large'
])
param deploymentSize string = 'small'

@description('Tags for the resource')
param tags object = {}

@description('Enable public network access')
param enablePublicGenAIAccess bool = false

@description('Enable public access with network perimeter')
param enablePublicAccessWithPerimeter bool = false

@description('VNet name for private endpoint')
param vnetName string = ''

@description('VNet resource group name')
param vnetResourceGroupName string = ''

@description('Subnet name for private endpoint')
param subnetNamePend string = ''

@description('Create private endpoint')
param createPrivateEndpoint bool = true

// ============== RESOURCE DEPLOYMENT ==============

resource elastic 'Microsoft.Elastic/monitors@2024-03-01' = {
  name: name
  location: location
  sku: {
    name: skuName
  }
  properties: {
    monitoringStatus: monitoringEnabled ? 'Enabled' : 'Disabled'
  }
  tags: union(tags, {
    size: deploymentSize
    email: elasticEmail
  })
}

// ============== PRIVATE ENDPOINT ==============

var privateEndpointName = 'pend-${name}'
var privateLinkServiceConnectionName = 'plsc-${name}'
var groupId = 'es'

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = if (!enablePublicGenAIAccess && !enablePublicAccessWithPerimeter && createPrivateEndpoint && !empty(vnetName)) {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: resourceId(vnetResourceGroupName, 'Microsoft.Network/virtualNetworks/subnets', vnetName, subnetNamePend)
    }
    privateLinkServiceConnections: [
      {
        name: privateLinkServiceConnectionName
        properties: {
          privateLinkServiceId: elastic.id
          groupIds: [
            groupId
          ]
        }
      }
    ]
  }
}

// ============== OUTPUTS ==============

@description('Elasticsearch resource ID')
output elasticResourceId string = elastic.id

@description('Elasticsearch name')
output elasticName string = elastic.name

@description('Private endpoint ID')
output privateEndpointId string = createPrivateEndpoint && !enablePublicGenAIAccess && !enablePublicAccessWithPerimeter && !empty(vnetName) ? privateEndpoint.id : ''

@description('DNS configuration for private DNS zone linking')
output dnsConfig array = [
  {
    name: createPrivateEndpoint && !enablePublicGenAIAccess && !enablePublicAccessWithPerimeter && !empty(vnetName) ? privateEndpointName : ''
    type: 'elastic'
    id: createPrivateEndpoint && !enablePublicGenAIAccess && !enablePublicAccessWithPerimeter && !empty(vnetName) ? elastic.id : ''
  }
]
