targetScope = 'subscription'

// ================================================================
// DATABASE SERVICES DEPLOYMENT - Phase 4 Implementation
// This file deploys database services including:
// - CosmosDB (MongoDB API and SQL API)
// - PostgreSQL Flexible Server
// - Redis Cache
// - SQL Server and Database
// ================================================================

// ============== PARAMETERS ==============
@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string

@description('Project number (e.g., "005")')
param projectNumber string

@description('Location for all resources')
param location string

@description('Location suffix (e.g., "weu", "swc")')
param locationSuffix string

@description('Common resource suffix (e.g., "-001")')
param commonResourceSuffix string

@description('Project-specific resource suffix')
param resourceSuffix string

@description('Tenant ID')
param tenantId string

// Resource exists flags from Azure DevOps
param cosmosDBExists bool = false
param postgreSQLExists bool = false
param redisExists bool = false
param sqlServerExists bool = false

// Enable flags from parameter files
@description('Enable Cosmos DB deployment')
param serviceSettingDeployCosmosDB bool = false

@description('Enable PostgreSQL deployment')
param serviceSettingDeployPostgreSQL bool = false

@description('Enable Redis Cache deployment')
param serviceSettingDeployRedisCache bool = false

@description('Enable SQL Database deployment')
param serviceSettingDeploySQLDatabase bool = false

// Security and networking
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param centralDnsZoneByPolicyInHub bool = false

// Required resource references
param vnetNameFull string
param vnetResourceGroupName string
param defaultSubnet string = 'snet-common'
param genaiSubnetName string = 'snet-genai'
param targetResourceGroup string
param commonResourceGroup string

// Tags
param projecttags object = {}

// IP Rules
param IPwhiteList string = ''

// Dependencies and naming
param aifactorySuffixRG string
param commonRGNamePrefix string
param uniqueInAIFenv string = ''
param prjResourceSuffixNoDash string = ''

// Database-specific parameters
// CosmosDB
param cosmosDBProvisionedThroughput int = 400
param cosmosTotalThroughputLimit int = 4000
param cosmosKind string = 'MongoDB'
param cosmosMinimalTlsVersion string = 'Tls12'

// PostgreSQL
param postgreSQLSKU object = {
  name: 'Standard_B1ms'
  tier: 'Burstable'
}
param postgreSQLStorage object = {
  storageSizeGB: 32
}
param postgreSQLVersion string = '14'
param postgreSQLHighAvailability object = {
  mode: 'Disabled'
}
param postgresAvailabilityZone string = ''
param postgresEnableCustomerManagedKey bool = false

// Redis
param redisSKU string = 'Standard'

// SQL Server
param sqlServerSKU_DTU string = 'S0'
param sqlServerTier_DTU string = 'Standard'
param sqlServerCapacity_DTU int = 10

// Access control
param useAdGroups bool = false
param technicalContactId string = ''

// Seeding Key Vault parameters
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string

// ============== VARIABLES ==============
var subscriptionIdDevTestProd = subscription().subscriptionId
var projectName = 'prj${projectNumber}'
var deploymentProjSpecificUniqueSuffix = '${projectName}${env}${uniqueInAIFenv}'

// Resource names
var cosmosDBName = 'cosmos-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
var postgreSQLName = 'psql-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
var redisName = 'redis-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
var sqlServerName = 'sql-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
var sqlDBName = 'sqldb-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
var keyvaultName = 'kv-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'

// IP Rules processing
var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []

// Network references using proper resource references
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  scope: resourceGroup(subscription().subscriptionId, vnetResourceGroupName)
  name: vnetNameFull
}

resource subnet_genai 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: genaiSubnetName
}

resource subnet_aks 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: 'aks-${projectName}'
}

var subnet_genai_ref = {
  id: subnet_genai.id
}
var subnet_aks_ref = {
  id: subnet_aks.id
}

// SQL Server SKU object
var sqlServerSKUObject_DTU = {
  name: sqlServerSKU_DTU
  tier: sqlServerTier_DTU
  capacity: sqlServerCapacity_DTU
}

// DNS configurations for private endpoints
var privateLinksDnsZones = [
  // Will be populated by private DNS zone module
]

// Access policies for principals
var p011_genai_team_lead_array = [] // Simplified - team leads would be passed as array
var p011_genai_team_lead_email_array = [] // Email addresses for admin assignment
var spAndMiArray = [] // Service principals and managed identities

