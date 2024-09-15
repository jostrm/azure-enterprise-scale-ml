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

/*
{
  properties: {
    privateDnsZoneConfigs: [
      {
        properties: {
          privateDnsZoneId: '/subscriptions/451967ad-7751-478e-8c64-cd0e7afa64ed/resourceGroups/sweco-1-esml-common-sdc-dev-001/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net'
        }
      }
    ]
  }
}
*/
