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
module existingSnet 'subnetGetProps.bicep' = {
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
    addressPrefix: !empty(addressPrefix) ? addressPrefix : (!empty(existingAddressPrefix) ? existingAddressPrefix : existingSnet.outputs.addressPrefix)
    serviceEndpoints: !empty(serviceEndpoints) ? serviceEndpoints : existingSnet.outputs.serviceEndpoints
    routeTable: !empty(existingSnet.outputs.routeTableId)?{
      id:existingSnet.outputs.routeTableId
    }:null
    networkSecurityGroup: !empty(existingSnet.outputs.networkSecurityGroupId)?{
      id:existingSnet.outputs.networkSecurityGroupId
    }:null
    natGateway: !empty(existingSnet.outputs.natGatewayId)?{
      id:existingSnet.outputs.natGatewayId
    }:null
    delegations: delegations
    privateEndpointNetworkPolicies: (existingSnet.outputs.privateEndpointNetworkPolicies!='Disabled')?existingSnet.outputs.privateEndpointNetworkPolicies:'Disabled' //  (Disabled:recommended for most cases):securely connect to private endpoints without being blocked by NSGs
    privateLinkServiceNetworkPolicies:(existingSnet.outputs.privateLinkServiceNetworkPolicies!='Enabled')?existingSnet.outputs.privateLinkServiceNetworkPolicies :'Enabled' //  (default setting):NSG rules are applied to private link services
  }
  dependsOn:[
    existingSnet
  ]
}

output subnetId string = subnet.id
output subnetName string = subnet.name