// DNS configurations for private endpoints (simplified)
var var_cosmosdb_dnsConfig = [
  {
    name: cosmosDBName
    type: 'Microsoft.DocumentDB/databaseAccounts'
    groupIds: ['Sql']
    resourceId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.DocumentDB/databaseAccounts/${cosmosDBName}'
  }
]

var var_postgreSQL_dnsConfig = [
  {
    name: postgreSQLName
    type: 'Microsoft.DBforPostgreSQL/flexibleServers'
    groupIds: ['postgresqlServer']
    resourceId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.DBforPostgreSQL/flexibleServers/${postgreSQLName}'
  }
]

var var_redisCache_dnsConfig = [
  {
    name: redisName
    type: 'Microsoft.Cache/redis'
    groupIds: ['redisCache']
    resourceId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.Cache/redis/${redisName}'
  }
]

var var_sqlServer_dnsConfig = [
  {
    name: sqlServerName
    type: 'Microsoft.Sql/servers'
    groupIds: ['sqlServer']
    resourceId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.Sql/servers/${sqlServerName}'
  }
]

// Target resource group reference
resource resourceExists_struct 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: targetResourceGroup
  location: location
}

// ============== COSMOS DB ==============

module cosmosdb '../modules/databases/cosmosdb/cosmosdb.bicep' = if(!cosmosDBExists && serviceSettingDeployCosmosDB) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'CosmosDB4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: cosmosDBName
    location: location
    // Removed provisionedThroughput - using defaults from module
    enablePublicGenAIAccess: enablePublicGenAIAccess
    ipRules: (empty(ipWhitelist_array) || !enablePublicGenAIAccess || enablePublicAccessWithPerimeter) ? [] : ipWhitelist_array
    totalThroughputLimit: cosmosTotalThroughputLimit
    subnetNamePend: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    createPrivateEndpoint: enablePublicAccessWithPerimeter ? false : true
    keyvaultName: keyvaultName
    vNetRules: [
      subnet_genai_ref.id
      subnet_aks_ref.id
    ]
    kind: cosmosKind
    minimalTlsVersion: cosmosMinimalTlsVersion
    tags: projecttags
    corsRules: [
      {
        allowedOrigins: [
          'https://mlworkspace.azure.ai'
          'https://ml.azure.com'
          'https://ai.azure.com'
          'https://azure.com'
          'https://mlworkspacecanary.azure.ai'
          'https://mlworkspace.azureml-test.net'
          'https://42.${location}.instances.azureml.ms'
        ]
        allowedMethods: [
          'GET'
          'HEAD'
          'POST'
          'PUT'
          'DELETE'
          'OPTIONS'
          'PATCH'
        ]
        allowedHeaders: [
          'Content-Type'
          'Accept'
          'Authorization'
          'x-ms-blob-type'
          'x-ms-blob-content-type'
          'x-ms-version'
          'x-ms-date'
          'x-ms-copy-source'
          'Content-Length'
          'Origin'
          'Access-Control-Request-Method'
          'Access-Control-Request-Headers'
        ]
        exposedHeaders: [
          'Content-Length'
          'Content-Type'
          'Content-Range'
          'Content-Encoding'
          'Content-Language'
          'Cache-Control'
          'Last-Modified'
          'ETag'
          'x-ms-request-id'
          'x-ms-version'
          'x-ms-copy-status'
          'x-ms-copy-progress'
        ]
        maxAgeInSeconds: 2520
      }
    ]
  }
  dependsOn: [
    resourceExists_struct
  ]
}

module cosmosdbRbac '../modules/databases/cosmosdb/cosmosRbac.bicep' = if(!cosmosDBExists && serviceSettingDeployCosmosDB) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'cosmosRbac${deploymentProjSpecificUniqueSuffix}'
  params: {
    cosmosName: cosmosDBName
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    cosmosdb
  ]
}

module privateDnsCosmos '../modules/privateDns.bicep' = if(!cosmosDBExists && !centralDnsZoneByPolicyInHub && serviceSettingDeployCosmosDB && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'privateDnsLinkCosmos${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: var_cosmosdb_dnsConfig
    privateLinksDnsZones: {}
  }
  dependsOn: [
    resourceExists_struct
    cosmosdb
  ]
}

// ============== POSTGRESQL ==============

module postgreSQL '../modules/databases/postgreSQL/pgFlexibleServer.bicep' = if(!postgreSQLExists && serviceSettingDeployPostgreSQL) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'PostgreSQL4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: postgreSQLName
    location: location
    tags: projecttags
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    keyvaultName: keyvaultName
    createPrivateEndpoint: enablePublicAccessWithPerimeter ? false : true
    sku: postgreSQLSKU
    storage: postgreSQLStorage
    version: postgreSQLVersion
    tenantId: tenantId
    useAdGroups: useAdGroups
    highAvailability: postgreSQLHighAvailability
    availabilityZone: postgresAvailabilityZone
    useCMK: postgresEnableCustomerManagedKey
  }
  dependsOn: [
    resourceExists_struct
  ]
}

