targetScope = 'subscription'

@allowed(['Premium', 'Standard', 'Basic'])
param containerRegistrySkuName string = 'Premium'
param vmSKU array = [
  'Standard_E2s_v3'
  'Standard_D4s_v3'
  'standard_D2as_v5'
]

@allowed([
  'Standard_LRS'
  'Standard_GRS'
  'Standard_ZRS'
  'Premium_LRS'
  'Premium_ZRS'
  'Standard_GZRS'
  'Standard_RAGRS'
  'Standard_RAGZRS'
])
@description('Specifies the SKU of the storage account')
param skuNameStorage string = 'Standard_ZRS' // Cannot be changed after creation

param privateDnsAndVnetLinkAllGlobalLocation bool=true // Microsoft only supports global Private DNS Zones as of now
@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvault string
param inputKeyvaultSubscription string
param inputKeyvaultResourcegroup string
param inputCommonSPIDKey string
param inputCommonSPSecretKey string
param enablePublicAccessWithPerimeter bool = false
@description('AI Factory suffix. If you have multiple instances')
param aifactorySuffixRG string=''
param commonResourceSuffix string
param resourceSuffix string = ''
@secure()
@description('The password that is saved to keyvault and used by local admin user on VM')
param adminPassword string
@description('The username of the local admin that is created on VM')
param adminUsername string
@description('Log analytics can only add search queries in BICEP once, otherwise will give error 2nd time, entry key already exists')
param enableLogAnalyticsQueries bool = true
param deployOnlyAIGatewayNetworking bool = false
param vmSKUSelectedArrayIndex int = 0
@allowed([
  'dev'
  'test'
  'prod'
])
@description('Specifies the name of the environment. This name is reflected in resource group and sub-resources')
param env string
@description('Specifies the short location notation. This name is reflected in resource group and sub-resources')
param locationSuffix string
@description('Specifies the tags that should be applied to newly created resources')
param tags object
@description('Datalake GEN 2 storage account prefix. Max 8 chars.Example: If prefix is "marvel", then "marvelesml001[random5]dev",marvelesml001[random5]test,marvelesml001[random5]prod')
param commonLakeNamePrefixMax8chars string
@description('Datalake GEN 2 storage container name')
param lakeContainerName string
@description('Specifies the tenant id')
param tenantId string
@description('Specifies the virtual network name')
param vnetNameBase string
@description('Deployment location')
param location string
@description('Specifies if private VM  - access via Bastion or Azure VPN')
param enableAdminVM bool = false
@description('true if Bastion Host should be created')
param addBastionHost bool
@description('Common default subnet')
param common_subnet_name string
@description('(Required) true if Hybrid benefits for Windows server VMs, else FALSE for Pay-as-you-go')
param hybridBenefit bool
@description('Specifies project owner email and will be used for tagging and RBAC')
param technicalContactEmail string=''
@description('Specifies project owner objectId and will be used for tagging and RBAC')
param technicalContactId string=''
@description('Common service principle keuvault secret key name for Object ID')
param commonServicePrincipleOIDKey string
param databricksOID string
@description('Resource group prefix. If "rg-msft-word" then "rg-msft-word-{commonResourceName}-weu-dev-001"')
param commonRGNamePrefix string = ''
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsObjectID string = 'null'
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsEmail string = 'null'
@description('Optional:Whitelist IP addresses from project members to see keyvault, and to connect via Bastion')
param IPwhiteList string = ''
@description('ESML can run standalone/demo mode, this is deafault mode, meaning default FALSE value, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false // DONE: jåaj 
@description('Common resource group name. If not set, it will be created as "{commonResourceName}-weu-dev-001"')
param commonResourceGroup_param string = ''
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param datalakeName_param string = ''
param kvNameFromCOMMON_param string = ''
param useCommonACR bool = true
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''
param enablePurgeProtection bool = true

// CMK Parameters
param cmk bool = false
param cmkKeyName string = ''

param keyvaultSoftDeleteDays int = 90
param BYO_subnets bool = false
param network_env string =''
param subnetCommon string = ''
param subnetCommonScoring string = ''
param subnetCommonPowerbiGw string = ''
param subnetProjGenAI string = ''
param subnetProjAKS string = ''
param subnetProjDatabricksPublic string = ''
param subnetProjDatabricksPrivate string = ''
param subnetProjACA string = ''
param DOCS_byovnet_example string = ''
param DOCS_byosnet_common_example string = ''
param DOCS_byosnet_project_example string = ''
param byoASEv3 bool = false
param byoAseFullResourceId string = ''
param byoAseAppServicePlanResourceId string = ''
param allowPublicAccessWhenBehindVnet bool = false
param acr_adminUserEnabled bool = false
param acr_dedicated bool = true
@description('Common resource name identifier. Default is "esml-common"')
param commonResourceName string = 'esml-common'
@description('Common resource abbreviation. Default is "esml"')
param commonResourceAbbreviation string = 'esml'
@description('Common resource abbreviation for short names. Default is "cmn"')
param commonResourceShortName string = 'cmn'

var subscriptionIdDevTestProd = subscription().subscriptionId
var commonResourceGroupName = commonResourceGroup_param != '' ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'  // {commonResourceName}-weu-dev-002
var vnetResourceGroupName = vnetResourceGroup_param != '' ? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroupName

var privDnsResourceGroupName = (privDnsResourceGroup_param != '' && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (privDnsSubscription_param != '' && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd

// DEPENDENCIES - should exist
resource esmlCommonResourceGroup 'Microsoft.Resources/resourceGroups@2020-10-01' existing = {
  name: commonResourceGroupName
  scope:subscription(subscriptionIdDevTestProd)
}

// Create a short, unique suffix, that will be unique to each AI Factorys common env (Dev,Test,Prod)
var uniqueInAIFenv = substring(uniqueString(esmlCommonResourceGroup.id), 0, 5)
var vnetNameFull = vnetNameFull_param != '' ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'  // {vnetNameBase}-weu-dev-001
var cmnName = commonResourceShortName // needs to be short. KV, ADF, LA, STORAGE needs to be globally unique
var kvNameCommon = 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}' //kv-cmn-prod-12345-004 (21/24)
var kvNameCommonAdmin = 'kv-${cmnName}adm${env}-${uniqueInAIFenv}${commonResourceSuffix}' // kv-cmnadm-prod-12345-004 (24, 24max)
var vnetId = '${subscription().id}/resourceGroups/${vnetResourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetNameFull}'
var vnetNameAbbreviation = vnetNameBase // Dynamic vnet name for private endpoints
var datalakeName = '${commonLakeNamePrefixMax8chars}${uniqueInAIFenv}${commonResourceAbbreviation}${replace(commonResourceSuffix,'-','')}${env}' // Max(16/24) Example: {commonLakeNamePrefixMax8chars}001lobguprod

// CMK Identity Variables
var cmkIdentityName = 'id-cmn-cmk-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
var cmkIdentityIdString = resourceId(subscriptionIdDevTestProd, commonResourceGroupName, 'Microsoft.ManagedIdentity/userAssignedIdentities', cmkIdentityName)

// Assign "Key Vault Crypto Service Encryption User" to the CMK Identity (identity created in 11-rgCommon)
module cmkRbac '../../modules/kvRbacSingleAssignment.bicep' = if (cmk) {
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
  name: 'cmkRbac-${uniqueInAIFenv}'
  params: {
    keyVaultName: inputKeyvault
    principalId: cmk ? reference(cmkIdentityIdString, '2023-01-31').principalId : ''
    keyVaultRoleId: 'e147488a-f6f5-4113-8e2d-b22465e65bf6' // Key Vault Crypto Service Encryption User
    assignmentName: 'cmk-cmnrg-acr-rbac-${cmkIdentityName}'
    principalType: 'ServicePrincipal'
  }
}

// snets
//param BYO_subnets bool = false
//param network_env string =''
//param subnetCommon string = ''
//param subnetCommonScoring string = ''
//param subnetCommonPowerbiGw string = ''

var defaultSubnet = (BYO_subnets)?replace(subnetCommon, '<network_env>', network_env) : common_subnet_name
var commonSubnetScoring = (BYO_subnets)?replace(subnetCommonScoring, '<network_env>', network_env) : '${common_subnet_name}-scoring'
var commonSubnetPowerBI = (BYO_subnets)?replace(subnetCommonPowerbiGw, '<network_env>', network_env) : 'snet-${commonResourceAbbreviation}-${commonResourceShortName}-pbi-001' // common_pbi_subnet_name

// RBAC
var ipWhitelist_array_1 = array(split(replace(IPwhiteList, '\\s+', ''), ','))
var ipWhitelist_array = (empty(IPwhiteList) || IPwhiteList == 'null') ? [] : ipWhitelist_array_1

// Process IP rules for Container Registry (add /32 if no CIDR notation provided)
var processedIpRules = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,'\\s+', ''),','))
var technicalAdminsObjectID_array_safe = (empty(technicalAdminsObjectID) || technicalAdminsObjectID == 'null') ? [] : technicalAdminsObjectID_array

