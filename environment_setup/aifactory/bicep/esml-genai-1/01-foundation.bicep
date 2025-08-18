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
param aifactoryVersionMinor int = 20
var activeVersion = 121

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

@description('Existing resource flags')
param miACAExists bool = false
param miPrjExists bool = false
param keyvaultExists bool = false
param storageAccount1001Exists bool = false

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

@description('Tenant configuration')
param tenantId string

@description('Service Principal configuration')
param projectServicePrincipleOID_SeedingKeyvaultName string
param projectServicePrincipleSecret_SeedingKeyvaultName string
param projectServicePrincipleAppID_SeedingKeyvaultName string

@description('Keyvault seeding configuration')
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string

// ============================================================================
// PARAMETERS - Debugging
// ============================================================================

@description('Enable debugging output')
param enableDebugging bool = false

@description('Random value for unique naming')
param randomValue string = ''

@description('Salt values for deterministic naming')
param aifactorySalt5char string = ''
param aifactorySalt10char string = ''

// ============================================================================
// PARAMETERS - Tags
// ============================================================================

@description('Resource tags')
param tags object
param projecttags object

// ============================================================================
// COMPUTED VARIABLES - Core
// ============================================================================

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

// ============================================================================
// COMPUTED VARIABLES - RBAC Arrays
// ============================================================================

var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,'\\s+', ''),','))
var p011_genai_team_lead_array = (empty(technicalAdminsObjectID)) ? [] : union(technicalAdminsObjectID_array,[])

var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var p011_genai_team_lead_email_array = (empty(technicalAdminsEmail)) ? [] : technicalAdminsEmail_array

// ============================================================================
// COMPUTED VARIABLES - Naming & Salt
// ============================================================================

// Salt generation for unique naming
var randomGuid = sys.newGuid()
var randomValueUsed = empty(randomValue) ? randomGuid : randomValue
var randomSalt = empty(aifactorySalt10char) || length(aifactorySalt10char) <= 5 ? substring(randomValueUsed, 6, 10): aifactorySalt10char

// Resource group references for salt generation
resource targetResourceGroupRefSalt 'Microsoft.Resources/resourceGroups@2020-10-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

var projectSalt = substring(uniqueString(targetResourceGroupRefSalt.id), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${projectSalt}'

#disable-next-line BCP318
var uniqueInAIFenv = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// Resource naming with salt
var miACAName = 'mi-aca-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${resourceSuffix}'
var miPrjName = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${resourceSuffix}'

// ============================================================================
// COMPUTED VARIABLES - Private DNS Zones
// ============================================================================

var privateDnsZoneName = {
  azureusgovernment: 'privatelink.api.ml.azure.us'
  azurechinacloud: 'privatelink.api.ml.azure.cn'
  azurecloud: 'privatelink.api.azureml.ms'
}

var privateAznbDnsZoneName = {
  azureusgovernment: 'privatelink.notebooks.usgovcloudapi.net'
  azurechinacloud: 'privatelink.notebooks.chinacloudapi.cn'
  azurecloud: 'privatelink.notebooks.azure.net'
}

var privateLinksDnsZones = {
  blob: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.blob.${environment().suffixes.storage}'
    name:'privatelink.blob.${environment().suffixes.storage}'
  }
  file: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.file.${environment().suffixes.storage}'
    name:'privatelink.file.${environment().suffixes.storage}'
  }
  dfs: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.dfs.${environment().suffixes.storage}'
    name:'privatelink.dfs.${environment().suffixes.storage}'
  }
  queue: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.queue.${environment().suffixes.storage}'
    name:'privatelink.queue.${environment().suffixes.storage}'
  }
  table: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.table.${environment().suffixes.storage}'
    name:'privatelink.table.${environment().suffixes.storage}'
  }
  registry: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.azurecr.io'
    name:'privatelink.azurecr.io'
  }
  registryregion: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/${location}.data.privatelink.azurecr.io'
    name:'${location}.data.privatelink.azurecr.io'
  }
  vault: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net'
    name:'privatelink.vaultcore.azure.net'
  }
  amlworkspace: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/${privateDnsZoneName[toLower(environment().name)]}'
    name: privateDnsZoneName[toLower(environment().name)]
  }
  notebooks: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/${privateAznbDnsZoneName[toLower(environment().name)]}'
    name: privateAznbDnsZoneName[toLower(environment().name)]
  }
  dataFactory: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.datafactory.azure.net'
    name:'privatelink.datafactory.azure.net'
  }
  portal: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.adf.azure.com'
    name:'privatelink.adf.azure.com'
  }
  openai: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.openai.azure.com'
    name:'privatelink.openai.azure.com'
  }
  searchService: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.search.windows.net'
    name:'privatelink.search.windows.net'
  }
  azurewebapps: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.azurewebsites.net'
    name:'privatelink.azurewebsites.net'
  }
  cosmosdbnosql: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.documents.azure.com'
    name:'privatelink.documents.azure.com'
  }
  cognitiveservices: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.cognitiveservices.azure.com'
    name:'privatelink.cognitiveservices.azure.com'
  }
  azuredatabricks: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.azuredatabricks.net'
    name:'privatelink.azuredatabricks.net'
  }
  namespace: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.servicebus.windows.net'
    name:'privatelink.servicebus.windows.net'
  }
  azureeventgrid: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.eventgrid.azure.net'
    name:'privatelink.eventgrid.azure.net'
  }
  azuremonitor: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.monitor.azure.com'
    name:'privatelink.monitor.azure.com'
  }
  azuremonitoroms: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.oms.opinsights.azure.com'
    name:'privatelink.oms.opinsights.azure.com'
  }
  azuremonitorods: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.ods.opinsights.azure.com'
    name:'privatelink.ods.opinsights.azure.com'
  }
  azuremonitoragentsvc: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.agentsvc.azure-automation.net'
    name:'privatelink.agentsvc.azure-automation.net'
  }
  azurecontainerapps: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.${location}.azurecontainerapps.io'
    name:'privatelink.${location}.azurecontainerapps.io'
  }
  redis: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.redis.cache.windows.net'
    name:'privatelink.redis.cache.windows.net'
  }
  postgres: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.postgres.database.azure.com'
    name:'privatelink.postgres.database.azure.com'
  }
  sql: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.database.windows.net'
    #disable-next-line no-hardcoded-env-urls
    name:'privatelink.database.windows.net'
  }
  cosmosdbmongo: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.mongo.cosmos.azure.com'
    name:'privatelink.mongo.cosmos.azure.com'
  }
}

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
  }
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
  name: 'createNewPrivateDnsZones${deploymentProjSpecificUniqueSuffix}'
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
  name: 'prjRG${deploymentProjSpecificUniqueSuffix}'
  params: {
    rgName: targetResourceGroup
    location: location
    tags: projecttags
  }
}

// Project Managed Identity
module miForPrj '../modules/mi.bicep' = if (!resourceExists.miPrj) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'miForPrj${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: miPrjName
    location: location
    tags: projecttags
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
    tags: projecttags
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
