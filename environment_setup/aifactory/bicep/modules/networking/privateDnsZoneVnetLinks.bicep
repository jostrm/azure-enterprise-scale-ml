// Links existing private DNS zones (in this resource group) to one more VNet.
// Used by esml-common/main/13-rgLevel.bicep when an added scale set joins the factory's own access hub: the
// bootstrap created the zones (with its tags) and linked them to the hub VNet only. The zones are referenced,
// never PUT again. The link name is derived from the VNet id, so re-runs PUT the same link and every added scale
// set gets its own (one zone can link many VNets, but each VNet once).

@description('Zones to link: objects with a name property (13-rgLevel privateLinksDnsZonesArray).')
param privateLinksDnsZones array
@description('ARM id of the VNet to link.')
param vnetId string
param location string
param allGlobal bool = true

var locationGlobal = 'global'

resource zones 'Microsoft.Network/privateDnsZones@2024-06-01' existing = [for zone in privateLinksDnsZones: {
  name: zone.name
}]

resource zoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (zone, i) in privateLinksDnsZones: {
  parent: zones[i]
  name: take('${last(split(vnetId, '/'))}-${uniqueString(vnetId)}', 80)
  location: (zone.name == '${location}.data.privatelink.azurecr.io' && allGlobal == false) ? location : locationGlobal
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'NxDomainRedirect'
    virtualNetwork: {
      id: vnetId
    }
  }
}]