var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var technicalAdminsEmail_array_safe = (empty(technicalAdminsEmail) || technicalAdminsEmail == 'null') ? [] : technicalAdminsEmail_array
var sweden_central_adf_missing = false // (location == 'swedencentral')?true:false

// Config regarding private DNS zones (Microsoft private DNS. If you have your ownd DNS server, see here: https://docs.microsoft.com/en-us/azure/machine-learning/how-to-custom-dns?tabs=azure-cli)
var privateDnsZoneName =  {
  azureusgovernment: 'privatelink.api.ml.azure.us'
  azurechinacloud: 'privatelink.api.ml.azure.cn'
  azurecloud: 'privatelink.api.azureml.ms'
}

var privateAznbDnsZoneName = {
    azureusgovernment: 'privatelink.notebooks.usgovcloudapi.net'
    azurechinacloud: 'privatelink.notebooks.chinacloudapi.cn'
    azurecloud: 'privatelink.notebooks.azure.net'
}

/// 2024-09-15: 25 entries
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
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.azurecr.io' // privatelink.${environment().suffixes.acrLoginServer}' // # E
    name:'privatelink.azurecr.io'
  }
  registryregion: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/${location}.data.privatelink.azurecr.io' // privatelink.${environment().suffixes.acrLoginServer}' // # E
    name:'${location}.data.privatelink.azurecr.io'
  }
  vault: { // privatelink.vault.azure.net
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net'
    name:'privatelink.vaultcore.azure.net'
  }
  amlworkspace: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/${privateDnsZoneName[toLower(environment().name)]}' //# E
    name: privateDnsZoneName[toLower(environment().name)]
  }
  notebooks: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/${privateAznbDnsZoneName[toLower(environment().name)]}' 
    name:privateAznbDnsZoneName[toLower(environment().name)]
  }
  dataFactory: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.datafactory.azure.net' // # E
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
  /* Not needed: https://learn.microsoft.com/en-us/azure/app-service/overview-private-endpoint#dns  + Provides error if https://github.com/Azure/azure-cli/issues/25814
  azurewebappsscm: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/scm.privatelink.azurewebsites.net'
    name:'scm.privatelink.azurewebsites.net'
  }*/
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
  servicesai: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.services.ai.azure.com'
    name:'privatelink.services.ai.azure.com'
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
  apim: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.azure-api.net'
    name:'privatelink.azure-api.net'
  } 
}

