// ============================================================================
// AI Factory - Foundation Deployment (01-foundation.bicep)
// ============================================================================
// This deploys the foundational infrastructure components required by all other deployments
// Dependencies: None (first deployment)
// Components: Resource Groups, Managed Identities, Private DNS zones, Basic RBAC

targetScope = 'subscription'

// ============================================================================
// PARAMETERS - Core Configuration
// ============================================================================

@description('AI Factory version information')
param aifactoryVersionMajor int = 1
param aifactoryVersionMinor int = 22
var activeVersion = 122

@description('Use Azure AD Groups for RBAC')
param useAdGroups bool = false

// ============================================================================
// PARAMETERS - Environment & Location
// ============================================================================

@description('Environment: dev, test, or prod')
@allowed(['dev', 'test', 'prod'])
param env string

@description('Azure region location')
param location string

@description('Location suffix (e.g., "weu", "swc")')
param locationSuffix string

@description('Project number (e.g., "005")')
param projectNumber string

// ============================================================================
// PARAMETERS - Resource Existence Flags
// ============================================================================

@description('Existing flags')
param miACAExists bool = false
param miPrjExists bool = false
param keyvaultExists bool = false
param storageAccount1001Exists bool = false
param zoneAzurecontainerappsExists bool = false
param zonePostgresExists bool = false
param zoneSqlExists bool = false
param zoneMongoExists bool = false
param zoneRedisExists bool = false

var resourceExists = {
  miACA: miACAExists
  miPrj: miPrjExists
  keyvault: keyvaultExists
  storageAccount1001: storageAccount1001Exists
}

// ============================================================================
// PARAMETERS - Networking
// ============================================================================

@description('Virtual network configuration')
param vnetNameBase string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''

@description('Required subnet IDs from subnet calculator')
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''

@description('Private DNS configuration')
param centralDnsZoneByPolicyInHub bool = false
param privateDnsAndVnetLinkAllGlobalLocation bool = false
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// ============================================================================
// PARAMETERS - Resource Groups & Naming
// ============================================================================

@description('Resource group naming')
param commonRGNamePrefix string
param aifactorySuffixRG string
param commonResourceSuffix string
param resourceSuffix string

@description('Common resource configuration')
param commonResourceGroup_param string = ''

// ============================================================================
// PARAMETERS - RBAC & Security
// ============================================================================

@description('Technical contact information')
param technicalContactId string = ''
param technicalContactEmail string = ''
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''

@description('Service Principal configuration')
param projectServicePrincipleOID_SeedingKeyvaultName string

@description('Keyvault seeding configuration')
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string

// ============================================================================
// PARAMETERS - Tags
// ============================================================================

@description('Resource tags')
param tags object
param tagsProject object

// ============================================================================
// PARAMETERS - Debugging & Random Values
// ============================================================================

@description('Enable debugging output')
param enableDebugging bool = false

@description('Random value for unique naming')
param randomValue string = ''

@description('Salt values for random naming')
param aifactorySalt10char string = ''

var subscriptionIdDevTestProd = subscription().subscriptionId
var projectName = 'prj${projectNumber}'
var commonResourceGroup = commonResourceGroup_param != '' ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}esml-${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}-rg'

// ============================================================================
// COMPUTED VARIABLES - Networking
// ============================================================================

var vnetNameFull = vnetNameFull_param != '' ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = vnetResourceGroup_param != '' ? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup

// Network references - using proper resource references
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetNameFull
  scope: resourceGroup(vnetResourceGroupName)
}

// ============================================================================
// COMPUTED VARIABLES - Private DNS
// ============================================================================

