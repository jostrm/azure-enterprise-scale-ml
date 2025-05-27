targetScope = 'subscription' // We dont know PROJECT RG yet. This is what we are to create.

@description('UPDATE AIFactory (Long Term Support branches): If you want to upgrade the AIFactory Long Term Support branches. E.g. if you go from submodule RELEASE_BRANCH_120_LTS to RELEASE_BRANCH_121_LTS your AIFactory will be upgraded to 1.21 (add new private dns zones, etc)')
param aifactoryVersionMajor int = 1
param aifactoryVersionMinor int = 20
var activeVersion = 121
param useAdGroups bool = false

// Enable baseline services: default ON
param enableAIServices bool = true
param enableAIFoundryHub bool = true
param enableAISearch bool = true

// Optional services, default OFF
param enableAML bool = false
param enableAMLv2 bool = true

// Existing resources
param aiHubExists bool = false
param aifProjectExists bool = false
param openaiExists bool = false
param amlExists bool = false
param aiSearchExists bool = false
param dashboardInsightsExists bool = false
param applicationInsightExists bool = false
param aiServicesExists bool = false
param bingExists bool = false
param containerAppsEnvExists bool = false
param containerAppAExists bool = false
param containerAppWExists bool = false
param cosmosDBExists bool = false
param functionAppExists bool = false
param webAppExists bool = false
param funcAppServicePlanExists bool = false
param webAppServicePlanExists bool = false
param keyvaultExists bool = false
param miACAExists bool = false
param miPrjExists bool = false
param storageAccount1001Exists bool = false
param storageAccount2001Exists bool = false
param aifExists bool = false
param redisExists bool = false
param postgreSQLExists bool = false
param sqlServerExists bool = false
param sqlDBExists bool = false
param acrProjectExists bool = false
param vmExists bool = false

var resourceExists = {
  aiHub: aiHubExists
  aiHubProject: aifProjectExists
  aml: amlExists
  openai: openaiExists
  aiSearch: aiSearchExists
  dashboardInsights: dashboardInsightsExists
  applicationInsight: applicationInsightExists
  aiServices: aiServicesExists
  bing: bingExists
  containerAppsEnv: containerAppsEnvExists
  containerAppA: containerAppAExists
  containerAppW: containerAppWExists
  cosmosDB: cosmosDBExists
  functionApp: functionAppExists
  webApp: webAppExists
  funcAppServicePlan: funcAppServicePlanExists
  webAppServicePlan: webAppServicePlanExists
  keyvault: keyvaultExists
  miACA: miACAExists
  miPrj: miPrjExists
  storageAccount1001: storageAccount1001Exists
  storageAccount2001: storageAccount2001Exists
  aif: aifExists
  redis: redisExists
  postgreSQL: postgreSQLExists
  sqlServer: sqlServerExists
  sqlDB: sqlDBExists
  acrProject: acrProjectExists
  vm:vmExists
}

/*
resource openaiREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if(resourceExists.openai || serviceSettingDeployAzureOpenAI) {
  name: aoaiName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource aiHubREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if(resourceExists.aiHub || enableAIFoundryHub) { 
  name: aiHubName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
resource aiHubProjectREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if(resourceExists.aiHubProject || enableAIFoundryHub) { 
  name: aifProjectName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
resource aiSearchREF 'Microsoft.Search/searchServices@2024-03-01-preview' existing = if(resourceExists.aiSearch || enableAISearch) { 
  name: safeNameAISearch
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

// Aml
resource amlREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if(resourceExists.aml || enableAML) { 
  name: amlName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
// WebApp
resource webappREF 'Microsoft.Web/sites@2022-09-01' existing = if(resourceExists.webApp || serviceSettingDeployWebApp) {
  name: webAppName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
// FunctionApp
resource functionREF 'Microsoft.Web/sites@2022-09-01' existing = if(resourceExists.functionApp || serviceSettingDeployFunction) {
  name: webAppName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource containerAppsEnvREF 'Microsoft.App/managedEnvironments@2025-01-01' existing = if(resourceExists.containerAppsEnv || serviceSettingDeployContainerApps) {
  name: containerAppsEnvName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP081
resource bingREF 'Microsoft.Bing/accounts@2020-06-10' existing = if(resourceExists.bing || serviceSettingDeployBingSearch) {
  name: bingName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
// BASELINE: Kv, ApplicationInsights,Storage, 
resource kvREF 'Microsoft.KeyVault/vaults@2023-07-01' existing = if(resourceExists.keyvault) { 
  name: keyvaultName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

*/

