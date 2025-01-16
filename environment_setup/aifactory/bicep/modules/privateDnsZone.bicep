param location string ='global' // Using default Microsoft Private DNS, they are registered in global. (you can change this, but need to register, see ref01 )
param typeArray array
param privateLinksDnsZones object
param virtualNetworkId string
param tags object = {}

resource dnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' =  [ for obj in typeArray: {
  name: privateLinksDnsZones[obj.type].name
  location: location
  // etag:''
  // tags:tags

}]
//@batchSize(5)
resource filePrivateDnsZoneVnetLinkLoop 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01'  = [for i in range(0, length(typeArray)): {
  dependsOn:[
    dnsZone[i]
  ]
  name: '${dnsZone[i].name}/${uniqueString(typeArray[i].id)}'
  location: location
  properties: {
    registrationEnabled: false // Is auto-registration of virtual machine records in the virtual network in the Private DNS zone enabled?
    resolutionPolicy: 'NxDomainRedirect' // The resolution policy for the private DNS zone. Possible values include: 'Default', 'NxDomainRedirect'
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}]