var privDnsResourceGroupName = (privDnsResourceGroup_param != '' && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (privDnsSubscription_param != '' && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// Resource group references for salt generation
resource targetResourceGroupRefSalt 'Microsoft.Resources/resourceGroups@2020-10-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

var projectSalt = substring(uniqueString(targetResourceGroupRefSalt.id), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${projectSalt}'

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: guid('naming-convention-01-foundation',targetResourceGroupRefSalt.id)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    env: env
    projectNumber: projectNumber
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    randomValue:randomValue
    aifactorySalt10char:aifactorySalt10char
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    commonResourceGroupName: commonResourceGroup
    subscriptionIdDevTestProd:subscriptionIdDevTestProd
    technicalAdminsEmail:technicalAdminsEmail
    technicalAdminsObjectID:technicalAdminsObjectID
    acaSubnetId: acaSubnetId
    aksSubnetId:aksSubnetId
    genaiSubnetId:genaiSubnetId
  }
}

var miACAName = namingConvention.outputs.miACAName
var miPrjName = namingConvention.outputs.miPrjName
var p011_genai_team_lead_email_array = namingConvention.outputs.p011_genai_team_lead_email_array
var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array
var uniqueInAIFenv = namingConvention.outputs.uniqueInAIFenv
var randomSalt = namingConvention.outputs.randomSalt
var defaultSubnet = namingConvention.outputs.defaultSubnet
var aksSubnetName = namingConvention.outputs.aksSubnetName
var acaSubnetName = namingConvention.outputs.acaSubnetName

// ============================================================================
// COMPUTED VARIABLES - Private DNS Zones
// ============================================================================

module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

var privateLinksDnsZonesArray = [
  {
    name: privateLinksDnsZones.blob.name
    id: privateLinksDnsZones.blob.id
    exists: true
  }
  {
    name: privateLinksDnsZones.file.name
    id: privateLinksDnsZones.file.id
    exists: true
  }
  {
    name: privateLinksDnsZones.dfs.name
    id: privateLinksDnsZones.dfs.id
    exists: true
  }
  {
    name: privateLinksDnsZones.queue.name
    id: privateLinksDnsZones.queue.id
    exists: true
  }
  {
    name: privateLinksDnsZones.table.name
    id: privateLinksDnsZones.table.id
    exists: true
  }
  {
    name: privateLinksDnsZones.registry.name
    id: privateLinksDnsZones.registry.id
    exists: true
  }
  {
    name: privateLinksDnsZones.registryregion.name
    id: privateLinksDnsZones.registryregion.id
    exists: true
  }
  {
    name: privateLinksDnsZones.vault.name
    id: privateLinksDnsZones.vault.id
    exists: true
  }
  {
    name: privateLinksDnsZones.amlworkspace.name
    id: privateLinksDnsZones.amlworkspace.id
    exists: true
  }
  {
    name: privateLinksDnsZones.notebooks.name
    id: privateLinksDnsZones.notebooks.id
    exists: true
  }
  {
    name: privateLinksDnsZones.dataFactory.name
    id: privateLinksDnsZones.dataFactory.id
    exists: true
  }
  {
    name: privateLinksDnsZones.portal.name
    id: privateLinksDnsZones.portal.id
    exists: true
  }
  {
    name: privateLinksDnsZones.openai.name
    id: privateLinksDnsZones.openai.id
    exists: true
  }
  {
    name: privateLinksDnsZones.searchService.name
    id: privateLinksDnsZones.searchService.id
    exists: true
  }
  {
    name: privateLinksDnsZones.azurewebapps.name
    id: privateLinksDnsZones.azurewebapps.id
    exists: true
  }
  {
    name: privateLinksDnsZones.cosmosdbnosql.name
    id: privateLinksDnsZones.cosmosdbnosql.id
    exists: true
  }
  {
    name: privateLinksDnsZones.cognitiveservices.name
    id: privateLinksDnsZones.cognitiveservices.id
    exists: true
  }
  {
    name: privateLinksDnsZones.azuredatabricks.name
    id: privateLinksDnsZones.azuredatabricks.id
    exists: true
  }
  {
    name: privateLinksDnsZones.namespace.name
    id: privateLinksDnsZones.namespace.id
    exists: true
  }
  {
    name: privateLinksDnsZones.azureeventgrid.name
    id: privateLinksDnsZones.azureeventgrid.id
    exists: true
  }
  {
    name: privateLinksDnsZones.azuremonitor.name
    id: privateLinksDnsZones.azuremonitor.id
    exists: true
  }
  {
    name: privateLinksDnsZones.azuremonitoroms.name
    id: privateLinksDnsZones.azuremonitoroms.id
    exists: true
  }
  {
    name: privateLinksDnsZones.azuremonitorods.name
    id: privateLinksDnsZones.azuremonitorods.id
    exists: true
  }
  {
    name: privateLinksDnsZones.azuremonitoragentsvc.name
    id: privateLinksDnsZones.azuremonitoragentsvc.id
    exists: true
  } // 2025-04-01: Added above in Common
  {
    name: privateLinksDnsZones.azurecontainerapps.name
    id: privateLinksDnsZones.azurecontainerapps.id
    exists: zoneAzurecontainerappsExists
  }
  {
    name: privateLinksDnsZones.redis.name
    id: privateLinksDnsZones.redis.id
    exists: zoneRedisExists
  }
  {
    name: privateLinksDnsZones.postgres.name
    id: privateLinksDnsZones.postgres.id
    exists: zonePostgresExists
  }
  {
    name: privateLinksDnsZones.sql.name
    id: privateLinksDnsZones.sql.id
    exists: zoneSqlExists
  }
  {
    name: privateLinksDnsZones.cosmosdbmongo.name
    id: privateLinksDnsZones.cosmosdbmongo.id
    exists: zoneMongoExists
  } // 2025-05-30: Added above in Common
]

// ============================================================================
// EXISTING RESOURCES
// ============================================================================

// External KeyVault for seeding
resource externalKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

// ============================================================================
// MODULE DEPLOYMENTS
// ============================================================================

// Private DNS Zones Setup
@description('AIFACTORY-UPDATE-121: Create Private DNS Zones if not centralized')
module createNewPrivateDnsZonesIfNotExists '../modules/createNewPrivateDnsZonesIfNotExists.bicep' = if (centralDnsZoneByPolicyInHub == false) {
  scope: resourceGroup(privDnsSubscription, privDnsResourceGroupName)
  name: guid('createNewPrivateDnsZones',commonResourceGroupRef.id, subscriptionIdDevTestProd)
  params: {
    privateLinksDnsZones: privateLinksDnsZonesArray
    privDnsSubscription: privDnsSubscription
    privDnsResourceGroup: privDnsResourceGroupName
    vNetName: vnetNameFull
    vNetResourceGroup: vnetResourceGroupName
    location: location
    allGlobal: privateDnsAndVnetLinkAllGlobalLocation
  }
  dependsOn: [
    commonResourceGroupRef
  ]
}

// Project Resource Group
module projectResourceGroup '../modules/resourcegroupUnmanaged.bicep' = {
  scope: subscription(subscriptionIdDevTestProd)
  name: guid('prjRG',commonResourceGroupRef.id, subscriptionIdDevTestProd)
  params: {
    rgName: targetResourceGroup
    location: location
    tags: tagsProject
  }
}

// Project Managed Identity
module miForPrj '../modules/mi.bicep' = if (!resourceExists.miPrj) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: guid('miForPrj',commonResourceGroupRef.id, subscriptionIdDevTestProd)
  params: {
    name: miPrjName
    location: location
    tags: tagsProject
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// Container Apps Managed Identity
module miForAca '../modules/mi.bicep' = if (!resourceExists.miACA) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'miForAca${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: miACAName
    location: location
    tags: tagsProject
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// Service Principals and Managed Identity Array
module spAndMI2Array '../modules/spAndMiArray.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'spAndMI2Array${deploymentProjSpecificUniqueSuffix}'
  params: {
    managedIdentityOID: ''  // Will be populated by dependent modules
    servicePrincipleOIDFromSecret: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
  }
  dependsOn: [
    projectResourceGroup
    ...(resourceExists.miPrj ? [] : [miForPrj])
  ]
}

// Debug Module (optional)
module debug './00-debug.bicep' = if (enableDebugging) {
  name: 'debug${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    projectName: projectName
    projectNumber: projectNumber
    env: env
    location: location
    locationSuffix: locationSuffix
    commonResourceGroup: commonResourceGroup
    targetResourceGroup: targetResourceGroup
    vnetNameFull: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subscriptions_subscriptionId: subscription().subscriptionId
    keyvaultExists: resourceExists.keyvault
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// VM Admin Login Permissions (if storage already exists)
module vmAdminLoginPermissions '../modules/vmAdminLoginRbac.bicep' = if (resourceExists.storageAccount1001) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'VMAdminLogin4${deploymentProjSpecificUniqueSuffix}'
  params: {
    userId: technicalContactId
    userEmail: technicalContactEmail
    additionalUserEmails: p011_genai_team_lead_email_array
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// ============================================================================
// OUTPUTS
// ============================================================================

@description('Foundation deployment outputs')
output foundationOutputs object = {
  // Resource Group Information
  projectResourceGroupName: targetResourceGroup
  commonResourceGroupName: commonResourceGroup
  
  // Managed Identity Information
  miProjectName: miPrjName
  miACAName: miACAName
  
  // Service Principal Array
  spAndMiArrayOutput: spAndMI2Array.outputs.spAndMiArray
  
  // Networking Information
  vnetId: vnet.id
  vnetName: vnetNameFull
  vnetResourceGroupName: vnetResourceGroupName
  
  // Private DNS Configuration
  privateLinksDnsZones: privateLinksDnsZones
  privDnsResourceGroupName: privDnsResourceGroupName
  privDnsSubscription: privDnsSubscription
  
  // Naming & Salt Information
  uniqueInAIFenv: uniqueInAIFenv
  randomSalt: randomSalt
  deploymentSuffix: deploymentProjSpecificUniqueSuffix
}

@description('Ready for next deployment layer')
output foundationComplete bool = true