/* Random salt */
/*
resource miACAREF 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if(resourceExists.miACA) {
  name: miACAName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
resource miPrjREF 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if(resourceExists.miPrj) {
  name: miPrjName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource aiServicesREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if(resourceExists.aiServices ||enableAIServices) {
  name: aiServicesName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource storageAccount1001REF 'Microsoft.Storage/storageAccounts@2024-01-01' existing = if(resourceExists.storageAccount1001) {
  name: storageAccount1001Name
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
resource storageAccount2001REF 'Microsoft.Storage/storageAccounts@2024-01-01' existing = if(resourceExists.storageAccount2001) {
  name: storageAccount2001Name
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource appInsightsREF 'Microsoft.Insights/components@2020-02-02' existing = if(resourceExists.applicationInsight || serviceSettingDeployAppInsightsDashboard) {
  name: applicationInsightName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
*/

// Random salt END

param zoneAzurecontainerappsExists bool = false
param zoneRedisExists bool = false
param zonePostgresExists bool = false
param zoneSqlExists bool = false
param zoneMongoExists bool = false

// Optional override
param bastionName string = ''
param bastionResourceGroup string = ''
param bastionSubscription string = ''
param vnetNameFullBastion string = ''

param privateDnsAndVnetLinkAllGlobalLocation bool=false
param azureMachineLearningObjectId string =''
@description('If you want to use a common Azure Container Registry, in the AI Factory COMMON resourcegroup, set this to true')
param useCommonACR bool = true

param vmSKUSelectedArrayIndex int = 2
param vmSKU array = [
  'Standard_E2s_v3'
  'Standard_D4s_v3'
  'standard_D2as_v5'
]
@description('The API version of the OpenAI resource')
param openAiApiVersion string = '2024-08-01-preview'
// Cognitive Service types & settings
@allowed([
  'AIServices'
  'OpenAI'
  'ContentSafety'
])
param kindAOpenAI string = 'OpenAI'
param kindContentSafety string = 'ContentSafety'
param kindAIServices string = 'AIServices'
param apiVersionOpenAI string =  '2024-08-01-preview'
param modelVersionGPT4 string = 'turbo-2024-04-09' // GPT-4 Turbo with Vision https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models#o1-preview-and-o1-mini-models-limited-access
param modelVersionEmbedding string = 'text-embedding-3-large'
param modelVersionEmbeddingVersion string = '1'
param restore bool = false
param keyvaultEnablePurgeProtection bool = true // The property "enablePurgeProtection" cannot be set to false.
param disableLocalAuth bool = true
param enablePublicAccessWithPerimeter bool = false

@allowed([
  'S0' // 'Free': Invalid SKU name
  'S1' // 'Basic': Invalid SKU name
  'standard'
  'standard2' // 0 out of 0 quota, is default, apply to get this.
])
param aiSearchSKUSharedPrivate string = 'standard' // Needed for shared Private Endpoints  https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity#shared-private-link-resource-limits
@allowed([
  'Free'
  'S0'
  'S1'
  'S2'
  'S3'
])
param csContentSafetySKU string = 'S0' // 'Basic' = S0
param csSpeechSKU string = 'S0'
param csVisionSKU string = 'F0'
param csDocIntelligenceSKU string = 'S0'
param csAIservicesSKU string = 'S0'
param csOpenAISKU string = 'S0'
param keyvaultSoftDeleteDays int=90
/*
@allowed([
  '1106-Preview'
  '0613'
  'vision-preview'
  'turbo-2024-04-0'
])
*/
param modelGPT4Version string = '1106-Preview' // If your region doesn't support this version, please change it.

param serviceSettingDeployAppInsightsDashboard bool = true
// ### FALSE as default - START ### 
param serviceSettingDeployBingSearch bool = false
param bingSearchSKU string = 'G1'

// Standalone: Speech, Vision, DocIntelligence
@description('Service setting: Deploy Azure AI Document Intelligence for project')
param serviceSettingDeployAIDocIntelligence bool = false
@description('Service setting: Deploy Azure Speech for project')
param serviceSettingDeployAzureSpeech bool = false

// User access: standalone/Bastion
@description('Service setting: Deploy VM for project')
param serviceSettingDeployProjectVM bool = false
@description('Service setting:Deploy Azure Machine Learning - classic, not in hub mode')
//param serviceSettingDeployAzureMLClassic bool = false

