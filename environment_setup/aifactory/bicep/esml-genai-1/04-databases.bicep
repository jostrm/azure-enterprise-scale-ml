targetScope = 'subscription'

// ================================================================
// DATABASE SERVICES DEPLOYMENT - Phase 4 Implementation
// This file deploys database services including:
// - CosmosDB (MongoDB API and SQL API)
// - PostgreSQL Flexible Server
// - Redis Cache
// - SQL Server and Database
//  inputKeyvault, inputKeyvaultResourcegroup, inputKeyvaultSubscription, projectServicePrincipleAppID_SeedingKeyvaultName, projectServicePrincipleOID_SeedingKeyvaultName, projectServicePrincipleSecret_SeedingKeyvaultName
// ================================================================
@description('Enable Cosmos DB free tier (one per subscription)')
param enableCosmosFreeTier bool = false
// ============================================================================
// SKU for services
// ============================================================================
// PostgreSQL
param postgreSQLSKU object = {
  name: 'Standard_B1ms'
  tier: 'Burstable'
}
// Redis
param redisSKU string = 'Standard'
// SQL Server
param sqlServerSKU_DTU string = 'S0'
param sqlServerTier_DTU string = 'Standard'

@description('Diagnostic setting level for monitoring and logging')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

// CMK Parameters
param cmk bool = false
param cmkKeyName string = ''
param admin_bicep_kv_fw string = ''
param admin_bicep_kv_fw_rg string = ''
param admin_bicep_input_keyvault_subscription string = ''

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
param postGresAdminEmails string = ''

// Resource exists flags from Azure DevOps
param cosmosDBExists bool = false
param postgreSQLExists bool = false
param redisExists bool = false
param sqlServerExists bool = false

// Enable flags from parameter files
@description('Enable Cosmos DB deployment')
param enableCosmosDB bool = false

@description('Enable PostgreSQL deployment')
param enablePostgreSQL bool = false

@description('Enable Redis Cache deployment')
param enableRedisCache bool = false

@description('Enable SQL Database deployment')
param enableSQLDatabase bool = false

@description('Enable AI Foundry Caphost feature')
param enableAFoundryCaphost bool = false

@description('Enable AI Foundry V2.1')
param enableAIFoundry bool = false

// Security and networking
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param centralDnsZoneByPolicyInHub bool = false

// ============================================================================
// PS-Networking: Needs to be here, even if not used, since .JSON file
// ============================================================================
@description('Required subnet IDs from subnet calculator')
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string
@description('Optional subnets from subnet calculator')
param aca2SubnetId string = ''
param aks2SubnetId string = ''
@description('if projectype is not genai-1, but instead all')
param dbxPubSubnetName string = ''
param dbxPrivSubnetName string = ''

// Users
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''

// Networking parameters for calculation
param vnetNameBase string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''

// Private DNS configuration
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// Resource group configuration
param commonResourceGroup_param string = ''

// Tags
param tagsProject object = {}
param tags object = {}

// IP Rules
param IPwhiteList string = ''

// Dependencies and naming
param aifactorySuffixRG string
param commonRGNamePrefix string
param prjResourceSuffixNoDash string = ''

// Database-specific parameters
// CosmosDB
param cosmosDBProvisionedThroughput int = 400
param cosmosTotalThroughputLimit int = 4000
@allowed([ 'GlobalDocumentDB', 'MongoDB'])
param cosmosKind string = 'GlobalDocumentDB'
param cosmosMinimalTlsVersion string = 'Tls12'

// PostgreSQL
param postgreSQLStorage object = {
  storageSizeGB: 32
}
param postgreSQLVersion string = '14'
param postgreSQLHighAvailability object = {
  mode: 'Disabled'
}
param postgresAvailabilityZone string = ''
param postgresEnableCustomerManagedKey bool = false

// Redis - other Redis parameters would go here if needed

// SQL Server
param sqlServerCapacity_DTU int = 10

// Access control
param useAdGroups bool = false

// Seeding Key Vault parameters
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
param projectServicePrincipleOID_SeedingKeyvaultName string
param aifactorySalt10char string = ''
@description('Random value for deployment uniqueness')
param randomValue string
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'
@description('Common resource name identifier. Default is "esml-common"')
param commonResourceName string = 'esml-common'

