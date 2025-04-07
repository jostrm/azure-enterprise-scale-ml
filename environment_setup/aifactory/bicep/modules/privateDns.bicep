param dnsConfig array
param privateLinksDnsZones object

resource privateEndpointDnsZone 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2020-08-01' = [ for obj in dnsConfig: {
  name: '${obj.name}/${obj.name}DnsZone'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: '${obj.name}'
        properties: {
          privateDnsZoneId: privateLinksDnsZones[obj.type].id
        }
      }
    ]
  }
}]