// Databases:PostGreSQL
param serviceSettingDeployPostgreSQL bool = false
param postgreSQLSKU_Name string = 'Standard_B1ms' // Basic tier with 1 vCore
param postgreSQLSKU_Tier string = 'Burstable'     // Burstable tier
param postgreSQLSKU_Family string = 'Gen5'        // Generation 5 hardware
param postgreSQLSKU_Capacity int = 1           // 1 vCore
var postgreSQLSKU = {
  name: postgreSQLSKU_Name 
  tier: postgreSQLSKU_Tier
  family: postgreSQLSKU_Family
  capacity: postgreSQLSKU_Capacity
}
param postgreSQLStorage_Size int = 32 // 32 GB of storage
param postgreSQLStorage_Iops int = 120 // Input/output operations per second
param postgreSQLStorage_AutoGrow bool = true // Enable auto-grow for storage
var postgreSQLStorage = {
  storageSizeGB: postgreSQLStorage_Size
  iops: postgreSQLStorage_Iops         
  autoGrow: postgreSQLStorage_AutoGrow
}
param postgreSQLVersion string = '16' // PostgreSQL version

// Databases:REDIS
param serviceSettingDeployRedisCache bool = false
@allowed([
  'Basic'
  'Premium'
  'Standard'
])
param redisSKU string = 'Standard' // 'Basic' 'Standard' 'Premium'

// Databases:SQL Database
param serviceSettingDeploySQLDatabase bool = false
param sqlServerSKU string = 'Standard'
param sqlServerCapacity int = 10
param sqlServerTier string = 'Standard'
param sqlServerFamily string = 'Gen5'
param sqlServerStorageSize int = 32
var sqlServerSKUObject = ''
/*
var sqlServerSKUObject = {
  name: sqlServerSKU
  family: sqlServerFamily
  size: sqlServerStorageSize
  tier: sqlServerTier
  capacity: sqlServerCapacity
}
      name: skuObject.name // Ensure 'name' is provided in skuObject
    family: skuObject.family // Optional: Add other properties if needed
    size: skuObject.size // Optional: Add other properties if needed
    tier: skuObject.tier // Optional: Add other properties if needed
    capacity: skuObject.capacity // Optional: Add other properties if applicable
*/

// Databases:CosmosDB
param serviceSettingDeployCosmosDB bool = false
param cosmosTotalThroughputLimit int = 1000
param cosmosKind string = 'GlobalDocumentDB'
param cosmosMinimalTlsVersion string = 'Tls12' //<-docs error -> 'Tls1_2'

// Databases

// Apps
param serviceSettingDeployContainerApps bool = false
param acaImageName string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param acaCustomDomainsArray array = []
param acaAppWorkloadProfileName string = '' // 'Consumption' 
param containerCpuCoreCount int = 1 // 0.5, 1.0, 2.0, 4.0, 8.0
param containerMemory string = '2.0Gi' // 0.5Gi, 1.0Gi, 2.0Gi, 4.0Gi, 8.0Gi
param wlProfileDedicatedName string = 'D4' // 'D4', 'D8', 'D16', 'D32', 'D64', 'E4', 'E8'
param wlProfileGPUConsumptionName string = 'Consumption-GPU-NC24-A100'
param wlMinCountServerless int = 0
param wlMinCountDedicated int = 1
param wlMaxCount int = 5

param serviceSettingDeployFunction bool = false
param functionRuntime string = 'python' //'node', 'dotnet', 'java', 'python'
param functionPyVersion string = '3.11'
param functionSKU object = {
  name: 'EP1' // Private endpoint support
  tier: 'ElasticPremium'
  family: 'EP'
  capacity: 1
}

@description('Service setting:Deploy Azure WebApp')
param serviceSettingDeployWebApp bool = false
param webAppRuntime string = 'python'  // Set to 'python' for Python apps
param webAppRuntimeVersion string = '3.11'  // Specify the Python version
@description('Optional. Site redundancy mode.')
@allowed([
  'ActiveActive'
  'Failover'
  'GeoRedundant'
  'Manual'
  'None'
])
param appRedundancyMode string = 'None'
param byoACEv3 bool = false // Optional, default is false. Set to true if you want to deploy ASE v3 instead of Multitenant App Service Plan.
param byoAceFullResourceId string = '' // Full resource ID of App Service Environment
param byoAceAppServicePlanResourceId string = '' // Full resource ID, default is empty. Set to the App Service Plan ID if you want to deploy ASE v3 instead of Multitenant App Service Plan.

