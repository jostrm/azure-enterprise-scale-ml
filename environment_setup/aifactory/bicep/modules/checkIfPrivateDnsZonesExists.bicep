param privateLinksDnsZones array
param privDnsResourceGroup string

/*
var existingPrivateDnsZones = [for zone in privateLinksDnsZones: {
  name: zone.name
  exists: !empty(resourceId('Microsoft.Network/privateDnsZones', zone.name))
}]
output existingPrivateDnsZones array = existingPrivateDnsZones
*/

module checkResourceExists 'checkIfOnePrivDnsZoneExists.bicep' = [for (zone, i) in privateLinksDnsZones: {
  name: 'checkResourceExists-${zone.name}'
  params: {
    resourceGroupName: privDnsResourceGroup
    resourceName: zone.name
    resourceType: 'Microsoft.Network/privateDnsZones'
  }
}]

output existingPrivateDnsZones array = [for (zone, i) in privateLinksDnsZones: {
  name: zone.name
  exists: checkResourceExists[i].outputs.exists
}]

//output aiFoundryHubExists bool = length(resourceNames.aiFoundryHub) > 0 ? checkResourceExists[0].outputs.exists : false


