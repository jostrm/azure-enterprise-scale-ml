param vnetName string
param subnetName string
param location string
param vnetResourceGroupName string
param addressPrefix string = ''
param existingAddressPrefix string = ''
param serviceEndpoints array = []
param delegations array

// Get the existing VNet
resource vnet 'Microsoft.Network/virtualNetworks@2023-05-01' existing = {
  name: vnetName
  //scope: resourceGroup(vnetResourceGroupName)
}

// First module - Get subnet properties
module existingSubnet 'subnetGetProps.bicep' = {
  name: 'get-snet-props-${uniqueString(deployment().name)}'
  scope: resourceGroup(vnetResourceGroupName)
  params: {
    vnetName: vnetName
    subnetName: subnetName
  }
}

// Fix: Instead of using a symbolic reference to existingSubnet, 
// use a reference() function for current subnet properties
//var existingSubnet = reference(
//  resourceId(vnetResourceGroupName, 'Microsoft.Network/virtualNetworks/subnets', vnetName, subnetName), 
//  '2023-05-01'
//)

// Update subnet with delegations
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' = {
  parent: vnet
  name: subnetName
  properties: {
    addressPrefix: !empty(addressPrefix) ? addressPrefix : (!empty(existingAddressPrefix) ? existingAddressPrefix : existingSubnet.outputs.addressPrefix)
    serviceEndpoints: !empty(serviceEndpoints) ? serviceEndpoints : existingSubnet.outputs.serviceEndpoints
    //routeTable: {
//      id:existingSubnet.outputs.routeTableId
    //}
    networkSecurityGroup: {
      id:existingSubnet.outputs.networkSecurityGroupId
    }
    delegations: union(
      existingSubnet.outputs.delegations ?? [],
      delegations
    )
    privateEndpointNetworkPolicies: 'Disabled' //  (recommended for most cases):securely connect to private endpoints without being blocked by NSGs
    privateLinkServiceNetworkPolicies: 'Enabled' //  (default setting):NSG rules are applied to private link services
  }
  dependsOn:[
    existingSubnet
  ]
}

output subnetId string = subnet.id
output subnetName string = subnet.name