param webappSKU object = {
  name: 'S1'
  tier: 'Standard'
  capacity: 1
}
@description('Service setting: Deploy Content Safety for project')
param serviceSettingDeployContentSafety bool = false
@description('Service setting: Deploy Azure OpenAI for project')
param serviceSettingDeployAzureOpenAI bool = false
@description('Service setting: Deploy Azure AI Vision for project')
param serviceSettingDeployAzureAIVision bool = true

// TODO: vnet in in other region, to create private endpoint, and then peer vNets
//p-prj001-aisearch-genai was not found. Please make sure that the referenced resource exists, and that both resources are in the same region.","
param serviceSettingOverrideRegionAzureAIVision string = ''
param serviceSettingOverrideRegionAzureAIVisionShort string = ''
param serviceSettingOverrideRegionAzureAISearch string = ''
param serviceSettingOverrideRegionAzureAISearchShort string = ''

@description('Service setting:Deploy AIHub, e.g. Azure Machine Learning in AI hub mode, with AIServices and 1 project')
param serviceSettingEnableAIFoundryPreview bool = false
param disableContributorAccessForUsers bool = false

// ### TRUE as default - END ###

@allowed([
  'disabled'
  'free'
  'standard'
])
param semanticSearchTier string = 'free' //   'disabled' 'free' 'standard'
@allowed([
  'S0' // 'Free': Invalid SKU name
  'S1' // 'Basic': Invalid SKU name
  'standard'
  'standard2' // 0 out of 0 quota, is default, apply to get this.
])
param aiSearchSKUName string = 'standard' // 'basic' gav error?  // 'basic' 'standard', 'standard2' if using sharedPrivateLinks ('S0,S1,standard,standard2')
param aiSearchEnableSharedPrivateLink bool = false
param aiSearchEnableSharedPrivateLink_DOCS string = 'https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity#shared-private-link-resource-limits'

@description('Default is false. May be needed if Azure OpenAI should be public, which is neeed for some features, such as Azure AI Studio on your data feature.')
param enablePublicNetworkAccessForCognitive bool = true
@description('Default is true. May be needed if Azure AI Search, if it should be public, which is neeed for some features, such as Azure AI Foudnry on your data feature.')
param enablePublicNetworkAccessForAISearch bool = true
@description('Default is false. May be needed if Azure Storage used by AI Search, if it should be public, which is neeed for some features, such as Azure AI Studio on your data feature.')
param enablePublicNetworkAccessFoAIStorage bool = false
@description('Default is false. If true, it will flip all flags for GenAI RAG, such as Azure OpenAI, Azure AI Search, CosmosDB, WebApp, Azure Machine Learning')
param enablePublicGenAIAccess bool = false
@description('Default is false.')
param allowPublicAccessWhenBehindVnet bool = false

// Azure Machine Learning
param aks_dev_sku_override string = ''  // Override: AKS -  Azure Machine Learning
param aks_test_prod_sku_override string = ''
param aks_version_override string = ''
param aks_dev_nodes_override int = -1
param aks_test_prod_nodes_override int = -1
param aml_ci_dev_sku_override string = '' // Override: AML Compute Instance -  Azure Machine Learning 
param aml_ci_test_prod_sku_override string = ''
param aml_cluster_dev_sku_override string = '' // Override: AML Compute Custer -  Azure Machine Learning 
param aml_cluster_test_prod_sku_override string = ''
param aml_cluster_dev_nodes_override int = -1
param aml_cluster_test_prod_nodes_override int = -1
// Networking - AML

@description('Paramenter file dynamicNetworkParams.json contains this. Specifies the id of the AKS subnet that should be used by new AKS instance')
param aksSubnetId string
param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aksDockerBridgeCidr string = '172.17.0.1/16'
// Azure Machine Learning - END

// Networking: GenAI 
@description('Paramenter file dynamicNetworkParams.json contains this. Written after dynamic IP calculation is done')
param genaiSubnetId string
param acaSubnetId string = ''

// Seeding Keyvault & Bastion access
@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvault string
@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvaultResourcegroup string
@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvaultSubscription string
@description('Private VM Bastion: saved to keyvault and used by local admin user on VM')
param adminPassword string
@description('Private VM Bastion:The username of the local admin that is created on VM')
param adminUsername string

// Metadata
@description('tags for common resources')
param tags object
param location string
@description('Such as "weu" or "swc" (swedencentral datacenter).Reflected in resource group and sub-resources')
param locationSuffix string
@description('Specifies the project number, such as a string "005". This is used to generate the projectName to embed in resources such as "prj005"')
param projectNumber string

