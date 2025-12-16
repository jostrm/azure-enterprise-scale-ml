param vnetName string
param subnetName string

resource vnet 'Microsoft.Network/virtualNetworks@2023-05-01' existing = {
  name: vnetName
}

resource existingSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: subnetName
}

output addressPrefix string = existingSubnet.properties.addressPrefix
output serviceEndpoints array = contains(existingSubnet.properties, 'serviceEndpoints') ? existingSubnet.properties.serviceEndpoints : []
output delegations array = contains(existingSubnet.properties, 'delegations') ? existingSubnet.properties.delegations : []
output networkSecurityGroupId string = contains(existingSubnet.properties, 'networkSecurityGroup') ? existingSubnet.properties.networkSecurityGroup.id : ''
output routeTableId string = contains(existingSubnet.properties, 'routeTable') ? existingSubnet.properties.routeTable.id : ''
output natGatewayId string = contains(existingSubnet.properties, 'natGateway') ? existingSubnet.properties.natGateway.id : ''
output privateEndpointNetworkPolicies string = contains(existingSubnet.properties, 'privateEndpointNetworkPolicies') ? existingSubnet.properties.privateEndpointNetworkPolicies : 'Disabled'
output privateLinkServiceNetworkPolicies string = contains(existingSubnet.properties, 'privateLinkServiceNetworkPolicies') ? existingSubnet.properties.privateLinkServiceNetworkPolicies : 'Enabled'

