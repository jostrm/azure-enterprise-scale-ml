// Replaces aif_ensure_vpn_access_hub (integrated mode): GatewaySubnet, zone-redundant Standard public IP
// for VPN transport only, VpnGw1AZ with Entra-authenticated OpenVPN point-to-site. Optional and billable.
targetScope = 'resourceGroup'

param location string
param vnetName string
param gatewaySubnetCidr string
param vnetCidr string
param vpnClientCidr string
param locationShort string
param scalesetNumber string
param costCenter string

var gatewayName = 'vpngw-aifactory-access-${locationShort}-${scalesetNumber}'
var tags = {
  CostCenter: costCenter
  Purpose: 'AIFactoryConnectivity'
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource gatewaySubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'GatewaySubnet'
  properties: {
    addressPrefix: gatewaySubnetCidr
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${gatewayName}-pip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  zones: [
    '1'
    '2'
    '3'
  ]
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource gateway 'Microsoft.Network/virtualNetworkGateways@2024-05-01' = {
  name: gatewayName
  location: location
  tags: tags
  properties: {
    gatewayType: 'Vpn'
    vpnType: 'RouteBased'
    vpnGatewayGeneration: 'Generation1'
    sku: {
      name: 'VpnGw1AZ'
      tier: 'VpnGw1AZ'
    }
    ipConfigurations: [
      {
        name: 'default'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: gatewaySubnet.id
          }
          publicIPAddress: {
            id: publicIp.id
          }
        }
      }
    ]
    vpnClientConfiguration: {
      vpnClientAddressPool: {
        addressPrefixes: [
          vpnClientCidr
        ]
      }
      vpnClientProtocols: [
        'OpenVPN'
      ]
      vpnAuthenticationTypes: [
        'AAD'
      ]
      aadTenant: '${environment().authentication.loginEndpoint}${tenant().tenantId}'
      aadAudience: 'c632b3df-fb67-4d84-bdcf-b95ad541b5c8'
      aadIssuer: 'https://sts.windows.net/${tenant().tenantId}/'
    }
    customRoutes: {
      addressPrefixes: [
        vnetCidr
      ]
    }
  }
}