module postgreSQLRbac '../modules/databases/postgreSQL/pgFlexibleServerRbac.bicep' = if(!postgreSQLExists && serviceSettingDeployPostgreSQL) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'PostgreSQLRbac4${deploymentProjSpecificUniqueSuffix}'
  params: {
    postgreSqlServerName: postgreSQLName
    useAdGroups: useAdGroups
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
    adminNames: p011_genai_team_lead_email_array
  }
  dependsOn: [
    postgreSQL
  ]
}

module privateDnsPostGreSQL '../modules/privateDns.bicep' = if(!postgreSQLExists && !centralDnsZoneByPolicyInHub && serviceSettingDeployPostgreSQL && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'privateDnsLinkPostgreSQL${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: var_postgreSQL_dnsConfig
    privateLinksDnsZones: {}
  }
  dependsOn: [
    resourceExists_struct
    postgreSQL
  ]
}

// ============== REDIS CACHE ==============

module redisCache '../modules/databases/redis/redis.bicep' = if(!redisExists && serviceSettingDeployRedisCache) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'RedisCache4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: redisName
    location: location
    tags: projecttags
    skuName: redisSKU
    subnetNamePend: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    keyvaultName: keyvaultName
    createPrivateEndpoint: enablePublicAccessWithPerimeter ? false : true
  }
  dependsOn: [
    resourceExists_struct
  ]
}

module redisCacheRbac '../modules/databases/redis/redisRbac.bicep' = if(!redisExists && serviceSettingDeployRedisCache) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'RedisCacheRbac4${deploymentProjSpecificUniqueSuffix}'
  params: {
    redisName: redisName
    useAdGroups: useAdGroups
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    redisCache
  ]
}

module privateDnsRedisCache '../modules/privateDns.bicep' = if(!redisExists && !centralDnsZoneByPolicyInHub && serviceSettingDeployRedisCache && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'privateDnsLinkRedisCache${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: var_redisCache_dnsConfig
    privateLinksDnsZones: {}
  }
  dependsOn: [
    resourceExists_struct
    redisCache
  ]
}

// ============== SQL SERVER & DATABASE ==============

module sqlServer '../modules/databases/sqldatabase/sqldatabase.bicep' = if(!sqlServerExists && serviceSettingDeploySQLDatabase) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'SqlServer4${deploymentProjSpecificUniqueSuffix}'
  params: {
    serverName: sqlServerName
    databaseName: sqlDBName
    location: location
    tags: projecttags
    skuObject: empty(sqlServerSKUObject_DTU) ? {} : sqlServerSKUObject_DTU
    subnetNamePend: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    keyvaultName: keyvaultName
    createPrivateEndpoint: enablePublicAccessWithPerimeter ? false : true
  }
  dependsOn: [
    resourceExists_struct
  ]
}

module sqlRbac '../modules/databases/sqldatabase/sqldatabaseRbac.bicep' = if(!sqlServerExists && serviceSettingDeploySQLDatabase) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'SqlServerRbac4${deploymentProjSpecificUniqueSuffix}'
  params: {
    sqlServerName: sqlServerName
    useAdGroups: useAdGroups
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    sqlServer
  ]
}

module privateDnsSql '../modules/privateDns.bicep' = if(!sqlServerExists && !centralDnsZoneByPolicyInHub && serviceSettingDeploySQLDatabase && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'privateDnsLinkSqlServer${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: var_sqlServer_dnsConfig
    privateLinksDnsZones: {}
  }
  dependsOn: [
    resourceExists_struct
    sqlServer
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs simplified to avoid conditional module reference issues
// Resource information should be retrieved through Azure CLI queries after deployment

@description('Cosmos DB deployment status')
output cosmosDBDeployed bool = (!cosmosDBExists && serviceSettingDeployCosmosDB)

@description('PostgreSQL deployment status')
output postgreSQLDeployed bool = (!postgreSQLExists && serviceSettingDeployPostgreSQL)

@description('Redis Cache deployment status')
output redisCacheDeployed bool = (!redisExists && serviceSettingDeployRedisCache)

@description('SQL Server deployment status')
output sqlServerDeployed bool = (!sqlServerExists && serviceSettingDeploySQLDatabase)