// ============== VARIABLES ==============
var subscriptionIdDevTestProd = subscription().subscriptionId

// Calculated variables
var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

// Networking calculations
var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup

// Private DNS calculations
var privDnsResourceGroupName = (!empty(privDnsResourceGroup_param) && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (!empty(privDnsSubscription_param) && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd

var deploymentProjSpecificUniqueSuffix = '${projectNumber}${env}${targetResourceGroup}'

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('04-naming-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    env: env
    projectNumber: projectNumber
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    aifactorySalt10char: aifactorySalt10char
    randomValue: randomValue
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    technicalAdminsObjectID: technicalAdminsObjectID
    technicalAdminsEmail: technicalAdminsEmail
    commonResourceGroupName: commonResourceGroup
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    acaSubnetId: acaSubnetId
    aksSubnetId:aksSubnetId
    genaiSubnetId:genaiSubnetId
    aca2SubnetId: aca2SubnetId
    aks2SubnetId: aks2SubnetId
    postGresAdminEmails:postGresAdminEmails
  }
}

//var miACAName = namingConvention.outputs.miACAName
var miPrjName = namingConvention.outputs.miPrjName
var p011_genai_team_lead_email_array = namingConvention.outputs.p011_genai_team_lead_email_array
var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array

var postGresAdminEmailsArray = namingConvention.outputs.postGresAdminEmails

var defaultSubnet = namingConvention.outputs.defaultSubnet

// Import specific names needed for database deployment
var cosmosDBName = namingConvention.outputs.cosmosDBName
var postgreSQLName = namingConvention.outputs.postgreSQLName
var redisName = namingConvention.outputs.redisName
var sqlServerName = namingConvention.outputs.sqlServerName
var sqlDBName = namingConvention.outputs.sqlDBName
var keyvaultName = namingConvention.outputs.keyvaultName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName

// Not used - do dependency
//var uniqueInAIFenv = namingConvention.outputs.uniqueInAIFenv
//var randomSalt = namingConvention.outputs.randomSalt
//var aksSubnetName = namingConvention.outputs.aksSubnetName
//var acaSubnetName = namingConvention.outputs.acaSubnetName
//var genaiSubnetName = namingConvention.outputs.genaiSubnetName
//var genaiName = namingConvention.outputs.genaiName

// IP Rules processing
var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []

// SQL Server SKU object
var sqlServerSKUObject_DTU = {
  name: sqlServerSKU_DTU
  tier: sqlServerTier_DTU
  capacity: sqlServerCapacity_DTU
}


module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  name: take('04-getPrivDnsZ-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

// Log Analytics workspace reference for diagnostics
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laWorkspaceName
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// Assumes the principals exists.
module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('04-getMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

// Array vars - use principal IDs from helper modules
var var_miPrj_PrincipalId = getProjectMIPrincipalId.outputs.principalId

resource externalKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}


// Access policies for principals
module spAndMI2Array '../modules/spAndMiArray.bicep' = {
  name: take('04-spAndMI2Array-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    managedIdentityOID: var_miPrj_PrincipalId
    servicePrincipleOIDFromSecret: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
  }
  dependsOn: [
      getProjectMIPrincipalId
  ]
}

#disable-next-line BCP318
var spAndMiArray = spAndMI2Array.outputs.spAndMiArray
#disable-next-line BCP318
var var_cosmosdb_dnsConfig = cosmosdb.outputs.dnsConfig
#disable-next-line BCP318
var var_postgreSQL_dnsConfig = postgreSQL.outputs.dnsConfig
#disable-next-line BCP318
var var_redisCache_dnsConfig = redisCache.outputs.dnsConfig
#disable-next-line BCP318
var var_sqlServer_dnsConfig = sqlServer.outputs.dnsConfig

resource existingTargetRG 'Microsoft.Resources/resourceGroups@2025-04-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============== CMK CONFIGURATION ==============
var cmkIdentityId = resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)
// Get Key Vault base URI and construct full key URI for Cosmos DB
var cmkKvBaseUriRaw = cmk? reference(resourceId(admin_bicep_input_keyvault_subscription, admin_bicep_kv_fw_rg, 'Microsoft.KeyVault/vaults', admin_bicep_kv_fw), '2022-07-01').vaultUri: ''
var cmkKvBaseUri = cmk && endsWith(cmkKvBaseUriRaw, '/') ? substring(cmkKvBaseUriRaw, 0, length(cmkKvBaseUriRaw) - 1) : cmkKvBaseUriRaw
// Full key URI format: https://<vault>.vault.azure.net/keys/<keyname> (no version for auto-rotation)
var cmkKvUri = cmk ? '${cmkKvBaseUri}/keys/${cmkKeyName}' : ''
// ============== COSMOS DB ==============

module cosmosdb '../modules/databases/cosmosdb/cosmosdb.bicep' = if(!cosmosDBExists && (enableCosmosDB || (enableAFoundryCaphost && enableAIFoundry))) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-CosmosDB4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    logAnalyticsWorkspaceResourceId: laWorkspaceName
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: !empty(miPrjName) ? [resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)] : []
    }
    name: cosmosDBName
    location: location
    enableFreeTier: enableCosmosFreeTier
    databaseAccountOfferType: 'Standard'
    useCMK: cmk
    keyVaultKeyUri: cmkKvUri
    cmkUserAssignedIdentityId: cmk ? cmkIdentityId : ''
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
      genaiSubnetId
      aksSubnetId
    ]
    kind: (enableAFoundryCaphost && enableAIFoundry) ? 'GlobalDocumentDB' : cosmosKind
    minimalTlsVersion: cosmosMinimalTlsVersion
    tags: tagsProject
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
    existingTargetRG
  ]
}

