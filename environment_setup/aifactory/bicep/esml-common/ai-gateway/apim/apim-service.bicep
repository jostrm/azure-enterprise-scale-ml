targetScope = 'resourceGroup'

@minLength(1)
param apimServiceName string

@minLength(1)
param location string

@minLength(1)
param publisherName string

@minLength(1)
param publisherEmail string

@minValue(1)
@maxValue(10)
param skuCapacity int = 1

@minLength(1)
param integrationSubnetId string

@allowed([
  'Enabled'
  'Disabled'
])
@description('Enabled is an explicit NEW-service bootstrap only. Disable after an approved private endpoint exists.')
param publicNetworkAccess string = 'Disabled'

@minLength(1)
param ownershipId string

param tags object = {}

// Azure tag names are case-insensitive; discard all caller spellings of the reserved ownership tag.
var callerTags = toObject(filter(items(tags), tag => toLower(tag.key) != 'aifactory-gateway-owner'), tag => tag.key, tag => tag.value)

resource apimService 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apimServiceName
  location: location
  tags: union(callerTags, {
    'aifactory-gateway-owner': ownershipId
  })
  sku: {
    name: 'StandardV2'
    capacity: skuCapacity
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publisherName: publisherName
    publisherEmail: publisherEmail
    developerPortalStatus: 'Disabled'
    publicNetworkAccess: publicNetworkAccess
    virtualNetworkType: 'External'
    virtualNetworkConfiguration: {
      subnetResourceId: integrationSubnetId
    }
  }
}

output apimResourceId string = apimService.id
output managedIdentityPrincipalId string = apimService.identity.principalId
output gatewayUrl string = apimService.properties.gatewayUrl
