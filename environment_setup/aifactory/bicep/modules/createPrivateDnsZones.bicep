param privDnsSubscription string
param privDnsResourceGroup string
param vNetName string
param vNetResourceGroup string
param location string
param allGlobal bool = true
var locationGlobal = 'global' // Using default Microsoft Private DNS, they are registered in global. (you can change this, but need to register, see ref01 )
param privateLinksDnsZones array

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vNetName
  scope: resourceGroup(vNetResourceGroup)
}

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for zone in privateLinksDnsZones: {
  name: zone.name
  location: (zone.name == '${location}.data.privatelink.azurecr.io' && allGlobal==false)? location:locationGlobal
  properties: {}
  // etag:''
  // tags:tags
}]

resource filePrivateDnsZoneVnetLinkLoop 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01'  =[for i in range(0, length(privateLinksDnsZones)): {
  dependsOn:[
    privateDnsZones[i]
  ]
  name: '${privateDnsZones[i].name}/${uniqueString(privateDnsZones[i].id)}'
  location: (privateDnsZones[i].name == '${location}.data.privatelink.azurecr.io' && allGlobal==false)? location:locationGlobal
  properties: {
    registrationEnabled: false // Is auto-registration of virtual machine records in the virtual network in the Private DNS zone enabled?
    resolutionPolicy: 'NxDomainRedirect' // The resolution policy for the private DNS zone. Possible values include: 'Default', 'NxDomainRedirect'
    virtualNetwork: {
      id: vnet.id
    }
  }
}]
