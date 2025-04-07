param vnetName string
param subnetName string
param location string
param vnetResourceGroupName string
param addressPrefix string = ''
param existingAddressPrefix string = ''
param serviceEndpoints array = []
param delegations array = [
  {
    name: 'webapp-delegation'
    properties: {
      serviceName: 'Microsoft.Web/serverFarms'
    }
  }
]

// Get the existing VNet
resource vnet 'Microsoft.Network/virtualNetworks@2023-05-01' existing = {
  name: vnetName
  //scope: resourceGroup(vnetResourceGroupName)
}

// Try to get the existing subnet
resource existingSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' existing = {
  parent: vnet
  name: subnetName
}

// Update subnet with delegations
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' = {
  parent: vnet
  name: subnetName
  properties: {
    addressPrefix: !empty(addressPrefix) ? addressPrefix : (!empty(existingAddressPrefix) ? existingAddressPrefix : existingSubnet.properties.addressPrefix)
    serviceEndpoints: !empty(serviceEndpoints) ? serviceEndpoints : existingSubnet.properties.serviceEndpoints
    delegations: union(
      existingSubnet.properties.delegations ?? [],
      delegations
    )
    privateEndpointNetworkPolicies: 'Disabled' //  (recommended for most cases):securely connect to private endpoints without being blocked by NSGs
    privateLinkServiceNetworkPolicies: 'Enabled' //  (default setting):NSG rules are applied to private link services
  }
}

output subnetId string = subnet.id
output subnetName string = subnet.name
