param privDnsSubscription string
param privDnsResourceGroup string
param vNetName string
param vNetResourceGroup string
param location string
param allGlobal bool = true
param privateLinksDnsZones array

/*
[ 
  { 
    name: 'privatelink1.contoso.com', 
    exists: true 
  }, 
  { 
    name: 'privatelink2.contoso.com', 
    exists: false 
  } 
]
*/
param dnsZonesExistence array
var locationGlobal = 'global' // Using default Microsoft Private DNS, they are registered in global. (you can change this, but need to register, see ref01)

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vNetName
  scope: resourceGroup(vNetResourceGroup)
}

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for (zone, index) in privateLinksDnsZones: if (!dnsZonesExistence[index].exists) {
  name: zone.name
  location: (zone.name == '${location}.data.privatelink.azurecr.io' && allGlobal == false) ? location : locationGlobal
  properties: {}
}]

resource filePrivateDnsZoneVnetLinkLoop 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (zone, index) in privateLinksDnsZones: if (!dnsZonesExistence[index].exists) {
  dependsOn: [
    privateDnsZones[index]
  ]
  name: '${zone.name}/${uniqueString(zone.name)}'
  location: (zone.name == '${location}.data.privatelink.azurecr.io' && allGlobal == false) ? location : locationGlobal
  properties: {
    registrationEnabled: false // Is auto-registration of virtual machine records in the virtual network in the Private DNS zone enabled?
    resolutionPolicy: 'NxDomainRedirect' // The resolution policy for the private DNS zone. Possible values include: 'Default', 'NxDomainRedirect'
    virtualNetwork: {
      id: vnet.id
    }
  }
}]
