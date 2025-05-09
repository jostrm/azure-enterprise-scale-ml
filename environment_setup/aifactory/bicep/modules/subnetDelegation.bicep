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

// Update subnet with delegations
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' = {
  parent: vnet
  name: subnetName
  properties: {
    addressPrefix: !empty(addressPrefix) ? addressPrefix : (!empty(existingAddressPrefix) ? existingAddressPrefix : existingSubnet.outputs.addressPrefix)
    serviceEndpoints: !empty(serviceEndpoints) ? serviceEndpoints : existingSubnet.outputs.serviceEndpoints
    routeTable: !empty(existingSubnet.outputs.routeTableId)?{
      id:existingSubnet.outputs.routeTableId
    }:null
    networkSecurityGroup: !empty(existingSubnet.outputs.networkSecurityGroupId)?{
      id:existingSubnet.outputs.networkSecurityGroupId
    }:null
    natGateway: !empty(existingSubnet.outputs.natGatewayId)?{
      id:existingSubnet.outputs.natGatewayId
    }:null
    delegations: delegations
    privateEndpointNetworkPolicies: (existingSubnet.outputs.privateEndpointNetworkPolicies!='Disabled')?existingSubnet.outputs.privateEndpointNetworkPolicies:'Disabled' //  (Disabled:recommended for most cases):securely connect to private endpoints without being blocked by NSGs
    privateLinkServiceNetworkPolicies:(existingSubnet.outputs.privateLinkServiceNetworkPolicies!='Enabled')?existingSubnet.outputs.privateLinkServiceNetworkPolicies :'Enabled' //  (default setting):NSG rules are applied to private link services
  }
  dependsOn:[
    existingSubnet
  ]
}

output subnetId string = subnet.id
output subnetName string = subnet.name