// 20250211 NEW: [privatelink.services.ai.azure.com]

var privateLinksDnsZonesArray = [
  {
    name: privateLinksDnsZones.blob.name
    id: privateLinksDnsZones.blob.id
  }
  {
    name: privateLinksDnsZones.file.name
    id: privateLinksDnsZones.file.id
  }
  {
    name: privateLinksDnsZones.dfs.name
    id: privateLinksDnsZones.dfs.id
  }
  {
    name: privateLinksDnsZones.queue.name
    id: privateLinksDnsZones.queue.id
  }
  {
    name: privateLinksDnsZones.table.name
    id: privateLinksDnsZones.table.id
  }
  {
    name: privateLinksDnsZones.registry.name
    id: privateLinksDnsZones.registry.id
  }
  {
    name: privateLinksDnsZones.registryregion.name
    id: privateLinksDnsZones.registryregion.id
  }
  {
    name: privateLinksDnsZones.vault.name
    id: privateLinksDnsZones.vault.id
  }
  {
    name: privateLinksDnsZones.amlworkspace.name
    id: privateLinksDnsZones.amlworkspace.id
  }
  {
    name: privateLinksDnsZones.notebooks.name
    id: privateLinksDnsZones.notebooks.id
  }
  {
    name: privateLinksDnsZones.dataFactory.name
    id: privateLinksDnsZones.dataFactory.id
  }
  {
    name: privateLinksDnsZones.portal.name
    id: privateLinksDnsZones.portal.id
  }
  {
    name: privateLinksDnsZones.openai.name
    id: privateLinksDnsZones.openai.id
  }
  {
    name: privateLinksDnsZones.searchService.name
    id: privateLinksDnsZones.searchService.id
  }
  {
    name: privateLinksDnsZones.azurewebapps.name
    id: privateLinksDnsZones.azurewebapps.id
  }
  {
    name: privateLinksDnsZones.cosmosdbnosql.name
    id: privateLinksDnsZones.cosmosdbnosql.id
  }
  {
    name: privateLinksDnsZones.cognitiveservices.name
    id: privateLinksDnsZones.cognitiveservices.id
  }
  /* Not needed: https://learn.microsoft.com/en-us/azure/app-service/overview-private-endpoint#dns  + Provides error if https://github.com/Azure/azure-cli/issues/25814
  {
    name: privateLinksDnsZones.azurewebappsscm.name
    id: privateLinksDnsZones.azurewebappsscm.id
  }*/
  {
    name: privateLinksDnsZones.azuredatabricks.name
    id: privateLinksDnsZones.azuredatabricks.id
  }
  {
    name: privateLinksDnsZones.namespace.name
    id: privateLinksDnsZones.namespace.id
  }
  {
    name: privateLinksDnsZones.azureeventgrid.name
    id: privateLinksDnsZones.azureeventgrid.id
  }
  {
    name: privateLinksDnsZones.azuremonitor.name
    id: privateLinksDnsZones.azuremonitor.id
  }
  {
    name: privateLinksDnsZones.azuremonitoroms.name
    id: privateLinksDnsZones.azuremonitoroms.id
  }
  {
    name: privateLinksDnsZones.azuremonitorods.name
    id: privateLinksDnsZones.azuremonitorods.id
  }
  {
    name: privateLinksDnsZones.azuremonitoragentsvc.name
    id: privateLinksDnsZones.azuremonitoragentsvc.id
  }
  {
    name: privateLinksDnsZones.servicesai.name
    id: privateLinksDnsZones.servicesai.id
  }
  {
    name: privateLinksDnsZones.azurecontainerapps.name
    id: privateLinksDnsZones.azurecontainerapps.id
  }
  {
    name: privateLinksDnsZones.redis.name
    id: privateLinksDnsZones.redis.id
  }
  {
    name: privateLinksDnsZones.postgres.name
    id: privateLinksDnsZones.postgres.id
  }
  {
    name: privateLinksDnsZones.sql.name
    id: privateLinksDnsZones.sql.id
  }
  {
    name: privateLinksDnsZones.cosmosdbmongo.name
    id: privateLinksDnsZones.cosmosdbmongo.id
  }
  {
    name: privateLinksDnsZones.apim.name
    id: privateLinksDnsZones.apim.id
  }
]


