targetScope = 'subscription'

@minLength(1)
param apimServiceName string

@minLength(1)
@description('Existing resource group for the managed APIM service.')
param apimResourceGroupName string

param apimSubscriptionId string = subscription().subscriptionId

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
@description('Existing validated dedicated subnet delegated to Microsoft.Web/serverFarms.')
param integrationSubnetId string

@allowed([
  'Enabled'
  'Disabled'
])
@description('Secure steady-state default. Enabled is only an explicit NEW-service bootstrap before creating and approving the private endpoint; never use Enabled on an existing service.')
param publicNetworkAccess string = 'Disabled'

@minLength(1)
@description('Stable ownership identifier. Caller must reject existing services that do not already carry this owner and the exact desired SKU, identity, network, location, and publisher settings.')
param ownershipId string

param tags object = {}

module apimService 'apim-service.bicep' = {
  name: 'apim-service-${uniqueString(apimSubscriptionId, apimResourceGroupName, apimServiceName)}'
  scope: resourceGroup(apimSubscriptionId, apimResourceGroupName)
  params: {
    apimServiceName: apimServiceName
    location: location
    publisherName: publisherName
    publisherEmail: publisherEmail
    skuCapacity: skuCapacity
    integrationSubnetId: integrationSubnetId
    publicNetworkAccess: publicNetworkAccess
    ownershipId: ownershipId
    tags: tags
  }
}

output apimResourceId string = apimService.outputs.apimResourceId
output managedIdentityPrincipalId string = apimService.outputs.managedIdentityPrincipalId
output gatewayUrl string = apimService.outputs.gatewayUrl