// Metadata &  Dummy parameters, since same json parameterfile has more parameters than this bicep file
@description('Meta. Needed to calculate subnet: subnetCalc and genDynamicNetworkParamFile')
param vnetResourceGroupBase string // Meta
param addBastionHost bool= false // Dummy: Do not correspond to any parameters defined in the template: 'addBastionHost'

// Environment
@allowed([
  'dev'
  'test'
  'prod'
])
@description('Specifies the name of the environment [dev,test,prod]. This name is reflected in resource group and sub-resources')
param env string

// Performance
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
param skuNameStorage string = 'Standard_ZRS'
@description('RBAC purposes:ObjectID to set Contributor on project resource group. ESML CoreTeam assigned to help project. Will be used for RBAC')

// RBAC - Optionally add a super-admin in core team: UserObjectId
param technicalContactId string=''
@description('ESML CoreTeam assigned to help project. Specifies technical contact email and will be used for tagging')
param technicalContactEmail string=''
@description('RBAC: Specifies the tenant id')

param tenantId string
// RBAC: AzureDevops Variable Overrides: Microsft EntraID ObjectID, can be a semicolon-separeted array
@description('Semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf". AzureDevops Variable Overrides')
param technicalAdminsObjectID string = 'null'
@description('Semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf". AzureDevops Variable Overrides.')
param technicalAdminsEmail string = 'null'
@description('Whitelist IP addresses from project members to see keyvault, and to connect via Bastion. AzureDevops Variable Overrides')
param IPwhiteList string = ''

@description('Name in keyvault for ObjectID of a user, service principal or security group in Microsoft EntraID. ') // OID: Get it by using Get-AzADUser or Get-AzADServicePrincipal cmdlet
param projectServicePrincipleOID_SeedingKeyvaultName string // Specifies the object ID of a user, service principal or security group in the Azure AD. The object ID must be unique for the list of access policies. 
@description('Project specific service principle KEYVAULT secret NAME to be added in kv for - Secret value ')
param projectServicePrincipleSecret_SeedingKeyvaultName string
@description('Project specific service principle KEYVAULT secret NAME for - App ID')
param projectServicePrincipleAppID_SeedingKeyvaultName string

// Networking
@description('Specifies the virtual network name')
param vnetNameBase string
@description('AI Factory suffix. If you have multiple instances example: -001')
param aifactorySuffixRG string
@description('Resources in common RG, the suffix on resources, example: -001')
param commonResourceSuffix string
@description('Resources in project RG, the suffix on resources, example: -001')
param resourceSuffix string
@description('(Required) true if Hybrid benefits for Windows server VMs, else FALSE for Pay-as-you-go')
param hybridBenefit bool

// Datalake
@description('Datalake GEN 2 storage account prefix. Max 8 chars.Example: If prefix is "marvel", then "marvelesml001[random5]dev",marvelesml001[random5]test,marvelesml001[random5]prod')
param commonLakeNamePrefixMax8chars string
@description('Datalake GEN 2 storage account')
param lakeContainerName string

// Metadata
@description('Specifies project specific tags that should be applied to newly created resources')
param projecttags object
@description('Specifies project owner email and will be used for tagging and RBAC')
param projectOwnerEmail string=''
@description('Specifies project owner objectId and will be used for tagging and RBAC')
param projectOwnerId string=''
@description('not set in genai-1')
param databricksOID string = 'not set in genai-1'
@description('not set in genai-1')
param databricksPrivate bool = false
@description('not set in genai-1')
param AMLStudioUIPrivate bool = false

