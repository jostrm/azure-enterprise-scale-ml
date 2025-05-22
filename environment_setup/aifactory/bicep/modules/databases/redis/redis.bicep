@description('Required. The name of the Redis cache resource. Start and end with alphanumeric. Consecutive hyphens not allowed')
@maxLength(63)
@minLength(1)
param name string

param connectionStringKey string = 'aifactory-proj-redis-con-string'
param redisVersion string = '7.0' //'7.2'
param minimumTlsVersion string = '1.2'
param vnetName string
param subnetNamePend string
param vnetResourceGroupName string
param location string
param tags object
@description('The name of an existing keyvault, that it will be used to store secrets (connection string)' )
param keyvaultName string
param systemAssignedIdentity bool = true // Enables system assigned managed identity on the resource
param userAssignedIdentities object = {} // Optional. The ID(s) to assign to the resource.

@description('Optional. Specifies whether the non-ssl Redis server port (6379) is enabled.')
param enableNonSslPort bool = false

@minValue(1)
@description('Optional. The number of replicas to be created per primary.')
param replicasPerMaster int = 1

@minValue(1)
@description('Optional. The number of replicas to be created per primary.')
param replicasPerPrimary int = 1

@minValue(1)
@description('Optional. The number of shards to be created on a Premium Cluster Cache.')
param shardCount int = 1

@allowed([
  0
  1
  2
  3
  4
  5
  6
])
@description('Optional. The size of the Redis cache to deploy. Valid values: for C (Basic/Standard) family (0, 1, 2, 3, 4, 5, 6), for P (Premium) family (1, 2, 3, 4).')
param capacity int = 2

@allowed([
  'Basic'
  'Premium'
  'Standard'
])
@description('Optional, default is Standard. The type of Redis cache to deploy.')
param skuName string = 'Standard'

@description('Optional. The full resource ID of a subnet in a virtual network to deploy the Redis cache in. Example format: /subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/Microsoft.{Network|ClassicNetwork}/VirtualNetworks/vnet1/subnets/subnet1.')
param subnetId string = ''

@description('Optional. The name of the diagnostic setting, if deployed.')
param diagnosticSettingsName string = '${name}-diagnosticSettings'

@description('Optional. Resource ID of the diagnostic log analytics workspace. For security reasons, it is recommended to set diagnostic settings to send data to either storage account, log analytics workspace or event hub.')
param diagnosticWorkspaceId string = ''

@description('Optional. The name of logs that will be streamed. "allLogs" includes all possible logs for the resource.')
@allowed([
  'allLogs'
  'ConnectedClientList'
])
param diagnosticLogCategoriesToEnable array = [
  'allLogs'
]

@description('Optional. The name of metrics that will be streamed.')
@allowed([
  'AllMetrics'
])
param diagnosticMetricsToEnable array = [
  'AllMetrics'
]

@description('Has the resource private endpoint?')
param createPrivateEndpoint bool


@description('Optional. Redis configuration. See https://docs.microsoft.com/azure/azure-cache-for-redis/cache-configure for valid values.')
param redisConfiguration object = {
  'maxmemory-policy': 'volatile-lru'
  'maxmemory-reserved': '50'
  'maxfragmentationmemory-reserved': '50'
}

// Add an update channel parameter
@allowed([
  'None'
  'Patch'
  'Minor'
  'Major'
])
@description('Optional. Specifies which Redis updates are automatically applied. Default is None.')
param updateChannel string = 'None'

// Add a zonal allocation policy parameter for Premium SKUs
@allowed([
  ''
  'Enabled'
  'Disabled'
])
@description('Optional. Specifies distribution of Redis cache nodes across Availability Zones. Only supported for Premium SKUs.')
param zonalAllocationPolicy string = ''

// Add option for disabling access key authentication (useful for AAD auth)
@description('Optional. Disables access via Redis keys. Requires AAD integration.')
param disableAccessKeyAuthentication bool = false

// Add AAD integration option
@description('Optional. Enables Azure Active Directory authentication.')
param enableAadIntegration bool = false

var diagnosticsLogsSpecified = [for category in filter(diagnosticLogCategoriesToEnable, item => item != 'allLogs'): {
  category: category
  enabled: true
}]

var diagnosticsLogs = contains(diagnosticLogCategoriesToEnable, 'allLogs') ? [
  {
    categoryGroup: 'allLogs'
    enabled: true
  }
] : diagnosticsLogsSpecified

