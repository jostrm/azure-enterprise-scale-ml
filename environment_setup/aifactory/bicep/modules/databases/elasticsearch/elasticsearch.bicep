// ================================================================
// ELASTICSEARCH (ELASTIC CLOUD) MODULE
// Deploys Azure Elastic Cloud integration
// ================================================================

@description('Elasticsearch monitor name')
param name string
// available regions for the Elasticsearch resource type is 'westus2,uksouth,eastus,eastus2,westeurope,francecentral,centralus,southcentralus,japaneast,southeastasia,australiaeast,northeurope,canadacentral,brazilsouth,southafricanorth,centralindia,spaincentral,germanywestcentral'.
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

// ============== LOCATION CONVERSION ==============
// Elasticsearch: If Sweden Central is chosen, use North Europe instead
var actualLocation = (toLower(location) == 'swedencentral' || toLower(location) == 'sweden central') ? 'northeurope' : location

// ============== NAME CONVERSION ==============
// Convert naming convention: sdc (Sweden Central) -> neu (North Europe)
var actualName = (toLower(location) == 'swedencentral' || toLower(location) == 'sweden central') ? replace(name, 'sdc', 'neu') : name

// ============== RESOURCE DEPLOYMENT ==============

resource elastic 'Microsoft.Elastic/monitors@2024-03-01' = {
  name: actualName
  location: actualLocation
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

var privateEndpointName = 'pend-${actualName}'
var privateLinkServiceConnectionName = 'plsc-${actualName}'
var groupId = 'es'

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = if (!enablePublicGenAIAccess && !enablePublicAccessWithPerimeter && createPrivateEndpoint && !empty(vnetName)) {
  name: privateEndpointName
  location: actualLocation
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

@description('Actual location used (converted from Sweden Central to North Europe if applicable)')
output actualLocation string = actualLocation

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