var subscriptionIdDevTestProd = subscription().subscriptionId
@description('ESML COMMON Resource Group prefix. If "rg-msft-word" then "rg-msft-word-esml-common-weu-dev-001"')
param commonRGNamePrefix string
@description('Common default subnet')
param common_subnet_name string // TODO - 31-network.bicep for own subnet
@description('True for centralized Private DNS Zones in HUB. False is default: that ESML run standalone/demo mode, which creates private DnsZones, DnsZoneGroups, and vNetLinks in own resource group. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false

// Networking & Overrides RG, vnet, datalakename, kvNameFromCOMMON
param commonResourceGroup_param string = ''
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param datalakeName_param string = ''
param kvNameFromCOMMON_param string = ''
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''
param DOCS_byovnet_example string = ''
param DOCS_byosnet_common_example string = ''
param DOCS_byosnet_project_example string = ''
param BYO_subnets bool = false
param network_env string =''
param subnetCommon string = ''
param subnetCommonScoring string = ''
param subnetCommonPowerbiGw string = ''
param subnetProjGenAI string = ''
param subnetProjAKS string = ''
param subnetProjACA string = ''
param subnetProjDatabricksPublic string = ''
param subnetProjDatabricksPrivate string = ''
param enableDebugging bool = false
param randomValue string = newGuid()

// Parameters to variables
var vnetNameFull = vnetNameFull_param != '' ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

// ESML convention (that you may override)
var projectName = 'prj${projectNumber}'
var cmnName = 'cmn'
var genaiName = 'genai'
var commonResourceGroup = commonResourceGroup_param != '' ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}esml-${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}-rg'
var vnetResourceGroupName = vnetResourceGroup_param != '' ? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup
var subscriptions_subscriptionId = subscription().id
var vnetId = '${subscriptions_subscriptionId}/resourceGroups/${vnetResourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetNameFull}'

// BYOSubnet: common_subnet_name,common_subnet_scoring_name,common_pbi_subnet_name,common_bastion_subnet_name
var common_subnet_name_local = subnetCommon != '' ? replace(subnetCommon, '<network_env>', network_env) : common_subnet_name

// Troubleshooting001
//var common_subnet_name_local = common_subnet_name_local_1 != '' ? common_subnet_name_local_1 : 'acme-tst-common-eus2-subnet'

// Gen genaiSubnetName from genaiSubnetId which is resourceID
var segments = split(genaiSubnetId, '/')
var genaiSubnetName = segments[length(segments) - 1] // Get the last segment, which is the subnet name
var defaultSubnet = genaiSubnetName

var segmentsAKS = split(aksSubnetId, '/')
var aksSubnetName = segmentsAKS[length(segmentsAKS) - 1] // Get the last segment, which is the subnet name

var segmentsACA = split(acaSubnetId, '/')
var acaSubnetName = segmentsACA[length(segmentsACA) - 1] // Get the last segment, which is the subnet name

// RBAC
var ipWhitelist_array_1 = array(split(replace(IPwhiteList, '\\s+', ''), ','))
var ipWhitelist_array = (empty(IPwhiteList) || IPwhiteList == 'null') ? [] : union(ipWhitelist_array_1,[]) // remove dups

var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,'\\s+', ''),','))
var p011_genai_team_lead_array = (empty(technicalAdminsObjectID) || technicalAdminsObjectID == 'null') ? [] : union(technicalAdminsObjectID_array,[])

var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var p011_genai_team_lead_email_array = (empty(technicalAdminsEmail) || technicalAdminsEmail == 'null') ? [] : technicalAdminsEmail_array

//AI Services,Storage Do not allow /32 - "The prefix must be smaller than or equal to 30."
var processedIpRulesSa = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: endsWith(ip, '/32') ? substring(ip, 0, length(ip) - 3) : ip
}]
var processedIpRulesAIServices = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: endsWith(ip, '/32') ? substring(ip, 0, length(ip) - 3) : ip
}]

// Kv+AIHuv -> Do allow and prefer /32
var processedIpRulesKv = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]
var processedIpRulesAIHub = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]
// AI Search - Cannot have overlappning subnets. But /24 or /32 is allowed for AI Search
var processedIpRulesAISearch = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

var ipWhitelist_remove_ending_32 = [for ip in ipWhitelist_array: endsWith(ip, '/32') ? substring(ip, 0, length(ip) - 3) : ip]
var ipWhitelist_remove_ending_slash_something = [for ip in ipWhitelist_array: (contains(ip, '/') ? substring(ip, 0, indexOf(ip, '/')) : ip)]

// Salt: Project/env specific
resource targetResourceGroupRefSalt 'Microsoft.Resources/resourceGroups@2020-10-01' existing = {
  name: targetResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}
resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}


param aifactorySalt5char string = '' // Determenistic. 
param aifactorySalt7char string = '' // Random
var projectSalt = substring(uniqueString(targetResourceGroupRefSalt.id), 0, 5)
var randomSalt = empty(aifactorySalt7char) || length(aifactorySalt7char) <= 4 ? substring(randomValue, 6, 10): aifactorySalt7char
var deploymentProjSpecificUniqueSuffix = '${projectName}${projectSalt}'

