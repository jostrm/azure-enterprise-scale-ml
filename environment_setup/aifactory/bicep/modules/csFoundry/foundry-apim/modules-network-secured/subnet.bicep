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

// Use a helper module to get existing subnet properties (avoids circular dependency)
module getSubnetProps '../../../subnetGetProps.bicep' = {
  name: 'get-subnet-props-${uniqueString(deployment().name, subnetName)}'
  scope: resourceGroup(vnetResourceGroupName)
  params: {
    vnetName: vnetName
    subnetName: subnetName
  }
}

// Update subnet while preserving existing NSG, service endpoints, route tables, etc.
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  name: '${vnetName}/${subnetName}'
  properties: {
    addressPrefix: addressPrefix
    // Preserve existing service endpoints
    serviceEndpoints: !empty(getSubnetProps.outputs.serviceEndpoints) ? getSubnetProps.outputs.serviceEndpoints : null
    // Preserve existing NSG - critical!
    networkSecurityGroup: !empty(getSubnetProps.outputs.networkSecurityGroupId) ? {
      id: getSubnetProps.outputs.networkSecurityGroupId
    } : null
    // Preserve existing route table
    routeTable: !empty(getSubnetProps.outputs.routeTableId) ? {
      id: getSubnetProps.outputs.routeTableId
    } : null
    // Preserve existing NAT gateway
    natGateway: !empty(getSubnetProps.outputs.natGatewayId) ? {
      id: getSubnetProps.outputs.natGatewayId
    } : null
    // Set delegations (new or updated)
    delegations: delegations
    // Preserve network policies
    privateEndpointNetworkPolicies: getSubnetProps.outputs.privateEndpointNetworkPolicies
    privateLinkServiceNetworkPolicies: getSubnetProps.outputs.privateLinkServiceNetworkPolicies
  }
  dependsOn: [
    getSubnetProps
  ]
}

output subnetId string = subnet.id
output subnetName string = subnetName
