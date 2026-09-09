targetScope = 'resourceGroup'

param location string = resourceGroup().location
param gatewayName string
param vnetName string
param commonSubnetName string = 'snet-esml-cmn-001'
param vpnClientCidr string
param certificateVaultId string
param vaultDnsZoneId string
param costCenter string

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'mi-${gatewayName}'
  location: location
  tags: { CostCenter: costCenter }
}

// Private-only v2 isolation is a runtime prerequisite. Explicit deny rules override
// the default VirtualNetwork/Internet rules and prevent public backend fallback.
resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-${gatewayName}'
  location: location
  tags: { CostCenter: costCenter }
  properties: {
    securityRules: [
      {
        name: 'PrivateHttpsIn'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefixes: ['172.16.0.0/20', vpnClientCidr]
          destinationAddressPrefix: '172.16.2.10'
        }
      }
      {
        name: 'LoadBalancerProbes'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'AzureLoadBalancer'
          destinationAddressPrefix: '*'
        }
      }
      {
        name: 'DenyOtherInbound'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
        }
      }
      {
        name: 'PrivateHttpsOut'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefixes: ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']
        }
      }
      {
        name: 'AzureDnsOut'
        properties: {
          priority: 110
          direction: 'Outbound'
          access: 'Allow'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '53'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzurePlatformDNS'
        }
      }
      {
        name: 'PrivateDnsOut'
        properties: {
          priority: 120
          direction: 'Outbound'
          access: 'Allow'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '53'
          sourceAddressPrefix: '*'
          destinationAddressPrefixes: ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']
        }
      }
      {
        name: 'DenyOtherOutbound'
        properties: {
          priority: 200
          direction: 'Outbound'
          access: 'Deny'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
        }
      }
    ]
  }
}

resource gatewaySubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'snet-application-gateway'
  properties: {
    addressPrefix: '172.16.2.0/24'
    networkSecurityGroup: { id: nsg.id }
    delegations: [
      { name: 'application-gateway', properties: { serviceName: 'Microsoft.Network/applicationGateways' } }
    ]
  }
}

resource certificateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${gatewayName}-certificate'
  location: location
  tags: { CostCenter: costCenter }
  properties: {
    subnet: { id: '${vnet.id}/subnets/${commonSubnetName}' }
    privateLinkServiceConnections: [
      {
        name: 'certificate-vault'
        properties: {
          privateLinkServiceId: certificateVaultId
          groupIds: ['vault']
        }
      }
    ]
  }
}

resource certificateDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: certificateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      { name: 'vault', properties: { privateDnsZoneId: vaultDnsZoneId } }
    ]
  }
}

output principalId string = identity.properties.principalId
output identityId string = identity.id
output subnetId string = gatewaySubnet.id