module createPrivateDnsZonesIfNotExists '../../modules/createPrivateDnsZones.bicep' = if(!centralDnsZoneByPolicyInHub) {
  scope: resourceGroup(privDnsSubscription,privDnsResourceGroupName)
  name: 'PrivDnsZonesIfNotExistsCmn-${uniqueInAIFenv}'
  params: {
    privateLinksDnsZones: privateLinksDnsZonesArray
    privDnsSubscription: privDnsSubscription
    privDnsResourceGroup: privDnsResourceGroupName
    vNetName: vnetNameFull
    vNetResourceGroup: vnetResourceGroupName
    location: location
    allGlobal:privateDnsAndVnetLinkAllGlobalLocation
  }
  dependsOn: [
    esmlCommonResourceGroup
  ]
}

var acrCommonName = 'acrcommon${uniqueInAIFenv}${locationSuffix}${commonResourceSuffix}${env}'
module acrCommon '../../modules/containerRegistry.bicep' = if(!deployOnlyAIGatewayNetworking){
  scope: esmlCommonResourceGroup
  name: 'CommonACR4CommonRG${uniqueInAIFenv}'
  params: {
    containerRegistryName:acrCommonName
    skuName: containerRegistrySkuName
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: 'pend-acr-${commonResourceShortName}${locationSuffix}-containerreg-to-${vnetNameAbbreviation}' // dynamic based on vnet name
    tags: tags
    location:location
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    ipRules: processedIpRules
    adminUserEnabled: acr_adminUserEnabled
    dedicatedDataPoint:acr_dedicated
    cmk: cmk
    cmkIdentityId: cmk ? cmkIdentityIdString : ''
    cmkKeyName: cmk ? cmkKeyName : ''
    cmkKeyVaultUri: cmk ? reference(resourceId(inputKeyvaultSubscription, inputKeyvaultResourcegroup, 'Microsoft.KeyVault/vaults', inputKeyvault), '2022-07-01').vaultUri : ''
  }

