param dnsConfig array
param privateLinksDnsZones object
param resourceCreatedNow bool = false

//resource privateEndpointDnsZone 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2020-08-01' = [ for obj in dnsConfig: if(resourceCreatedNow){
resource privateEndpointDnsZone 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [ for obj in dnsConfig: if(!empty(obj.name)) {
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
