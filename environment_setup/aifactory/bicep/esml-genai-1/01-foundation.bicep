// ============================================================================
// AI Factory - Foundation Deployment (01-foundation.bicep)
// ============================================================================
// This deploys the foundational infrastructure components required by all other deployments
// Dependencies: None (first deployment)
// Components: Resource Groups, Managed Identities, Private DNS zones, Basic RBAC

targetScope = 'subscription'

// Import types
import { aifactoryNamingType } from '../modules/types/aifactoryNaming.bicep'

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
param technicalContactId string = '' // TODO-Remove, Replaced by personas
param technicalContactEmail string = '' // TODO-Remove, Replaced by personas
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
// ============================================================================
// PARAMETERS - Naming convention or project resource group
// ============================================================================
param projectPrefix string = 'esml-' // mrvel-1-[esml-]project001-eus2-dev-008-rg
param projectSuffix string = '-rg' // mrvel-1-esml-project001-eus2-dev-008[-rg]

// ============================================================================
// PARAMETERS - Meta. Maybe not needed? jostrm
// ============================================================================
// Metadata &  Dummy parameters, since same json parameterfile has more parameters than this bicep file
@description('Meta. Needed to calculate subnet: subnetCalc and genDynamicNetworkParamFile')
param vnetResourceGroupBase string = 'meta-subnetCalc-to-set' // Meta

// ============================================================================
// PARAMETERS - DEBUG
// ============================================================================

@description('Enable AI Services')
param DEBUG_enableAIServices bool = false

@description('Enable AI Foundry Hub')
param DEBUG_enableAIFoundryHub bool = false

@description('Enable AI Search')
param DEBUG_enableAISearch bool = false

@description('Enable Azure Machine Learning')
param DEBUG_enableAzureMachineLearning bool = false

@description('Deploy Function App')
param DEBUG_serviceSettingDeployFunction bool = true

@description('Function runtime')
param DEBUG_functionRuntime string = 'dotnet'

@description('Function version')
param DEBUG_functionVersion string = 'v7.0'

@description('Deploy Web App')
param DEBUG_serviceSettingDeployWebApp bool = true

@description('Web App runtime')
param DEBUG_webAppRuntime string = 'python'

@description('Web App runtime version')
param DEBUG_webAppRuntimeVersion string = '3.11'

@description('App Service Environment SKU')
param DEBUG_aseSku string = 'IsolatedV2'

@description('App Service Environment SKU Code')
param DEBUG_aseSkuCode string = 'I1v2'

@description('App Service Environment SKU Workers')
param DEBUG_aseSkuWorkers int = 1

@description('Deploy Container Apps')
param DEBUG_serviceSettingDeployContainerApps bool = false

@description('Deploy App Insights Dashboard')
param DEBUG_serviceSettingDeployAppInsightsDashboard bool = false

@description('Container Apps API registry image')
param DEBUG_aca_a_registry_image string = 'containerapps-default:latest'

@description('Container Apps Web registry image')
param DEBUG_aca_w_registry_image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Deploy Bing Search')
param DEBUG_serviceSettingDeployBingSearch bool = false

@description('Deploy Cosmos DB')
param DEBUG_serviceSettingDeployCosmosDB bool = false

@description('Deploy Azure OpenAI')
param DEBUG_serviceSettingDeployAzureOpenAI bool = false

@description('Deploy Azure AI Vision')
param DEBUG_serviceSettingDeployAzureAIVision bool = false

@description('Deploy Azure Speech')
param DEBUG_serviceSettingDeployAzureSpeech bool = false

@description('Deploy AI Document Intelligence')
param DEBUG_serviceSettingDeployAIDocIntelligence bool = false

@description('Disable Contributor Access for Users')
param DEBUG_disableContributorAccessForUsers bool = false

@description('Deploy PostgreSQL')
param DEBUG_serviceSettingDeployPostgreSQL bool = false

@description('Deploy Redis Cache')
param DEBUG_serviceSettingDeployRedisCache bool = false

@description('Deploy SQL Database')
param DEBUG_serviceSettingDeploySQLDatabase bool = false

@description('Bring Your Own subnets - false means use default subnets created by pipeline')
param DEBUG_BYO_subnets bool = false

@description('Network environment prefix for dev - empty string if BYO_subnets is false')
param DEBUG_network_env_dev string = 'tst-'