  dependsOn: [
    esmlCommonResourceGroup
    cmkRbac
  ]
}
module privateDnsContainerRegistryCommon '../../modules/privateDns.bicep' = if(!centralDnsZoneByPolicyInHub && !deployOnlyAIGatewayNetworking){
  scope: esmlCommonResourceGroup
  name: 'privDnsCommonACR${uniqueInAIFenv}'
  params: {
    #disable-next-line BCP318
    dnsConfig: acrCommon.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZonesIfNotExists
    esmlCommonResourceGroup
  ]
}


// Log analytics WORKSPACE (dev,test,prod - 3 in the AI Factory, one per landingzone/environment)
var laName = 'la-${cmnName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
module logAnalyticsWorkspaceOpInsight '../../modules/logAnalyticsWorkspace.bicep' = if(!deployOnlyAIGatewayNetworking){
  scope: esmlCommonResourceGroup
  name: 'LogAnCmn4${uniqueInAIFenv}'
  params: {
    name: laName
    tags: tags
    location: location
    keyvaultName: kvNameCommon
  }

  dependsOn: [
    kvCmn
    esmlCommonResourceGroup
  ]
}

module wsQueries '../../modules/logAnalyticsQueries.bicep' = if(enableLogAnalyticsQueries && !deployOnlyAIGatewayNetworking) {
  scope: esmlCommonResourceGroup
  name: 'logAnalyticsCmnQs${uniqueInAIFenv}'
  params: {
    logAnalyticsName:laName
  }
  dependsOn: [
    logAnalyticsWorkspaceOpInsight
  ]
}


var adfName = 'adf-${cmnName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}' // globally unique: adf-cmn-weu-prod-1234-004 (25/63)
module adf '../../modules/dataFactory.bicep' = if(!deployOnlyAIGatewayNetworking) {
  scope: esmlCommonResourceGroup
  name: 'DataFactoryCmn${uniqueInAIFenv}'
  params: {
    name: adfName
    location: location
    vnetId: vnetId
    subnetName: defaultSubnet
    portalPrivateEndpointName: 'pend-${cmnName}-${env}-${uniqueInAIFenv}-adfportal-to-${vnetNameAbbreviation}' // 64
    runtimePrivateEndpointName: 'pend-${cmnName}-${env}-${uniqueInAIFenv}-adfruntime-to-${vnetNameAbbreviation}'
    tags: tags
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
    cmk: cmk
    cmkKeyName: cmk ? cmkKeyName : ''
    keyVaultUri: cmk ? reference(resourceId(inputKeyvaultSubscription, inputKeyvaultResourcegroup, 'Microsoft.KeyVault/vaults', inputKeyvault), '2022-07-01').vaultUri : ''
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: cmk ? [
        cmkIdentityIdString
      ] : []
    }
  }

  dependsOn: [
    esmlCommonResourceGroup
  ]
}

resource vnetCommonDefaultResourceId 'Microsoft.Network/virtualNetworks@2021-05-01' existing = {
  name:vnetNameFull
  scope: esmlCommonResourceGroup
}

resource subnetCommonDefaultResource 'Microsoft.Network/virtualNetworks/subnets@2021-05-01' existing = {
  name:'${vnetId}/${defaultSubnet}'
  scope: esmlCommonResourceGroup
}

var bastion_subnet_name = 'AzureBastionSubnet'
resource subnetBastion 'Microsoft.Network/virtualNetworks/subnets@2021-05-01' existing = if(addBastionHost && !deployOnlyAIGatewayNetworking) {
  name:'${vnetId}/${bastion_subnet_name}'
  scope: esmlCommonResourceGroup
}