var diagnosticsMetrics = [for metric in diagnosticMetricsToEnable: {
  category: metric
  timeGrain: null
  enabled: true
}]

var identityType = systemAssignedIdentity 
  ? (!empty(userAssignedIdentities) ? 'SystemAssigned, UserAssigned' : 'SystemAssigned') 
  : (!empty(userAssignedIdentities) ? 'UserAssigned' : 'None')

var identity = identityType != 'None' ? {
  type: identityType
  userAssignedIdentities: !empty(userAssignedIdentities) ? userAssignedIdentities : null
} : null

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
}

/*
Default values for common Redis configuration settings
Support for features like update channels and zonal allocation
Include options for modern authentication methods
Make explicit some default values that were implicit before
*/
resource redisCache 'Microsoft.Cache/redis@2024-11-01' = {
  name: name
  location: location
  tags: tags
  identity: identity
  properties: {
    enableNonSslPort: enableNonSslPort
    minimumTlsVersion: minimumTlsVersion
    publicNetworkAccess: createPrivateEndpoint ? 'Disabled' : 'Enabled'
    redisConfiguration: union(
      redisConfiguration,
      enableAadIntegration ? { 'aad-enabled': 'true' } : {}
    )
    redisVersion: redisVersion
    replicasPerMaster: skuName == 'Premium' ? replicasPerMaster : null
    replicasPerPrimary: skuName == 'Premium' ? replicasPerPrimary : null
    shardCount: skuName == 'Premium' ? shardCount : null
    disableAccessKeyAuthentication: disableAccessKeyAuthentication
    updateChannel: updateChannel
    zonalAllocationPolicy: skuName == 'Premium' ? zonalAllocationPolicy : null
    sku: {
      capacity: capacity
      family: skuName == 'Premium' ? 'P' : 'C'
      name: skuName
    }
    subnetId: !empty(subnetId) ? subnetId : null
  }
  zones: skuName == 'Premium' ? pickZones('Microsoft.Cache', 'redis', location, 1) : null
}

@description('Key Vault: REDIS')
resource redisConnectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: connectionStringKey
  properties: {
    value: '${redisCache.properties.hostName},password=${redisCache.listKeys().primaryKey},ssl=True,abortConnect=False' //'${name}.redis.cache.windows.net,abortConnect=false,ssl=true,password=${listKeys(redis.id, redis.apiVersion).primaryKey}'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource redisCache_diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if ( !empty(diagnosticWorkspaceId) ) {
  name: diagnosticSettingsName
  properties: {
    storageAccountId:  null 
    workspaceId: empty(diagnosticWorkspaceId) ? null : diagnosticWorkspaceId
    eventHubAuthorizationRuleId: null 
    eventHubName:  null
    metrics: empty(diagnosticWorkspaceId) ? null : diagnosticsMetrics
    logs:  empty(diagnosticWorkspaceId) ? null : diagnosticsLogs
  }
  scope: redisCache
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnetPend 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetNamePend
  parent: vnet
}

resource pendRedis 'Microsoft.Network/privateEndpoints@2024-05-01' = if(createPrivateEndpoint) {
  name: 'pend-redis-${name}'
  location: location
  properties: {
    subnet: {
      id: subnetPend.id
    }
    privateLinkServiceConnections: [
      {
        name: 'pend-redis-${name}'
        properties: {
          privateLinkServiceId: redisCache.id
          groupIds: [
            'redisCache'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}

@description('The resource name.')
output name string = redisCache.name

@description('The resource ID.')
output resourceId string = redisCache.id

@description('Redis hostname.')
output hostName string = redisCache.properties.hostName

@description('Redis SSL port.')
output sslPort int = redisCache.properties.sslPort

@description('The full resource ID of a subnet in a virtual network where the Redis cache was deployed in.')
output subnetId string = !empty(subnetId) ? redisCache.properties.subnetId : ''

@description('The location the resource was deployed into.')
output location string = redisCache.location

@description('The name of the secret in keyvault, holding the connection string to redis.')
output redisConnectionStringSecretName string = redisConnectionStringSecret.name
output dnsConfig array = [
  {
    name: createPrivateEndpoint? redisCache.name: ''
    type: 'redis'
    id:createPrivateEndpoint? redisCache.id: ''
  }
]