@description('Network environment prefix for stage')
param DEBUG_network_env_stage string = 'tst2-'

@description('Network environment prefix for prod')
param DEBUG_network_env_prod string = 'prd-'

@description('VNet Resource Group parameter - BYOVNET example: esml-common-eus2-<network_env>001-rg')
param DEBUG_vnetResourceGroup_param string = ''

@description('VNet Name Full parameter')
param DEBUG_vnetNameFull_param string = ''

@description('Common Resource Group parameter')
param DEBUG_commonResourceGroup_param string = ''

@description('Data Lake Name parameter')
param DEBUG_datalakeName_param string = ''

@description('Key Vault Name from COMMON parameter')
param DEBUG_kvNameFromCOMMON_param string = ''

@description('Use Common ACR override')
param DEBUG_useCommonACR_override bool = true

@description('Subnet Common')
param DEBUG_subnetCommon string = ''

@description('Subnet Common Scoring')
param DEBUG_subnetCommonScoring string = ''

@description('Subnet Common Power BI Gateway')
param DEBUG_subnetCommonPowerbiGw string = ''

@description('Subnet Project GenAI')
param DEBUG_subnetProjGenAI string = ''

@description('Subnet Project AKS')
param DEBUG_subnetProjAKS string = ''

@description('Subnet Project ACA')
param DEBUG_subnetProjACA string = ''

@description('Subnet Project Databricks Public')
param DEBUG_subnetProjDatabricksPublic string = ''

@description('Subnet Project Databricks Private')
param DEBUG_subnetProjDatabricksPrivate string = ''

@description('Bring Your Own ASE v3')
param DEBUG_byoASEv3 bool = false

@description('BYO ASE Full Resource ID')
param DEBUG_byoAseFullResourceId string = ''

@description('BYO ASE App Service Plan Resource ID')
param DEBUG_byoAseAppServicePlanResourceId string = ''

@description('Enable Public GenAI Access')
param DEBUG_enablePublicGenAIAccess bool = false

@description('Allow Public Access When Behind VNet')
param DEBUG_allowPublicAccessWhenBehindVnet bool = false

@description('Enable Public Access With Perimeter')
param DEBUG_enablePublicAccessWithPerimeter bool = false

@description('Admin AI Factory Suffix RG')
param DEBUG_admin_aifactorySuffixRG string = '-008'

@description('Admin Common Resource Suffix')
param DEBUG_admin_commonResourceSuffix string = '-001'

@description('Admin Project Resource Suffix')
param DEBUG_admin_prjResourceSuffix string = '-001'

@description('AI Factory Salt')
param DEBUG_aifactory_salt string = ''

@description('Admin Project Type')
param DEBUG_admin_projectType string = 'genai-1'

@description('Project Number 000')
param DEBUG_project_number_000 string = '001'

@description('Project Service Principal App ID Seeding KV Name')
param DEBUG_project_service_principal_AppID_seeding_kv_name string = 'esml-project001-sp-id'

@description('Project Service Principal OID Seeding KV Name')
param DEBUG_project_service_principal_OID_seeding_kv_name string = 'esml-project001-sp-oid'

@description('Project Service Principal Secret Seeding KV Name')
param DEBUG_project_service_principal_Secret_seeding_kv_name string = 'esml-project001-sp-secret'

@description('Project IP Whitelist')
param DEBUG_project_IP_whitelist string = ''

@description('Deploy Model GPT-4')
param DEBUG_deployModel_gpt_4 bool = false

@description('Deploy Model Text Embedding Ada 002')
param DEBUG_deployModel_text_embedding_ada_002 bool = false

@description('Deploy Model Text Embedding 3 Large')
param DEBUG_deployModel_text_embedding_3_large bool = false

@description('Deploy Model Text Embedding 3 Small')
param DEBUG_deployModel_text_embedding_3_small bool = false

@description('Deploy Model GPT-4o Mini')
param DEBUG_deployModel_gpt_4o_mini bool = false

var subscriptionIdDevTestProd = subscription().subscriptionId
var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

// ============================================================================
// COMPUTED VARIABLES - Networking
// ============================================================================

var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup

// Network references - using proper resource references
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetNameFull
  scope: resourceGroup(vnetResourceGroupName)
}

// ============================================================================
// COMPUTED VARIABLES - Private DNS
// ============================================================================