// Salt: AIFactory instance/env specific
var uniqueInAIFenv = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// Networking - Private DNS: Centralized or Standalone
var privDnsResourceGroupName = (privDnsResourceGroup_param != '' && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (privDnsSubscription_param != ''&& centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd
var prjResourceSuffixNoDash = replace(resourceSuffix,'-','')

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetNameFull
  scope: resourceGroup(vnetResourceGroupName)
}

// Get the CIDR address prefixes from the vNet's properties
var vnetAddressPrefixes = vnet.properties.addressSpace.addressPrefixes
// If you want just the first CIDR (most common case)
var vnetCidr = vnetAddressPrefixes[0]

// 2024-09-15: 25 entries, and special keyes
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

// 2024-09-15: 25 entries
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
  vault: {
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
    exists: false
  }
  {
    name: privateLinksDnsZones.file.name
    id: privateLinksDnsZones.file.id
    exists: false
  }
  {
    name: privateLinksDnsZones.dfs.name
    id: privateLinksDnsZones.dfs.id
    exists: false
  }
  {
    name: privateLinksDnsZones.queue.name
    id: privateLinksDnsZones.queue.id
    exists: false
  }
  {
    name: privateLinksDnsZones.table.name
    id: privateLinksDnsZones.table.id
    exists: false
  }
  {
    name: privateLinksDnsZones.registry.name
    id: privateLinksDnsZones.registry.id
    exists: false
  }
  {
    name: privateLinksDnsZones.registryregion.name
    id: privateLinksDnsZones.registryregion.id
    exists: false
  }
  {
    name: privateLinksDnsZones.vault.name
    id: privateLinksDnsZones.vault.id
    exists: false
  }
  {
    name: privateLinksDnsZones.amlworkspace.name
    id: privateLinksDnsZones.amlworkspace.id
    exists: false
  }
  {
    name: privateLinksDnsZones.notebooks.name
    id: privateLinksDnsZones.notebooks.id
    exists: false
  }
  {
    name: privateLinksDnsZones.dataFactory.name
    id: privateLinksDnsZones.dataFactory.id
    exists: false
  }
  {
    name: privateLinksDnsZones.portal.name
    id: privateLinksDnsZones.portal.id
    exists: false
  }
  {
    name: privateLinksDnsZones.openai.name
    id: privateLinksDnsZones.openai.id
    exists: false
  }
  {
    name: privateLinksDnsZones.searchService.name
    id: privateLinksDnsZones.searchService.id
    exists: false
  }
  {
    name: privateLinksDnsZones.azurewebapps.name
    id: privateLinksDnsZones.azurewebapps.id
    exists: false
  }
  {
    name: privateLinksDnsZones.cosmosdbnosql.name
    id: privateLinksDnsZones.cosmosdbnosql.id
    exists: false
  }
  {
    name: privateLinksDnsZones.cognitiveservices.name
    id: privateLinksDnsZones.cognitiveservices.id
    exists: false
  }
  {
    name: privateLinksDnsZones.azuredatabricks.name
    id: privateLinksDnsZones.azuredatabricks.id
    exists: false
  }
  {
    name: privateLinksDnsZones.namespace.name
    id: privateLinksDnsZones.namespace.id
    exists: false
  }
  {
    name: privateLinksDnsZones.azureeventgrid.name
    id: privateLinksDnsZones.azureeventgrid.id
    exists: false
  }
  {
    name: privateLinksDnsZones.azuremonitor.name
    id: privateLinksDnsZones.azuremonitor.id
    exists: false
  }
  {
    name: privateLinksDnsZones.azuremonitoroms.name
    id: privateLinksDnsZones.azuremonitoroms.id
    exists: false
  }
  {
    name: privateLinksDnsZones.azuremonitorods.name
    id: privateLinksDnsZones.azuremonitorods.id
    exists: false
  }
  {
    name: privateLinksDnsZones.azuremonitoragentsvc.name
    id: privateLinksDnsZones.azuremonitoragentsvc.id
    exists: false
  }
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
  }
]

output privateLinksDnsZones object = privateLinksDnsZones
// Baseline is already created in esml-common/main/13-rgLevel.bicep 
// Verify that at least 1 Private DNS zones exists in privDnsResourceGroupName and privDnsSubscription  before continuing
resource createPrivateDnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' existing = if (centralDnsZoneByPolicyInHub==false){
  name: 'privatelink.cognitiveservices.azure.com'
  scope:resourceGroup(privDnsSubscription,privDnsResourceGroupName)
}

