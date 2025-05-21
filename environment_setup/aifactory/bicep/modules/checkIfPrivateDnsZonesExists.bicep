param privateLinksDnsZones array
param privDnsResourceGroup string

var existingPrivateDnsZones = [for zone in privateLinksDnsZones: {
  name: zone.name
  exists: !empty(resourceId('Microsoft.Network/privateDnsZones', zone.name))
}]

output existingPrivateDnsZones array = existingPrivateDnsZones