var common_bastion_host_name = 'bastion-${locationSuffix}-${env}${commonResourceSuffix}'
module bastionHost '../modules-common/bastionHostCommon.bicep' = if(addBastionHost && !deployOnlyAIGatewayNetworking) { 
  scope: esmlCommonResourceGroup
  name: 'common_bastion-depl${uniqueInAIFenv}'
  params: {
    name: common_bastion_host_name
    location:location
    subnetId: '${vnetId}/subnets/${bastion_subnet_name}'
    tags: tags
  }
  dependsOn:[
    vnetCommonDefaultResourceId
    subnetBastion
  ]
}

var kvNameCommonNoDash = replace(kvNameCommon,'-','')

module kvCmn '../../modules/keyVault.bicep' = if(!deployOnlyAIGatewayNetworking){
  scope: esmlCommonResourceGroup
  name: '${kvNameCommonNoDash}-depl-${uniqueInAIFenv}'
  params: {
    keyvaultName: kvNameCommon
    location: location
    tags: tags
    tenantIdentity: tenantId
    enablePurgeProtection:enablePurgeProtection
    soft_delete_days:keyvaultSoftDeleteDays
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${kvNameCommon}-to-${vnetNameAbbreviation}'
    keyvaultNetworkPolicySubnets: [
      '${vnetId}/subnets/${defaultSubnet}'
    ]
    accessPolicies: [] 
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
  }
  dependsOn: [
    esmlCommonResourceGroup
    subnetCommonDefaultResource
    dataLake
  ]
}

var secretGet = {
  secrets: [ 
    'get'
  ]
}
var secretGetList = {
  secrets: [ 
    'get'
    'list'
  ]
}

var secretAll = {
  secrets: [ 
    'all'
  ]
}

// AzureDatabricks - if set, and if this EnterpriseApplication already exists (can be that a project needs to be provisoned first..)
module spDatabricksAccessPolicyGet '../../modules/kvCmnAccessPolicys.bicep' = if(!empty(databricksOID) && !deployOnlyAIGatewayNetworking) {
  scope: esmlCommonResourceGroup
  name: 'spDBXAPGet${uniqueInAIFenv}'
  params: {
    keyVaultPermissions: secretGetList
    keyVaultResourceName: kvNameCommon
    policyName: 'add'
    principalId: databricksOID
    additionalPrincipalIds:[]
  }
  dependsOn: [
    kvCmn
  ]
}
// Note: az keyvault update  --name msft-weu-dev-cmnai-kv --enabled-for-template-deployment true
resource externalKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = if(!deployOnlyAIGatewayNetworking){
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription,inputKeyvaultResourcegroup)
}
module spCmnAccessPolicyGet '../../modules/kvCmnAccessPolicys.bicep' = if(!deployOnlyAIGatewayNetworking) {
  scope: esmlCommonResourceGroup
  name: 'spCmnAPGet${uniqueInAIFenv}'
  params: {
    keyVaultPermissions: secretGet
    keyVaultResourceName: kvNameCommon
    policyName: 'add'
    #disable-next-line BCP422
    principalId: externalKv.getSecret(commonServicePrincipleOIDKey) // commonServicePrincipleOID
    additionalPrincipalIds:[]
  }
  dependsOn: [
    kvCmn
    spDatabricksAccessPolicyGet
  ]
}
module adfAccessPolicyGet '../../modules/kvCmnAccessPolicys.bicep' = if(!deployOnlyAIGatewayNetworking) {
  scope: esmlCommonResourceGroup
  name: 'adfAPGet${uniqueInAIFenv}'
  params: {
    keyVaultPermissions: secretGet
    keyVaultResourceName: kvNameCommon
    policyName: 'add'
    #disable-next-line BCP318
    principalId: adf.outputs.principalId
    additionalPrincipalIds:[]
  }
  dependsOn: [
    kvCmn
    adf
    spDatabricksAccessPolicyGet
    spCmnAccessPolicyGet
  ]
}
module kvCmnAccessPolicyTechnicalContactAll '../../modules/kvCmnAccessPolicys.bicep' = if(!deployOnlyAIGatewayNetworking) {
  scope: esmlCommonResourceGroup
  name: 'kvCmnAPTechContact${uniqueInAIFenv}'
  params: {
    keyVaultPermissions: secretAll
    keyVaultResourceName: kvNameCommon
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds:technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    kvCmn
    spDatabricksAccessPolicyGet
    spCmnAccessPolicyGet
    adfAccessPolicyGet
  ]
}

