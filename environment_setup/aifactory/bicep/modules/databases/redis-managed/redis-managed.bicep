@description('Azure Managed Redis is supported here only in commercial Azure. Disable enableRedisManaged in other clouds until service availability and DNS suffixes are verified.')
@allowed(['AzureCloud'])
param azureCloud string = any(environment().name)

@minLength(1)
@maxLength(60)
param name string
param location string
param tags object = {}
param vnetName string
param vnetResourceGroupName string
param subnetNamePend string

@description('Supported Managed Redis subset; capacity is not applicable. Enterprise_E and EnterpriseFlash_F SKUs are intentionally excluded.')
@allowed(['Balanced_B0', 'Balanced_B1', 'Balanced_B5', 'Balanced_B10'])
param skuName string = 'Balanced_B1'

@description('Enabled to Disabled is not supported. This module never deletes/recreates a cluster.')
@allowed(['Enabled', 'Disabled'])
param highAvailability string = 'Enabled'

@allowed(['AllKeysLFU', 'AllKeysLRU', 'AllKeysRandom', 'NoEviction', 'VolatileLFU', 'VolatileLRU', 'VolatileRandom', 'VolatileTTL'])
param evictionPolicy string = 'NoEviction'

@description('Changing OSSCluster or EnterpriseCluster requires recreation. NoCluster is limited to 25 GB.')
@allowed(['OSSCluster', 'EnterpriseCluster', 'NoCluster'])
param clusteringPolicy string = 'OSSCluster'

@description('Existing project managed identity and optional project service principal object IDs; not Entra groups or application IDs.')
@minLength(1)
param principalIds array
param logAnalyticsWorkspaceId string = ''

resource cluster 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  properties: {
    highAvailability: highAvailability
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
  }
}

resource database 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: cluster
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    port: 10000
    accessKeysAuthentication: 'Disabled'
    clusteringPolicy: clusteringPolicy
    evictionPolicy: evictionPolicy
    persistence: {
      aofEnabled: false
      rdbEnabled: false
    }
  }
}

resource accessAssignments 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2025-07-01' = [for principalId in union(principalIds, principalIds): {
  parent: database
  name: replace(guid(database.id, principalId), '-', '')
  properties: {
    accessPolicyName: 'default'
    user: {
      objectId: principalId
    }
  }
}]

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: subnetNamePend
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${name}-pend'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${name}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${name}-pend'
        properties: {
          privateLinkServiceId: cluster.id
          groupIds: ['redisEnterprise']
        }
      }
    ]
  }
  dependsOn: [database]
}

resource clusterDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(logAnalyticsWorkspaceId)) {
  name: '${name}-metrics'
  scope: cluster
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

resource databaseDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(logAnalyticsWorkspaceId)) {
  name: '${name}-connections'
  scope: database
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        category: 'ConnectionEvents'
        enabled: true
      }
    ]
  }
}

output resourceId string = cluster.id
output name string = cluster.name
output hostName string = cluster.properties.hostName
output port int = database.properties.port
output dnsConfig array = [
  {
    name: privateEndpoint.name
    type: 'redisManaged'
    id: cluster.id
  }
]