module cosmosdbRbac '../modules/databases/cosmosdb/cosmosRbac.bicep' = if(!cosmosDBExists && (enableCosmosDB || (enableAFoundryCaphost && enableAIFoundry))) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-cosmosRbac${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    cosmosName: cosmosDBName
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    cosmosdb
    spAndMI2Array
  ]
}

module privateDnsCosmos '../modules/privateDns.bicep' = if(!cosmosDBExists && !centralDnsZoneByPolicyInHub && (enableCosmosDB || (enableAFoundryCaphost && enableAIFoundry)) && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-privDnsCosmos${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_cosmosdb_dnsConfig
    privateLinksDnsZones:privateLinksDnsZones
  }
  dependsOn: [
    existingTargetRG
    cosmosdb
  ]
}

// ============== POSTGRESQL ==============

module postgreSQL '../modules/databases/postgreSQL/pgFlexibleServer.bicep' = if(!postgreSQLExists && enablePostgreSQL) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-PostgreSQL4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: postgreSQLName
    location: location
    tags: tagsProject
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    keyvaultName: keyvaultName
    createPrivateEndpoint: enablePublicAccessWithPerimeter ? false : true
    sku: postgreSQLSKU
    storage: postgreSQLStorage
    version: postgreSQLVersion
    tenantId: tenant().tenantId
    useAdGroups: useAdGroups
    highAvailability: postgreSQLHighAvailability
    availabilityZone: postgresAvailabilityZone
    useCMK: cmk
    keyVaultKeyId: cmk ? cmkKvUri : ''
    cmkUserAssignedIdentityId: cmk ? cmkIdentityId : ''
  }
  dependsOn: [
    existingTargetRG
  ]
}

module postgreSQLRbac '../modules/databases/postgreSQL/pgFlexibleServerRbac.bicep' = if(!postgreSQLExists && enablePostgreSQL) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-PostgreSQLRbac4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    postgreSqlServerName: postgreSQLName
    useAdGroups: useAdGroups
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
    adminNames: postGresAdminEmailsArray
  }
  dependsOn: [
    postgreSQL
    spAndMI2Array
  ]
}

module privateDnsPostGreSQL '../modules/privateDns.bicep' = if(!postgreSQLExists && !centralDnsZoneByPolicyInHub && enablePostgreSQL && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-privDnsPGres${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_postgreSQL_dnsConfig
    privateLinksDnsZones:privateLinksDnsZones
  }
  dependsOn: [
    existingTargetRG
    postgreSQL
  ]
}

// ============== REDIS CACHE ==============

module redisCache '../modules/databases/redis/redis.bicep' = if(!redisExists && enableRedisCache) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-RedisCache4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: redisName
    location: location
    tags: tagsProject
    skuName: redisSKU
    subnetNamePend: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    keyvaultName: keyvaultName
    createPrivateEndpoint: enablePublicAccessWithPerimeter ? false : true
  }
  dependsOn: [
    existingTargetRG
  ]
}