module addSecret '../modules-common/kvSecretsCmn.bicep' = if(!deployOnlyAIGatewayNetworking){
  name: '${kvNameCommonNoDash}sec${uniqueInAIFenv}'
  scope: esmlCommonResourceGroup
  params: {
    #disable-next-line BCP422
    esmlCommonSpIDSecret: externalKv.getSecret(inputCommonSPIDKey)
    #disable-next-line BCP422
    esmlCommonSpSecretValue:externalKv.getSecret(inputCommonSPSecretKey)
    #disable-next-line BCP422
    esmlCommonSpOIDValue:externalKv.getSecret(commonServicePrincipleOIDKey)
    //esmlCommonSpOIDValue: commonServicePrincipleOID
    keyvaultName: kvNameCommon
  }
  dependsOn: [
    kvCmn
    spDatabricksAccessPolicyGet
    spCmnAccessPolicyGet
    adfAccessPolicyGet
    kvCmnAccessPolicyTechnicalContactAll
  ]
}

var kvAdminNoDash = replace(kvNameCommonAdmin,'-','')
module kvAdmin '../../modules/keyVault.bicep' = if(!deployOnlyAIGatewayNetworking){
  scope: esmlCommonResourceGroup
  name: '${kvAdminNoDash}${uniqueInAIFenv}'
  params: {
    keyvaultName: kvNameCommonAdmin
    location: location
    tags: tags
    tenantIdentity: tenantId
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    enablePurgeProtection:enablePurgeProtection
    soft_delete_days:keyvaultSoftDeleteDays
    privateEndpointName: 'pend-${kvNameCommonAdmin}-to-${vnetNameAbbreviation}'
    keyvaultNetworkPolicySubnets: [
      '${vnetId}/subnets/${defaultSubnet}'
    ]
    accessPolicies: [] 
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
  }
  dependsOn: [
    esmlCommonResourceGroup
    subnetCommonDefaultResource
  ]
}
module kvAdminAccessPolicyTechnicalContactAll '../../modules/kvCmnAccessPolicys.bicep' = if(!deployOnlyAIGatewayNetworking){
  scope: esmlCommonResourceGroup
  name: '${kvAdminNoDash}AP${uniqueInAIFenv}' 
  params: {
    keyVaultPermissions: secretAll
    keyVaultResourceName: kvNameCommonAdmin
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds:technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    kvAdmin
  ]
}
module kvAdminAccessPolicyCommonSP '../../modules/kvCmnAccessPolicys.bicep' = if(!deployOnlyAIGatewayNetworking){
  scope: esmlCommonResourceGroup
  name: '${kvAdminNoDash}AP2${uniqueInAIFenv}'
  params: {
    keyVaultPermissions: secretGetList
    keyVaultResourceName: kvNameCommonAdmin
    policyName: 'add'
    #disable-next-line BCP422
    principalId: externalKv.getSecret(commonServicePrincipleOIDKey)
    additionalPrincipalIds:[]
  }
  dependsOn: [
    kvAdmin
    kvAdminAccessPolicyTechnicalContactAll
  ]
}

module kvAdminAccessPolicyGetADF '../../modules/kvCmnAccessPolicys.bicep' = if(!deployOnlyAIGatewayNetworking){
  scope: esmlCommonResourceGroup
  name: '${kvAdminNoDash}APadf${uniqueInAIFenv}'
  params: {
    keyVaultPermissions: secretGet
    keyVaultResourceName: kvNameCommonAdmin
    policyName: 'add'
    #disable-next-line BCP318
    principalId: adf.outputs.principalId
    additionalPrincipalIds:[]
  }
  dependsOn: [
    kvAdmin
    adf
    kvAdminAccessPolicyTechnicalContactAll
    kvAdminAccessPolicyCommonSP
  ]
}

