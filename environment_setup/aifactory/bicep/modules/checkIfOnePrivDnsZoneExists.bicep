param resourceGroupName string
param resourceName string
param resourceType string

resource existingPrivDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

//output exists bool = (empty(existingPrivDnsZone)) ? false : !empty(existingPrivDnsZone.id)
output exists bool = !empty(existingPrivDnsZone)
