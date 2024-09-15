param location string ='global' // Using default Microsoft Private DNS, they are registered in global. (you can change this, but need to register, see ref01 )
param typeArray array
param privateLinksDnsZones object
param virtualNetworkId string

resource dnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' =  [ for obj in typeArray: {
  name: privateLinksDnsZones[obj.type].name
  location: location

}]
//@batchSize(5)
resource filePrivateDnsZoneVnetLinkLoop 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-01-01'  = [for i in range(0, length(typeArray)): {
  dependsOn:[
    dnsZone[i]
  ]
  name: '${dnsZone[i].name}/${uniqueString(typeArray[i].id)}'
  location: location
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}]