var virtualNetworkRules2Add = [
  {
    id: '${vnetId}/subnets/${defaultSubnet}'
    action: 'Allow'
    state: 'succeeded'
  }
]
module dataLake '../../modules/dataLake.bicep' = if(!deployOnlyAIGatewayNetworking){
  scope: esmlCommonResourceGroup
  name: '${datalakeName}${uniqueInAIFenv}'
  params: {
    storageAccountName: datalakeName
    containerName: lakeContainerName
    skuName: skuNameStorage //'Standard_LRS'
    location: location
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    blobPrivateEndpointName: 'pend-${datalakeName}-blob-to-${vnetNameAbbreviation}'
    filePrivateEndpointName: 'pend-${datalakeName}-file-to-${vnetNameAbbreviation}'
    dfsPrivateEndpointName: 'pend-${datalakeName}-dfs-to-${vnetNameAbbreviation}'
    queuePrivateEndpointName: 'pend-${datalakeName}-queue-to-${vnetNameAbbreviation}'
    tablePrivateEndpointName: 'pend-${datalakeName}-table-to-${vnetNameAbbreviation}'
    tags: tags
    virtualNetworkRules:virtualNetworkRules2Add
    ipWhitelist_array:ipWhitelist_array
    cmk: cmk
    cmkIdentityId: cmk ? cmkIdentityIdString : ''
    cmkKeyName: cmk ? cmkKeyName : ''
    cmkKeyVaultUri: cmk ? reference(resourceId(inputKeyvaultSubscription, inputKeyvaultResourcegroup, 'Microsoft.KeyVault/vaults', inputKeyvault), '2022-07-01').vaultUri : ''
  }

  dependsOn: [
    esmlCommonResourceGroup
  ]
}

module vmPrivate '../../modules/virtualMachinePrivate.bicep' = if(enableAdminVM && !deployOnlyAIGatewayNetworking) {
  scope: esmlCommonResourceGroup
  name: 'privateVirtualMachine${uniqueInAIFenv}'
  params: {
    adminUsername: adminUsername
    adminPassword: adminPassword
    hybridBenefit:hybridBenefit
    vmSize: vmSKU[0] //["Standard_E2s_v3","Standard_D4s_v3"]
    location: location
    vmName: 'dsvm-${cmnName}-${locationSuffix}-${env}${commonResourceSuffix}'
    subnetName: defaultSubnet
    vnetId: vnetId
    tags: tags
    #disable-next-line BCP318
    keyvaultName: kvAdmin.outputs.keyvaultName
  }

  dependsOn: [
    kvAdmin
    esmlCommonResourceGroup
  ]
}

module privateDnsDatalake '../../modules/privateDns.bicep' = if(!centralDnsZoneByPolicyInHub && !deployOnlyAIGatewayNetworking){
  scope:resourceGroup(subscriptionIdDevTestProd,commonResourceGroupName)
  name: 'privDnsZoneAndLinkLake2${uniqueInAIFenv}'
  params: {
    #disable-next-line BCP318
    dnsConfig: dataLake.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZonesIfNotExists
  ]
}


module privateDnsKeyVaultCmn '../../modules/privateDns.bicep' = if(!centralDnsZoneByPolicyInHub && !deployOnlyAIGatewayNetworking){
  scope:resourceGroup(subscriptionIdDevTestProd,commonResourceGroupName)
  name: 'privDnsZoneAndLinkKeyVaultCmn2${uniqueInAIFenv}'
  params: {
    #disable-next-line BCP318
    dnsConfig: kvCmn.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZonesIfNotExists
    kvCmn
  ]
}

module privateDnsKeyVaultAdmin '../../modules/privateDns.bicep' = if(!centralDnsZoneByPolicyInHub && !deployOnlyAIGatewayNetworking){
  scope:resourceGroup(subscriptionIdDevTestProd,commonResourceGroupName)
  name: 'privDnsZoneKVCmnAdmin2${uniqueInAIFenv}'
  params: {
    #disable-next-line BCP318
    dnsConfig: kvAdmin.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZonesIfNotExists
    kvAdmin
  ]
}

module privateDnsAzureDatafactory '../../modules/privateDns.bicep' = if(!centralDnsZoneByPolicyInHub && !deployOnlyAIGatewayNetworking){
  scope:resourceGroup(subscriptionIdDevTestProd,commonResourceGroupName)
  name: 'privDnsZoneADFCmn2${uniqueInAIFenv}'
  params: {
    #disable-next-line BCP318
    dnsConfig: adf.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZonesIfNotExists
    adf
  ]
}

