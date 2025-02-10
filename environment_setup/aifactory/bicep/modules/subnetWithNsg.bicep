// required
@description('Specifies the id of an NSG that should be connected to new subnet')
param nsgId string = ''

@description('Specifies the name of the new subnet')
param name string

@description('Specifies the address prefix used for new subnet')
param addressPrefix string

@description('Specifies the location where new subnet is deployed. Defaults to resourceGroup.location')
param location string = resourceGroup().location

@description('Specifies an array of service endpoints that should be enabled on the new subnet')
param serviceEndpoints array = []

@description('Specifies an array of delegations that should be enabled on the new subnet')
param delegations array 

@description('Specifies the name of a virtual network used for deploying new subnet')
param virtualNetworkName string

@description('Specifies a boolean to control if private endpoint network policies should be enabled or not')
param privateEndpointNetworkPolicies string = 'Enabled'

@description('Specifies a boolean to control if private link network policies should be enabled or not')
param privateLinkServiceNetworkPolicies string = 'Enabled'

@description('ESML can run in DEMO mode, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can turn this off, to use your HUB instead.')
param centralDnsZoneByPolicyInHub bool = false // TODO: jåaj - add ROUTING tables from HUB

resource snt 'Microsoft.Network/virtualNetworks/subnets@2020-06-01' = {
  name: '${virtualNetworkName}/${name}'
  properties: {
    addressPrefix: addressPrefix
    serviceEndpoints: [ for x in serviceEndpoints: {
        service: x
        locations: [
          location
        ]
    }]
    delegations: [ for x in delegations: {
        properties: {
          serviceName: x
        }
        name: '${toLower(split(split(x, '.')[0], '/')[0])}-del-${substring(uniqueString(name),0,12)}'
      }]
    privateEndpointNetworkPolicies: privateEndpointNetworkPolicies
    privateLinkServiceNetworkPolicies: privateLinkServiceNetworkPolicies
    //routeTable: // TODO if centralDnsZoneByPolicyInHub=true
    networkSecurityGroup: {
      id: nsgId
    }
  }
}


output subnetId string =  snt.id
output name string = snt.name