module redisCacheRbac '../modules/databases/redis/redisRbac.bicep' = if(!redisExists && enableRedisCache) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-RedisCacheRbac4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    redisName: redisName
    useAdGroups: useAdGroups
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    redisCache
    spAndMI2Array
  ]
}

module privateDnsRedisCache '../modules/privateDns.bicep' = if(!redisExists && !centralDnsZoneByPolicyInHub && enableRedisCache && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-privDnsRedis${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_redisCache_dnsConfig
    privateLinksDnsZones:privateLinksDnsZones
  }
  dependsOn: [
    existingTargetRG
    redisCache
  ]
}

// ============== SQL SERVER & DATABASE ==============

module sqlServer '../modules/databases/sqldatabase/sqldatabase.bicep' = if(!sqlServerExists && enableSQLDatabase) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-SqlServer4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    serverName: sqlServerName
    databaseName: sqlDBName
    location: location
    tags: tagsProject
    useCMK: cmk
    keyVaultKeyUri: cmk ? cmkKvUri : ''
    cmkUserAssignedIdentityId: cmk ? cmkIdentityId : ''
    skuObject: empty(sqlServerSKUObject_DTU) ? {} : sqlServerSKUObject_DTU
    subnetNamePend: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    keyvaultName: keyvaultName
    createPrivateEndpoint: enablePublicAccessWithPerimeter ? false : true
  }
  dependsOn: [
    existingTargetRG
  ]
}

module sqlRbac '../modules/databases/sqldatabase/sqldatabaseRbac.bicep' = if(!sqlServerExists && enableSQLDatabase) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-SqlServerRbac4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    sqlServerName: sqlServerName
    useAdGroups: useAdGroups
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    sqlServer
    spAndMI2Array
  ]
}

module privateDnsSql '../modules/privateDns.bicep' = if(!sqlServerExists && !centralDnsZoneByPolicyInHub && enableSQLDatabase && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-privDnsSQL${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_sqlServer_dnsConfig
    privateLinksDnsZones:privateLinksDnsZones
  }
  dependsOn: [
    existingTargetRG
    sqlServer
  ]
}

// ============== DIAGNOSTIC SETTINGS ==============

// Cosmos DB Diagnostic Settings
module cosmosDbDiagnostics '../modules/diagnostics/cosmosDbDiagnostics.bicep' = if (!cosmosDBExists && (enableCosmosDB || (enableAFoundryCaphost && enableAIFoundry))) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-diagCosmosDB-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    cosmosDbAccountName: cosmosDBName
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    cosmosdb
  ]
}

// PostgreSQL Diagnostic Settings
module postgresqlDiagnostics '../modules/diagnostics/postgresqlDiagnostics.bicep' = if (!postgreSQLExists && enablePostgreSQL) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-diagPostgreSQL-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    postgresqlServerName: postgreSQLName
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    postgreSQL
  ]
}

// Redis Cache Diagnostic Settings
module redisCacheDiagnostics '../modules/diagnostics/redisCacheDiagnostics.bicep' = if (!redisExists && enableRedisCache) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-diagRedis-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    redisCacheName: redisName
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    redisCache
  ]
}

// SQL Database Diagnostic Settings
module sqlDatabaseDiagnostics '../modules/diagnostics/sqlDatabaseDiagnostics.bicep' = if (!sqlServerExists && enableSQLDatabase) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('04-diagSQLDB-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    sqlServerName: sqlServerName
    sqlDatabaseName: sqlDBName
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    sqlServer
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs simplified to avoid conditional module reference issues
// Resource information should be retrieved through Azure CLI queries after deployment

@description('Cosmos DB deployment status')
output cosmosDBDeployed bool = (!cosmosDBExists && (enableCosmosDB || (enableAFoundryCaphost && enableAIFoundry)))

@description('PostgreSQL deployment status')
output postgreSQLDeployed bool = (!postgreSQLExists && enablePostgreSQL)

@description('Redis Cache deployment status')
output redisCacheDeployed bool = (!redisExists && enableRedisCache)

@description('SQL Server deployment status')
output sqlServerDeployed bool = (!sqlServerExists && enableSQLDatabase)
