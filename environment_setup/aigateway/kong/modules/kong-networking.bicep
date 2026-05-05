// ============================================================================
// Kong Networking - Creates subnet in existing VNet for ACI injection
// ============================================================================

@description('Existing VNet name')
param vnetName string

@description('Kong subnet name')
param kongSubnetName string

@description('Kong subnet CIDR (min /28)')
param kongSubnetCidr string

@description('Location')
param location string

// ============================================================================
// Reference existing VNet
// ============================================================================
resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' existing = {
  name: vnetName
}

// ============================================================================
// NSG for Kong subnet
// ============================================================================
resource kongNsg 'Microsoft.Network/networkSecurityGroups@2024-01-01' = {
  name: 'nsg-${kongSubnetName}'
  location: location
  properties: {
    securityRules: [
      {
        name: 'Allow-Kong-Proxy-Inbound'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '8000'
          description: 'Allow inbound traffic to Kong proxy port from VNet'
        }
      }
      {
        name: 'Allow-Kong-ProxySSL-Inbound'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '8443'
          description: 'Allow inbound HTTPS traffic to Kong proxy port from VNet'
        }
      }
      {
        name: 'Deny-Kong-Admin-External'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Deny'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '8001'
          description: 'Deny external access to Kong admin API'
        }
      }
      {
        name: 'Allow-Kong-Admin-VNet'
        properties: {
          priority: 150
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '8001'
          description: 'Allow VNet access to Kong admin API'
        }
      }
      {
        name: 'Allow-HTTPS-Outbound'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '443'
          description: 'Allow outbound HTTPS to VNet (Azure OpenAI private endpoint)'
        }
      }
    ]
  }
}

// ============================================================================
// Subnet for Kong ACI (delegated to Microsoft.ContainerInstance/containerGroups)
// ============================================================================
resource kongSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-01-01' = {
  parent: vnet
  name: kongSubnetName
  properties: {
    addressPrefix: kongSubnetCidr
    networkSecurityGroup: {
      id: kongNsg.id
    }
    delegations: [
      {
        name: 'Microsoft.ContainerInstance.containerGroups'
        properties: {
          serviceName: 'Microsoft.ContainerInstance/containerGroups'
        }
      }
    ]
    privateEndpointNetworkPolicies: 'Disabled'
  }
}

// ============================================================================
// Outputs
// ============================================================================
output kongSubnetId string = kongSubnet.id
output kongSubnetName string = kongSubnet.name
output nsgId string = kongNsg.id
