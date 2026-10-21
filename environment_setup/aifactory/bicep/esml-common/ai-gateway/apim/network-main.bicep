targetScope = 'subscription'

@minLength(1)
@description('Full ID of the approved NEW dedicated integration subnet in an existing VNet in this subscription. The caller must verify absence; validated reuse skips this deployment.')
param integrationSubnetId string

@minLength(1)
@description('Explicit approved non-overlapping CIDR for the new integration subnet. No automatic allocation.')
param integrationSubnetPrefix string

@minLength(1)
@description('Full ID of an existing approved network security group. Its rules are not changed.')
param networkSecurityGroupId string

@description('Full ID of an existing approved route table. Empty deliberately means no route table association.')
param routeTableId string = ''

@minLength(1)
@description('Approved VNet location; also distinguishes the scoped deployment name. Subnets inherit their VNet location.')
param location string

module integrationSubnet 'network-subnet.bicep' = {
  name: 'apim-subnet-${uniqueString(integrationSubnetId, location)}'
  scope: resourceGroup(subscription().subscriptionId, split(integrationSubnetId, '/')[4])
  params: {
    integrationSubnetId: integrationSubnetId
    integrationSubnetPrefix: integrationSubnetPrefix
    networkSecurityGroupId: networkSecurityGroupId
    routeTableId: routeTableId
  }
}

output subnetId string = integrationSubnet.outputs.subnetId