var privDnsResourceGroupName = (!empty(privDnsResourceGroup_param) && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (!empty(privDnsSubscription_param) && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// Create Target Resource group
resource projectResourceGroup 'Microsoft.Resources/resourceGroups@2024-07-01' = {
  name: targetResourceGroup
  location: location
  tags: tagsProject
}

var projectSalt = substring(uniqueString(commonResourceGroupRef.id), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${projectSalt}'

// ============================================================================
// AI Factory - naming convention (imported from shared module) 
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: '01-naming-${targetResourceGroup}'
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
  dependsOn: [
    projectResourceGroup
  ]
}

// Get naming convention outputs with type safety
var namingOutputs = namingConvention.outputs.namingConvention

// Extract commonly used values with type safety
var miACAName = namingOutputs.miACAName
var miPrjName = namingOutputs.miPrjName
var p011_genai_team_lead_email_array = namingOutputs.p011_genai_team_lead_email_array
var p011_genai_team_lead_array = namingOutputs.p011_genai_team_lead_array
var uniqueInAIFenv = namingOutputs.uniqueInAIFenv
var randomSalt = namingOutputs.randomSalt
var defaultSubnet = namingOutputs.defaultSubnet
var aksSubnetName = namingOutputs.aksSubnetName
var acaSubnetName = namingOutputs.acaSubnetName

// ============================================================================
// COMPUTED VARIABLES - Private DNS Zones
// ============================================================================

module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '01-getPrivDnsZ-${targetResourceGroup}'
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
  dependsOn: [
    projectResourceGroup
  ]
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

// Project Managed Identity
module miForPrj '../modules/mi.bicep' = if (!resourceExists.miPrj) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '01-miForPrj${deploymentProjSpecificUniqueSuffix}'
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
  name: '01-miForAca${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: miACAName
    location: location
    tags: tagsProject
  }
  dependsOn: [
    projectResourceGroup
  ]
}


