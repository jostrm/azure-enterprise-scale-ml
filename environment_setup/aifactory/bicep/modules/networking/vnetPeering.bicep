// One side of a VNet peering, in the resource group of the local VNet.
// Used by esml-common/main/13-rgLevel.bicep when an added scale set joins the factory's own access hub:
// hub -> spoke (allowGatewayTransit) first, then spoke -> hub (useRemoteGateways).
// Same properties as bootstrap/lib/common_network_preservation.plan_peerings. Re-runs PUT the same child.

@description('Name of the local VNet (in this resource group) that owns the peering.')
param vnetName string
@description('Deterministic peering name, max 80 characters.')
@maxLength(80)
param peeringName string
@description('ARM id of the remote VNet.')
param remoteVnetId string
@description('true on the hub side: lets the spoke use the hub VPN gateway.')
param allowGatewayTransit bool = false
@description('true on the spoke side: route to the hub VPN gateway. The hub side must already allow gateway transit.')
param useRemoteGateways bool = false

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource peering 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-05-01' = {
  parent: vnet
  name: peeringName
  properties: {
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
    allowGatewayTransit: allowGatewayTransit
    useRemoteGateways: useRemoteGateways
    remoteVirtualNetwork: {
      id: remoteVnetId
    }
  }
}

output peeringId string = peering.id