var aifactoryVersionString = '${aifactoryVersionMajor}${aifactoryVersionMinor}'
var aifactoryVersion = empty(aifactoryVersionString) || !contains(aifactoryVersionString, '^[0-9]+$') 
    ? 999 
    : int(aifactoryVersionString)


//module createNewPrivateDnsZonesIfNotExists '../modules/createNewPrivateDnsZonesIfNotExists.bicep' = if(centralDnsZoneByPolicyInHub==false && int(aifactoryVersion) < activeVersion) {

@description('AIFACTORY-UPDATE-121')
module createNewPrivateDnsZonesIfNotExists '../modules/createNewPrivateDnsZonesIfNotExists.bicep' = if(centralDnsZoneByPolicyInHub==false ) {
  scope: resourceGroup(privDnsSubscription,privDnsResourceGroupName)
  name: 'createNewPrivateDnsZones${deploymentProjSpecificUniqueSuffix}'
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
    commonResourceGroupRef
  ]
}
// AIFACTORY-UPDATE-121-END

// ### End Create NEW Private DNS zones

var twoNumbers = substring(resourceSuffix,2,2) // -001 -> 01
var aiHubName = 'ai-hub-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var aifProjectName = 'aif-prj${projectNumber}-01-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var aoaiName = 'aoai-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var amlName = 'aml-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var safeNameAISearch = replace(toLower('aisearch${projectName}${locationSuffix}${env}${uniqueInAIFenv}${resourceSuffix}'), '-', '')
var dashboardInsightsName = 'AIFactory${aifactorySuffixRG}-${projectName}-insights-${env}-${uniqueInAIFenv}${resourceSuffix}'
var applicationInsightName = 'ain-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var bingName = 'bing-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var containerAppsEnvName = 'aca-env-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var containerAppAName = 'aca-a-${projectName}${locationSuffix}${env}${uniqueInAIFenv}${resourceSuffix}'
var containerAppWName = 'aca-w-${projectName}${locationSuffix}${env}${uniqueInAIFenv}${resourceSuffix}'
var cosmosDBName = 'cosmos-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var functionAppName = 'func-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var webAppName = 'webapp-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var funcAppServicePlanName = 'func-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}-plan'
var webbAppServicePlanName = 'webapp-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}-plan'
var keyvaultName = 'kv-p${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${twoNumbers}'
var storageAccount1001Name = replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}1${prjResourceSuffixNoDash}${env}', '-', '')
var storageAccount2001Name = replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}2${prjResourceSuffixNoDash}${env}', '-', '')
var acrProjectName = 'acr${projectName}${genaiName}${locationSuffix}${uniqueInAIFenv}${env}${prjResourceSuffixNoDash}'
var aifName ='aif-hub-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var redisName ='redis-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var postgreSQLName ='pg-flex-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var sqlServerName ='sql-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var sqlDBName ='sqldb-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var vmName = 'dsvm-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'

// Random salt for project specific resources
var miACAName = 'mi-aca-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${resourceSuffix}'
var miPrjName = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${resourceSuffix}'
var aiServicesName = 'ai-services-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}-${randomSalt}${prjResourceSuffixNoDash}'
//var miACAName = 'mi-aca-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
//var miPrjName = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
//var aiServicesName = 'aiservices${projectName}${locationSuffix}${env}${uniqueInAIFenv}${prjResourceSuffixNoDash}'

// Common RG
var acrCommonName = replace('acrcommon${uniqueInAIFenv}${locationSuffix}${commonResourceSuffix}${env}','-','')
var laWorkspaceName = 'la-${cmnName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'

resource subnet_genai_ref 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: defaultSubnet
  parent: vnet
}
resource subnet_aks_ref 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: aksSubnetName
  parent: vnet
}

// Resource Groups
module projectResourceGroup '../modules/resourcegroupUnmanaged.bicep' = {
  scope: subscription(subscriptionIdDevTestProd)
  name: 'prjRG${deploymentProjSpecificUniqueSuffix}'
  params: {
    rgName: targetResourceGroup
    location: location
    tags: projecttags
  }
}

module miForPrj '../modules/mi.bicep' = if(!resourceExists.miPrj){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
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

output debug_vnetId string = vnetId
output debug_common_subnet_name_local string = common_subnet_name_local
output debug_genaiSubnetId string = genaiSubnetId
output debug_genaiSubnetName string = genaiSubnetName
output debug_defaultSubnet string = defaultSubnet
output debug_aksSubnetId string = aksSubnetId
output debug_aksSubnetName string = aksSubnetName
