// Replaces the seeding Key Vault part of aif_ensure_private_network_access: private endpoint in the
// common subnet and a zone group on the integrated hub's privatelink.vaultcore.azure.net zone.
targetScope = 'resourceGroup'

param location string
param keyVaultId string
param vnetName string
param subnetName string = 'snet-esml-cmn-001'

var keyVaultName = last(split(keyVaultId, '/'))
var endpointName = 'pend-${keyVaultName}-to-${vnetName}'

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: endpointName
  location: location
  properties: {
    subnet: {
      id: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, subnetName)
    }
    privateLinkServiceConnections: [
      {
        name: '${endpointName}-connection'
        properties: {
          privateLinkServiceId: keyVaultId
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'aifactory-seeding-keyvault'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'vaultcore'
        properties: {
          privateDnsZoneId: resourceId('Microsoft.Network/privateDnsZones', 'privatelink.vaultcore.azure.net')
        }
      }
    ]
  }
}
