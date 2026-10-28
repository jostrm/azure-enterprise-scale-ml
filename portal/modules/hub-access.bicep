// Replaces the integrated-hub steps of aif_ensure_private_network_access for Simple Mode:
// aif_ensure_bastion_developer, aif_ensure_simple_hub_artifacts (IP group) and
// aif_ensure_dns_private_resolver. The VNet DNS servers are not rewritten: an ARM PUT of the VNet
// would replace its subnets, and in-VNet clients already resolve the linked private zones.
// VNet writes run one at a time (subnet, resolver, inbound endpoint, Bastion): Azure rejects a resolver or
// Bastion while the VNet is still Updating after the subnet write.
targetScope = 'resourceGroup'

param location string
param vnetName string
param vnetCidr string
param resolverSubnetCidr string
param vpnClientCidr string
param namePrefix string
param locationShort string
param scalesetNumber string
param costCenter string
param enableBastion bool

var tags = {
  CostCenter: costCenter
  Purpose: 'AIFactoryConnectivity'
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource resolverSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'snet-dns-private-resolver'
  properties: {
    addressPrefix: resolverSubnetCidr
    delegations: [
      {
        name: 'Microsoft.Network.dnsResolvers'
        properties: {
          serviceName: 'Microsoft.Network/dnsResolvers'
        }
      }
    ]
  }
}

resource resolver 'Microsoft.Network/dnsResolvers@2025-05-01' = {
  name: 'dnspr-aifactory-${locationShort}-${scalesetNumber}'
  location: location
  tags: tags
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
  }
  dependsOn: [resolverSubnet]
}

resource inbound 'Microsoft.Network/dnsResolvers/inboundEndpoints@2025-05-01' = {
  parent: resolver
  name: 'inbound-aifactory-${locationShort}-${scalesetNumber}'
  location: location
  properties: {
    ipConfigurations: [
      {
        privateIpAllocationMethod: 'Dynamic'
        subnet: {
          id: resolverSubnet.id
        }
      }
    ]
  }
}

resource bastion 'Microsoft.Network/bastionHosts@2024-05-01' = if (enableBastion) {
  name: 'bastion-${namePrefix}-${locationShort}-dev-${scalesetNumber}'
  location: location
  tags: tags
  sku: {
    name: 'Developer'
  }
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
  }
  dependsOn: [inbound]
}

resource ipGroup 'Microsoft.Network/ipGroups@2024-05-01' = {
  name: 'ipg-aifactory-${locationShort}-${scalesetNumber}'
  location: location
  tags: {
    CostCenter: costCenter
    Purpose: 'AIFactoryAccessInventory'
  }
  properties: {
    ipAddresses: [
      vnetCidr
      vpnClientCidr
    ]
  }
}

output dnsResolverInboundIp string = inbound.properties.ipConfigurations[0].privateIpAddress
