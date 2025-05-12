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
output serviceEndpoints array = existingSubnet.properties.serviceEndpoints ?? []
output delegations array = existingSubnet.properties.delegations ?? []
output networkSecurityGroupId string = existingSubnet.properties.networkSecurityGroup.id ?? ''
output routeTableId string = contains(existingSubnet.properties, 'routeTable') ? existingSubnet.properties.routeTable.id : ''
output natGatewayId string = contains(existingSubnet.properties, 'natGateway') ? existingSubnet.properties.natGateway.id : ''
output privateEndpointNetworkPolicies string = existingSubnet.properties.privateEndpointNetworkPolicies ?? ''
output privateLinkServiceNetworkPolicies string = existingSubnet.properties.privateLinkServiceNetworkPolicies ?? ''