// Debug Module (optional)
module debug './00-debug.bicep' = if (enableDebugging) {
  name: '01-DEBUG-${deploymentProjSpecificUniqueSuffix}'
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
    // DEBUG Parameters
    DEBUG_enableAIServices: DEBUG_enableAIServices
    DEBUG_enableAIFoundryHub: DEBUG_enableAIFoundryHub
    DEBUG_enableAISearch: DEBUG_enableAISearch
    DEBUG_enableAzureMachineLearning: DEBUG_enableAzureMachineLearning
    DEBUG_serviceSettingDeployFunction: DEBUG_serviceSettingDeployFunction
    DEBUG_functionRuntime: DEBUG_functionRuntime
    DEBUG_functionVersion: DEBUG_functionVersion
    DEBUG_serviceSettingDeployWebApp: DEBUG_serviceSettingDeployWebApp
    DEBUG_webAppRuntime: DEBUG_webAppRuntime
    DEBUG_webAppRuntimeVersion: DEBUG_webAppRuntimeVersion
    DEBUG_aseSku: DEBUG_aseSku
    DEBUG_aseSkuCode: DEBUG_aseSkuCode
    DEBUG_aseSkuWorkers: DEBUG_aseSkuWorkers
    DEBUG_serviceSettingDeployContainerApps: DEBUG_serviceSettingDeployContainerApps
    DEBUG_serviceSettingDeployAppInsightsDashboard: DEBUG_serviceSettingDeployAppInsightsDashboard
    DEBUG_aca_a_registry_image: DEBUG_aca_a_registry_image
    DEBUG_aca_w_registry_image: DEBUG_aca_w_registry_image
    DEBUG_serviceSettingDeployBingSearch: DEBUG_serviceSettingDeployBingSearch
    DEBUG_serviceSettingDeployCosmosDB: DEBUG_serviceSettingDeployCosmosDB
    DEBUG_serviceSettingDeployAzureOpenAI: DEBUG_serviceSettingDeployAzureOpenAI
    DEBUG_serviceSettingDeployAzureAIVision: DEBUG_serviceSettingDeployAzureAIVision
    DEBUG_serviceSettingDeployAzureSpeech: DEBUG_serviceSettingDeployAzureSpeech
    DEBUG_serviceSettingDeployAIDocIntelligence: DEBUG_serviceSettingDeployAIDocIntelligence
    DEBUG_disableContributorAccessForUsers: DEBUG_disableContributorAccessForUsers
    DEBUG_serviceSettingDeployPostgreSQL: DEBUG_serviceSettingDeployPostgreSQL
    DEBUG_serviceSettingDeployRedisCache: DEBUG_serviceSettingDeployRedisCache
    DEBUG_serviceSettingDeploySQLDatabase: DEBUG_serviceSettingDeploySQLDatabase
    DEBUG_BYO_subnets: DEBUG_BYO_subnets
    DEBUG_network_env_dev: DEBUG_network_env_dev
    DEBUG_network_env_stage: DEBUG_network_env_stage
    DEBUG_network_env_prod: DEBUG_network_env_prod
    DEBUG_vnetResourceGroup_param: DEBUG_vnetResourceGroup_param
    DEBUG_vnetNameFull_param: DEBUG_vnetNameFull_param
    DEBUG_commonResourceGroup_param: DEBUG_commonResourceGroup_param
    DEBUG_datalakeName_param: DEBUG_datalakeName_param
    DEBUG_kvNameFromCOMMON_param: DEBUG_kvNameFromCOMMON_param
    DEBUG_useCommonACR_override: DEBUG_useCommonACR_override
    DEBUG_subnetCommon: DEBUG_subnetCommon
    DEBUG_subnetCommonScoring: DEBUG_subnetCommonScoring
    DEBUG_subnetCommonPowerbiGw: DEBUG_subnetCommonPowerbiGw
    DEBUG_subnetProjGenAI: DEBUG_subnetProjGenAI
    DEBUG_subnetProjAKS: DEBUG_subnetProjAKS
    DEBUG_subnetProjACA: DEBUG_subnetProjACA
    DEBUG_subnetProjDatabricksPublic: DEBUG_subnetProjDatabricksPublic
    DEBUG_subnetProjDatabricksPrivate: DEBUG_subnetProjDatabricksPrivate
    DEBUG_byoASEv3: DEBUG_byoASEv3
    DEBUG_byoAseFullResourceId: DEBUG_byoAseFullResourceId
    DEBUG_byoAseAppServicePlanResourceId: DEBUG_byoAseAppServicePlanResourceId
    DEBUG_enablePublicGenAIAccess: DEBUG_enablePublicGenAIAccess
    DEBUG_allowPublicAccessWhenBehindVnet: DEBUG_allowPublicAccessWhenBehindVnet
    DEBUG_enablePublicAccessWithPerimeter: DEBUG_enablePublicAccessWithPerimeter
    DEBUG_admin_aifactorySuffixRG: DEBUG_admin_aifactorySuffixRG
    DEBUG_admin_commonResourceSuffix: DEBUG_admin_commonResourceSuffix
    DEBUG_admin_prjResourceSuffix: DEBUG_admin_prjResourceSuffix
    DEBUG_aifactory_salt: DEBUG_aifactory_salt
    DEBUG_admin_projectType: DEBUG_admin_projectType
    DEBUG_project_number_000: DEBUG_project_number_000
    DEBUG_project_service_principal_AppID_seeding_kv_name: DEBUG_project_service_principal_AppID_seeding_kv_name
    DEBUG_project_service_principal_OID_seeding_kv_name: DEBUG_project_service_principal_OID_seeding_kv_name
    DEBUG_project_service_principal_Secret_seeding_kv_name: DEBUG_project_service_principal_Secret_seeding_kv_name
    DEBUG_project_IP_whitelist: DEBUG_project_IP_whitelist
    DEBUG_deployModel_gpt_4: DEBUG_deployModel_gpt_4
    DEBUG_deployModel_text_embedding_ada_002: DEBUG_deployModel_text_embedding_ada_002
    DEBUG_deployModel_text_embedding_3_large: DEBUG_deployModel_text_embedding_3_large
    DEBUG_deployModel_text_embedding_3_small: DEBUG_deployModel_text_embedding_3_small
    DEBUG_deployModel_gpt_4o_mini: DEBUG_deployModel_gpt_4o_mini
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// VM Admin Login Permissions (if storage already exists)

module vmAdminLoginPermissions '../modules/vmAdminLoginRbac.bicep' = if (!resourceExists.storageAccount1001) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '01-VMAdminLogin4${deploymentProjSpecificUniqueSuffix}'
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
