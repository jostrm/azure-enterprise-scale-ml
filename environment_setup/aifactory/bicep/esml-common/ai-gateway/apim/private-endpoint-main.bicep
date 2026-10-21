targetScope = 'subscription'

@minLength(1)
param apimServiceName string

@minLength(1)
param apimResourceGroupName string

param apimSubscriptionId string = subscription().subscriptionId

@minLength(1)
param location string

@minLength(1)
@description('Existing approved nondelegated private endpoint subnet. This module never changes it.')
param privateEndpointSubnetId string

@minLength(1)
param privateEndpointName string

@allowed([
  'policy'
  'existingZone'
])
@description('Policy owns DNS by default. existingZone associates only an approved existing private zone.')
param privateDnsMode string = 'policy'

@description('Full existing privatelink.azure-api.net zone ID, required and validated by the caller only for existingZone mode.')
param privateDnsZoneId string = ''

param tags object = {}

@minLength(1)
@description('Stable owner for this managed private endpoint. Caller must reject adoption of unrelated endpoints.')
param ownershipId string

module privateEndpoint 'private-endpoint.bicep' = {
  name: 'apim-pe-${uniqueString(apimSubscriptionId, apimResourceGroupName, privateEndpointName)}'
  scope: resourceGroup(apimSubscriptionId, apimResourceGroupName)
  params: {
    apimServiceName: apimServiceName
    location: location
    privateEndpointSubnetId: privateEndpointSubnetId
    privateEndpointName: privateEndpointName
    privateDnsMode: privateDnsMode
    privateDnsZoneId: privateDnsZoneId
    tags: tags
    ownershipId: ownershipId
  }
}

output privateEndpointResourceId string = privateEndpoint.outputs.privateEndpointResourceId
output apimResourceId string = privateEndpoint.outputs.apimResourceId
