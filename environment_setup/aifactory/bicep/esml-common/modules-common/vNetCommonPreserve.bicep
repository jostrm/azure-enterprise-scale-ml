@description('Only the reviewed, live-inventory-bound preserve-v1 plan is supported.')
param plan object
param location string
param tags object
param vnetNameFull string

// ARM deployment mode is not create-only: the coordinator must hold the hub lease
// and revalidate absence immediately before deploying this initial parent resource.
resource initialVnet 'Microsoft.Network/virtualNetworks@2023-11-01' = if (plan.createVnet) {
  name: vnetNameFull
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: plan.addressPrefixes
    }
  }
}

resource retainedVnet 'Microsoft.Network/virtualNetworks@2023-11-01' existing = {
  name: vnetNameFull
}

@batchSize(1)
resource missingSubnets 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' = [for subnet in plan.createSubnets: {
  parent: retainedVnet
  name: subnet.name
  properties: subnet.properties
  dependsOn: [
    initialVnet
  ]
}]

output vnetId string = retainedVnet.id
