targetScope = 'resourceGroup'

@minLength(1)
param apimServiceName string

@minLength(1)
param location string

@minLength(1)
param privateEndpointSubnetId string

@minLength(1)
param privateEndpointName string

@allowed([
  'policy'
  'existingZone'
])
param privateDnsMode string = 'policy'

@description('Caller-validated full ID of an approved existing privatelink.azure-api.net zone.')
param privateDnsZoneId string = ''

param tags object = {}

@minLength(1)
param ownershipId string

// Azure tag names are case-insensitive; discard all caller spellings of the reserved ownership tag.
var callerTags = toObject(filter(items(tags), tag => toLower(tag.key) != 'aifactory-gateway-owner'), tag => tag.key, tag => tag.value)

resource apimService 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimServiceName
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: privateEndpointName
  location: location
  tags: union(callerTags, {
    'aifactory-gateway-owner': ownershipId
  })
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: apimService.id
          groupIds: [
            'Gateway'
          ]
        }
      }
    ]
  }
}

resource privateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (privateDnsMode == 'existingZone') {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink.azure-api.net'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

output privateEndpointResourceId string = privateEndpoint.id
output apimResourceId string = apimService.id
