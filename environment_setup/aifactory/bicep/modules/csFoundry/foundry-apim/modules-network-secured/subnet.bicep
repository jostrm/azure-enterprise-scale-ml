@description('Name of the virtual network')
param vnetName string

@description('Name of the subnet')
param subnetName string

@description('Address prefix for the subnet')
param addressPrefix string

@description('Array of subnet delegations')
param delegations array = []

@description('Resource group where the VNet exists')
param vnetResourceGroupName string = resourceGroup().name

// Get existing VNet
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

// Get existing subnet properties to preserve them
resource existingSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: subnetName
}

// Update subnet while preserving existing NSG, service endpoints, route tables, etc.
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  name: '${vnetName}/${subnetName}'
  properties: {
    addressPrefix: addressPrefix
    // Preserve existing service endpoints
    serviceEndpoints: contains(existingSubnet.properties, 'serviceEndpoints') ? existingSubnet.properties.serviceEndpoints : null
    // Preserve existing NSG - critical!
    networkSecurityGroup: contains(existingSubnet.properties, 'networkSecurityGroup') ? {
      id: existingSubnet.properties.networkSecurityGroup.id
    } : null
    // Preserve existing route table
    routeTable: contains(existingSubnet.properties, 'routeTable') ? {
      id: existingSubnet.properties.routeTable.id
    } : null
    // Preserve existing NAT gateway
    natGateway: contains(existingSubnet.properties, 'natGateway') ? {
      id: existingSubnet.properties.natGateway.id
    } : null
    // Set delegations (new or updated)
    delegations: delegations
    // Preserve network policies
    privateEndpointNetworkPolicies: contains(existingSubnet.properties, 'privateEndpointNetworkPolicies') ? existingSubnet.properties.privateEndpointNetworkPolicies : 'Disabled'
    privateLinkServiceNetworkPolicies: contains(existingSubnet.properties, 'privateLinkServiceNetworkPolicies') ? existingSubnet.properties.privateLinkServiceNetworkPolicies : 'Enabled'
  }
}

output subnetId string = subnet.id
output subnetName string = subnetName
