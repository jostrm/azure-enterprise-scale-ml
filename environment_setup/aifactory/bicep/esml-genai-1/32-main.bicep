targetScope = 'subscription' // We dont know PROJECT RG yet. This is what we are to create.

@description('UPDATE AIFactory (Long Term Support branches): If you want to upgrade the AIFactory Long Term Support branches. E.g. if you go from submodule RELEASE_BRANCH_120_LTS to RELEASE_BRANCH_121_LTS your AIFactory will be upgraded to 1.21 (add new private dns zones, etc)')
param aifactoryVersionMajor int = 1
param aifactoryVersionMinor int = 20
var activeVersion = 121
param useAdGroups bool = false

// Model settings
param deployModel_text_embedding_3_large bool = false // text-embedding-3-large
param deployModel_text_embedding_3_small bool = false // text-embedding-3-small Standard dose not exists in Sweden Central, and other regions
param deployModel_text_embedding_ada_002 bool = false // text-embedding-ada-002
param default_embedding_capacity int = 25
param deployModel_gpt_4o_mini bool = false // gpt-4o-mini
param default_gpt_capacity int = 40
param default_model_sku string = 'Standard'

param deployModel_gpt_4 bool = false 
param modelGPT4Name string = '' // GPT-4 or GPT-4.1 etc

// Enable baseline services: default ON
param enableAIServices bool = true
param enableAIFoundryHub bool = true
param enableAISearch bool = true

// Optional services, default OFF
param enableAzureMachineLearning bool = false

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


resource openaiREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if(resourceExists.openai) {
  name: aoaiName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource aiHubREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if(resourceExists.aiHub) { 
  name: aiHubName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource aiHubProjectREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if(resourceExists.aiHubProject) { 
  name: aifProjectName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource aiSearchREF 'Microsoft.Search/searchServices@2024-03-01-preview' existing = if(resourceExists.aiSearch) { 
  name: safeNameAISearch
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

// Aml
resource amlREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if(resourceExists.aml) { 
  name: amlName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
// WebApp
resource webappREF 'Microsoft.Web/sites@2022-09-01' existing = if(resourceExists.webApp) {
  name: webAppName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
// FunctionApp
resource functionREF 'Microsoft.Web/sites@2022-09-01' existing = if(resourceExists.functionApp) {
  name: functionAppName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource containerAppsEnvREF 'Microsoft.App/managedEnvironments@2025-01-01' existing = if(resourceExists.containerAppsEnv) {
  name: containerAppsEnvName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP081
resource bingREF 'Microsoft.Bing/accounts@2020-06-10' existing = if(resourceExists.bing) {
  name: bingName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
// BASELINE: Kv, ApplicationInsights,Storage, 
resource kvREF 'Microsoft.KeyVault/vaults@2023-07-01' existing = if(resourceExists.keyvault) { 
  name: keyvaultName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}


resource miACAREF 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if(resourceExists.miACA) {
  name: miACAName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
resource miPrjREF 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if(resourceExists.miPrj) {
  name: miPrjName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

resource aiServicesREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if(resourceExists.aiServices) {
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

resource appInsightsREF 'Microsoft.Insights/components@2020-02-02' existing = if(resourceExists.applicationInsight) {
  name: applicationInsightName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

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
param postgreSQLHighAvailability object = {
  mode: 'Disabled' // Default to Disabled, can be overridden
}
param postgresAvailabilityZone string = '1' // Default to zone 1, can be overridden
param postgreSQLSKU_Name string = 'Standard_B2s' // Basic tier with 1 vCore
param postgreSQLSKU_Tier string = 'Burstable'     // Burstable tier
var postgreSQLSKU = {
    name: postgreSQLSKU_Name
    tier: postgreSQLSKU_Tier
}
param postgreSQLStorage_Size int = 32 // 32 GB of storage
param postgreSQLStorage_Iops int = 120 // Input/output operations per second
param postgreSQLStorage_Tier string = 'P4' // Input/output operations per second
param postgreSQLStorage_AutoGrow string = 'Disabled' // Enable auto-grow for storage
var postgreSQLStorage ={
  iops: postgreSQLStorage_Iops
  tier: postgreSQLStorage_Tier
  storageSizeGB: postgreSQLStorage_Size
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
param sqlServerSKU_DTU string = 'S0'
param sqlServerTier_DTU string = 'Standard'
param sqlServerCapacity_DTU int = 10
var sqlServerSKUObject_DTU = {
  name: sqlServerSKU_DTU
  tier: sqlServerTier_DTU
  capacity: sqlServerCapacity_DTU
}

param sqlServerSKUName_vCore_Prefix string = 'GP' // Example: GP for GeneralPurpose, BC for BusinessCritical
param sqlServerFamily_vCore string = 'Gen5'     // Example: Gen5
param sqlServerTier_vCore string = 'GeneralPurpose'
param sqlServerCapacity_vCore int = 4
var sqlServerSKUObject_vCore = {
  name: '${sqlServerSKUName_vCore_Prefix}_${sqlServerFamily_vCore}_${sqlServerCapacity_vCore}' // Constructs 'GP_Gen5_4'
  tier: sqlServerTier_vCore
  family: sqlServerFamily_vCore
  capacity: sqlServerCapacity_vCore
}


// Databases:CosmosDB
param serviceSettingDeployCosmosDB bool = false
param cosmosTotalThroughputLimit int = 1000
param cosmosKind string = 'GlobalDocumentDB'
param cosmosMinimalTlsVersion string = 'Tls12' //<-docs error -> 'Tls1_2'

// Databases

// containerApps
param serviceSettingDeployContainerApps bool = false
param aca_default_image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param aca_a_registry_image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'  // 'docker.io/library/nginx:alpine'  | 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var imageRegistryTypeA = !empty(aca_a_registry_image) && contains(aca_a_registry_image, 'mcr.microsoft.com') 
  ? 'ms' 
  : !empty(aca_a_registry_image) && contains(aca_a_registry_image, 'docker.io') 
    ? 'dockerhub' 
    : 'private'

param aca_w_registry_image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest' // '${containerRegistryName}.${containerRegistryHostSuffix}/containerapps-default:latest'
var imageRegistryTypeW = !empty(aca_w_registry_image) && contains(aca_w_registry_image, 'mcr.microsoft.com') 
  ? 'ms' 
  : !empty(aca_w_registry_image) && contains(aca_w_registry_image, 'docker.io') 
    ? 'dockerhub' 
    : 'private'

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
@allowed([
  'dotnet'
  'node'
  'python'
  'java'
])
param functionRuntime string = 'python' //'node', 'dotnet', 'java', 'python'
@allowed([
  '3.7'
  '3.8'
  '3.9'
  '3.10'
  '3.11'
  '3.12'
  // Node.js versions
  '18-lts'
  '20-lts'
  // Java LTS versions
  '8'
  '11'
  '17'
  '21'
  // .NET versions
  'v4.8'
  'v6.0'
  'v7.0'
  'v8.0'
])
param functionVersion string = '3.11'
param functionSKU object = {
  name: 'EP1' // Private endpoint support
  tier: 'ElasticPremium'
  family: 'EP'
  capacity: 1
}

@description('Service setting:Deploy Azure WebApp')
param serviceSettingDeployWebApp bool = false
@allowed([
  'dotnet'
  'node'
  'python'
  'java'
])
param webAppRuntime string = 'python'  // Set to 'python' for Python apps
@allowed([
  '3.7'
  '3.8'
  '3.9'
  '3.10'
  '3.11'
  '3.12'
  // Node.js versions
  '18-lts'
  '20-lts'
  // Java LTS versions
  '8'
  '11'
  '17'
  '21'
  // .NET versions
  'v4.8'
  'v6.0'
  'v7.0'
  'v8.0'
])
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
var ipWhitelist_array = (empty(IPwhiteList) || IPwhiteList == 'null' || length(IPwhiteList) < 5) ? [] : union(ipWhitelist_array_1,[]) // remove dups

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


param aifactorySalt5char string = '' // Deterministic
param aifactorySalt10char string = '' // Random
var projectSalt = substring(uniqueString(targetResourceGroupRefSalt.id), 0, 5)
var randomSalt = empty(aifactorySalt10char) || length(aifactorySalt10char) <= 5 ? substring(randomValue, 6, 10): aifactorySalt10char
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
var aifProjectName = 'ai-prj${projectNumber}-01-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var aoaiName = 'aoai-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var amlName = 'aml-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var safeNameAISearch = replace(toLower('aisearch${projectName}${locationSuffix}${env}${uniqueInAIFenv}${resourceSuffix}'), '-', '') // AzureAISearch4prj0025kxmv
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
var redisName ='redis-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var postgreSQLName ='pg-flex-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var sqlServerName ='sql-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var sqlDBName ='sqldb-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var vmName = 'dsvm-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var aifName ='aifoundry-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var aifPrjName ='aifoundry-${projectName}-01-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'

// Random salt for project specific resources
var miACAName = 'mi-aca-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${resourceSuffix}'
var miPrjName = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${resourceSuffix}'
var aiServicesName = replace(toLower('aiservices${projectName}${locationSuffix}${env}${uniqueInAIFenv}${randomSalt}${prjResourceSuffixNoDash}'), '-', '') 

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


// VARS - only fetch .outputs once!
var var_miPrj_PrincipalId = resourceExists.miPrj? miPrjREF.properties.principalId: miForPrj.outputs.managedIdentityPrincipalId
var var_miAca_PrincipalId = resourceExists.miACA? miACAREF.properties.principalId: miForAca.outputs.managedIdentityPrincipalId
var var_search_pricipalId = resourceExists.aiSearch? aiSearchREF.identity.principalId: aiSearchService.outputs.principalId
//var var_webAppPrincipalId=resourceExists.webApp? webappREF.identity.principalId: webapp.outputs.principalId
var var_functionPrincipalId=resourceExists.functionApp? functionREF.identity.principalId: function.outputs.principalId
var var_openai_pricipalId = resourceExists.openai? openaiREF.identity.principalId: csAzureOpenAI.outputs.principalId
var var_aiServices_principalId = resourceExists.aiServices? aiServicesREF.identity.principalId: aiServices.outputs.aiServicesPrincipalId
var var_aml_principal_id = (!resourceExists.aml && enableAzureMachineLearning)? amlv2.outputs.principalId: (enableAzureMachineLearning && resourceExists.aml)? amlREF.identity.principalId:''

// Array vars
var mi_array = array(var_miPrj_PrincipalId)
var mi_array2 = array(var_miAca_PrincipalId)
var var_all_principals = union(p011_genai_team_lead_array, mi_array, mi_array2)

// Name vars
var var_kv1_name = resourceExists.keyvault? keyvaultName: kv1.outputs.keyvaultName
var var_kv1_uri = resourceExists.keyvault? kvREF.properties.vaultUri: kv1.outputs.keyvaultUri

var var_app_insight_aca = (serviceSettingDeployAppInsightsDashboard && !resourceExists.applicationInsight) 
  ? appinsights.outputs.name 
  : serviceSettingDeployAppInsightsDashboard? applicationInsightName: applicationInsightSWC.outputs.name

var var_acr_cmn_or_prj = useCommonACR? acrCommon2.outputs.containerRegistryName
  :resourceExists.acrProject? acrProjectName
  :acr.outputs.containerRegistryName

var var_aml_name = resourceExists.aml && enableAzureMachineLearning?amlName
  : enableAzureMachineLearning? amlv2.outputs.amlName: ''

var var_aca_env_name = resourceExists.containerAppsEnv && serviceSettingDeployContainerApps? containerAppsEnvName
  : serviceSettingDeployContainerApps? containerAppsEnv.outputs.environmentName: ''

var var_aca_env_id = resourceExists.containerAppsEnv && serviceSettingDeployContainerApps?containerAppsEnvREF.id
  : serviceSettingDeployContainerApps? containerAppsEnv.outputs.environmentId: ''

var var_storageAccountName=resourceExists.storageAccount1001? storageAccount1001Name: sacc.outputs.storageAccountName
var var_storageAccountName2=resourceExists.storageAccount2001? storageAccount2001Name: sa4AIsearch.outputs.storageAccountName
// empty() names: 
var var_aiSearchName=resourceExists.aiSearch? safeNameAISearch: enableAISearch? aiSearchService.outputs.aiSearchName: ''
var var_openAIName=resourceExists.openai? aoaiName: serviceSettingDeployAzureOpenAI? csAzureOpenAI.outputs.cognitiveName: ''
var var_aiServicesName=resourceExists.aiServices? aiServicesName: enableAIServices? aiServices.outputs.name: ''

// Endpoint vars
var var_openAIEndpoint = (!resourceExists.openai && serviceSettingDeployAzureOpenAI)
  ? csAzureOpenAI.outputs.azureOpenAIEndpoint
  : serviceSettingDeployAzureOpenAI? openaiREF.properties.endpoint: ''

var var_aiServicesOpenAIEndpoint = (!resourceExists.aiServices && enableAIServices)
  ? aiServices.outputs.openAIEndpoint
  : enableAIServices? aiServicesREF.properties.endpoint: ''

var var_aiservices_openai_endpoint = resourceExists.aiServices && enableAIServices? aiServicesREF.properties.endpoints['OpenAI Language Model Instance API'] 
  : enableAIServices? aiServices.outputs.openAIEndpoint: ''

var hostname = 'https://${safeNameAISearch}.search.windows.net'
var var_aisearch_endpoint = (!resourceExists.aiSearch && enableAISearch)
  ? aiSearchService.outputs.aiSearchEndpoint
  : enableAISearch? hostname: ''

var var_appinsights_connectionstring= !resourceExists.applicationInsight && serviceSettingDeployAppInsightsDashboard 
  ?appinsights.outputs.connectionString
  :serviceSettingDeployAppInsightsDashboard? appInsightsREF.properties.ConnectionString: ''

var var_bingName=(serviceSettingDeployBingSearch && !resourceExists.bing)? bing.outputs.bingName
  :serviceSettingDeployBingSearch? bingName: ''

var var_bing_endpoint=(serviceSettingDeployBingSearch)? 'https://api.bing.microsoft.com/':''
var var_bing_api_Key=(serviceSettingDeployBingSearch && !resourceExists.bing)? bing.outputs.bingApiKey
: serviceSettingDeployBingSearch && resourceExists.bing? bingREF.listKeys().key1:''

var var_aiProjectName=(enableAIFoundryHub && !resourceExists.aiHubProject) ?aiHub.outputs.aiProjectName: aifProjectName

// End of vars

module spAndMI2Array '../modules/spAndMiArray.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    managedIdentityOID: var_miPrj_PrincipalId
    servicePrincipleOIDFromSecret: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
  }
  dependsOn: [
    ...(resourceExists.miPrj ? [] : [miForPrj])
  ]
}
var spAndMiArray = spAndMI2Array.outputs.spAndMiArray

module debug './00-debug.bicep' = if(enableDebugging){
  name: 'debug${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
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
    common_subnet_name_local: common_subnet_name_local
    genaiSubnetId: genaiSubnetId
    genaiSubnetName: genaiSubnetName
    defaultSubnet: defaultSubnet
    aksSubnetId: aksSubnetId
    aksSubnetName: aksSubnetName
    debug_vnetId: vnetId
    subscriptions_subscriptionId:subscriptions_subscriptionId
    vnetRule1:'${vnetId}/subnets/${defaultSubnet}'
    vnetRule2:'${vnetId}/subnets/${aksSubnetName}'
    keyvaultExists: keyvaultExists
    aiSearchExists: aiSearchExists
    //postGreSQLExists: existingResource.outputs.postgreSQLExists
  }
}



// ------------------------------ RBAC ResourceGroups, Bastion,vNet, VMAdminLogin  ------------------------------//

module vmAdminLoginPermissions '../modules/vmAdminLoginRbac.bicep' = if(resourceExists.storageAccount1001){ // If storage exists, it is not the 1st time. Already set
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'VMAdminLogin4${deploymentProjSpecificUniqueSuffix}'
  params: {
    userId: technicalContactId
    userEmail: technicalContactEmail
    additionalUserEmails: p011_genai_team_lead_email_array
    additionalUserIds:p011_genai_team_lead_array
    useAdGroups:useAdGroups
  }
  dependsOn:[
    projectResourceGroup
    rbacModuleUsers
  ]
}

// ------------------------------ END:RBAC ResourceGroups, Bastion,vNet, VMAdminLogin  ------------------------------//

// ----DATALAKE
// ------------------------------ SERVICES - AI Studio, Azure OpenAI, Azure AI Search, Storage for Azure AI Search, Azure Content Safety ------------------------------//

module csContentSafety '../modules/csContentSafety.bicep' = if(serviceSettingDeployContentSafety==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'ContentSafety4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csContentSafetySKU
    location: location
    restore:restore
    vnetResourceGroupName: vnetResourceGroupName
    contentsafetyName: 'cs-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: kindContentSafety
    pendCogSerName: 'p-${projectName}-contentsafety-${genaiName}'
    subnetName:genaiSubnetName
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    vnetRules: [
      subnet_genai_ref.id
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsContentSafety '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployContentSafety == true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkContentSafety${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csContentSafety.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

module csVision '../modules/csVision.bicep' = if(serviceSettingDeployAzureAIVision==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'Vision4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csVisionSKU
    location: (!empty(serviceSettingOverrideRegionAzureAIVision)) ? serviceSettingOverrideRegionAzureAIVision : location
    restore:restore
    keyvaultName: var_kv1_name
    vnetResourceGroupName: vnetResourceGroupName
    name: (!empty(serviceSettingOverrideRegionAzureAIVisionShort))? 'vision-${projectName}-${serviceSettingOverrideRegionAzureAIVisionShort}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    :'vision-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: 'ComputerVision'
    pendCogSerName: 'p-${projectName}-vision-${genaiName}'
    subnetName:defaultSubnet
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    vnetRules: [
      subnet_genai_ref.id
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsVision '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployAzureAIVision == true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsVision${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csVision.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

module csSpeech '../modules/csSpeech.bicep' = if(serviceSettingDeployAzureSpeech==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AISpeech4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csSpeechSKU
    location: location
    restore:restore
    keyvaultName: var_kv1_name
    vnetResourceGroupName: vnetResourceGroupName
    name: 'speech-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: 'SpeechServices'
    pendCogSerName: 'p-${projectName}-speech-${genaiName}'
    subnetName:defaultSubnet
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    vnetRules: [
      subnet_genai_ref.id
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsSpeech '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployAzureSpeech == true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkSpeech${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csSpeech.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}


module csDocIntelligence '../modules/csDocIntelligence.bicep' = if(serviceSettingDeployAIDocIntelligence==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AIDocIntelligence4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csDocIntelligenceSKU
    location: location
    restore:restore
    keyvaultName: var_kv1_name
    vnetResourceGroupName: vnetResourceGroupName
    name: 'docs-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: 'FormRecognizer'
    pendCogSerName: 'p-${projectName}-docs-${genaiName}'
    subnetName:defaultSubnet
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    vnetRules: [
      subnet_genai_ref.id
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
  }
  dependsOn: [
    projectResourceGroup
    kv1
  ]
}

module privateDnsDocInt '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployAIDocIntelligence == true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsDocInt${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csDocIntelligence.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}


module aiServices '../modules/csAIServices.bicep' = if(!resourceExists.aiServices && enableAIServices) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AIServices4${deploymentProjSpecificUniqueSuffix}'
  params: {
    location: location
    sku: csAIservicesSKU
    tags: projecttags
    vnetResourceGroupName: vnetResourceGroupName
    cognitiveName: aiServicesName
    pendCogSerName: 'p-${projectName}-aiservices-${genaiName}'
    restore: restore
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    keyvaultName: var_kv1_name
    modelGPT4Version:modelGPT4Version
    kind: kindAIServices
    //acrNameDummy: useCommonACR? acrCommon2.name:acr.name // Workaround for conditional "dependsOn"
    publicNetworkAccess: enablePublicGenAIAccess
    vnetRules: [
      subnet_genai_ref.id
    ]
    ipRules: empty(processedIpRulesAIServices)?[]:processedIpRulesAIServices
    disableLocalAuth: disableLocalAuth
    privateLinksDnsZones: privateLinksDnsZones
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
    deployModel_gpt_4:deployModel_gpt_4
    modelGPT4Name:modelGPT4Name
    deployModel_gpt_4o_mini:deployModel_gpt_4o_mini // gpt-4o-mini
    deployModel_text_embedding_3_small:deployModel_text_embedding_3_small // text-embedding-3-small
    deployModel_text_embedding_3_large:deployModel_text_embedding_3_large // text-embedding-3-large
    deployModel_text_embedding_ada_002:deployModel_text_embedding_ada_002 // text-embedding-ada-002
    default_embedding_capacity: default_embedding_capacity
    default_gpt_capacity: default_gpt_capacity
    default_model_sku: default_model_sku
  }
  dependsOn: [
    projectResourceGroup
    ...(resourceExists.keyvault ? [] : [kv1])
    ...(useCommonACR ? [acrCommon2] : [])
    ...(resourceExists.storageAccount2001 ? [] : [sa4AIsearch])
    ...(resourceExists.storageAccount1001 ? [] : [sacc])
  ]
}

// cog-prj003-sdc-dev-3pmpb-001
module csAzureOpenAI '../modules/csOpenAI.bicep' = if(!resourceExists.openai && serviceSettingDeployAzureOpenAI) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AzureOpenAI4${deploymentProjSpecificUniqueSuffix}'
  params: {
    cognitiveName:aoaiName
    tags: projecttags
    laWorkspaceName:laWorkspaceName
    restore:restore
    location: location
    vnetResourceGroupName: vnetResourceGroupName
    commonResourceGroupName: commonResourceGroup
    sku: csOpenAISKU
    vnetName: vnetNameFull
    subnetName: genaiSubnetName
    keyvaultName: var_kv1_name //resourceExists.keyvault? keyvaultName: kv1.outputs.keyvaultName
    modelGPT4Version:modelGPT4Version
    aiSearchPrincipalId: var_search_pricipalId
    kind: kindAOpenAI
    pendCogSerName: 'p-${projectName}-openai-${genaiName}'
    publicNetworkAccess: enablePublicGenAIAccess
    disableLocalAuth:disableLocalAuth
    vnetRules: [
      subnet_genai_ref.id
      subnet_aks_ref.id
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
  }
  dependsOn: [
    projectResourceGroup
    ...(resourceExists.keyvault ? [] : [kv1])
    ...(useCommonACR ? [acrCommon2] : [])
    ...(resourceExists.storageAccount2001 ? [] : [sa4AIsearch])
    ...(resourceExists.storageAccount1001 ? [] : [sacc])
    //...((!resourceExists.aiSearch && enableAISearch) ? [aiSearchService] : [])
  ]
}

module privateDnsAzureOpenAI '../modules/privateDns.bicep' = if(!resourceExists.openai && serviceSettingDeployAzureOpenAI && !centralDnsZoneByPolicyInHub){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privDnsZoneLAOAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csAzureOpenAI.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

// LogAnalytics
resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laWorkspaceName
  scope:commonResourceGroupRef
}

var sharedPrivateLinkResources = []

module aiSearchService '../modules/aiSearch.bicep' = if (!resourceExists.aiSearch && enableAISearch) {
  name: 'AzureAISearch4${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    aiSearchName:safeNameAISearch
    location:location
    replicaCount: 1
    partitionCount: 1
    privateEndpointName: 'p-${projectName}-aisearch-${genaiName}'
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    tags: projecttags
    semanticSearchTier: semanticSearchTier
    publicNetworkAccess: enablePublicGenAIAccess
    skuName: aiSearchSKUName
    enableSharedPrivateLink:aiSearchEnableSharedPrivateLink
    sharedPrivateLinks: []
    ipRules: empty(processedIpRulesAISearch)?[]:processedIpRulesAISearch
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
  }
  dependsOn: [
    projectResourceGroup
    ...(resourceExists.keyvault ? [] : [kv1])
    ...(useCommonACR ? [acrCommon2] : [])
    ...(resourceExists.storageAccount2001 ? [] : [sa4AIsearch])
    ...(resourceExists.storageAccount1001 ? [] : [sacc])
  ]
}

module privateDnsAiSearchService '../modules/privateDns.bicep' = if(!resourceExists.aiSearch && centralDnsZoneByPolicyInHub==false && enableAISearch==true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDZoneSA1${genaiName}${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: aiSearchService.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

// Azure AI Search - END

// Storage for Azure AI Search

module sa4AIsearch '../modules/storageAccount.bicep' = if(!resourceExists.storageAccount2001 && enableAISearch){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'GenAISAAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount2001Name //replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}2${prjResourceSuffixNoDash}${env}','-','')
    skuName: 'Standard_LRS'
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    location: location
    enablePublicGenAIAccess:enablePublicGenAIAccess
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}'
    filePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-file-${genaiName}'
    queuePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-queue-${genaiName}'
    tablePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-table-${genaiName}'
    tags: projecttags
    ipRules: empty(processedIpRulesSa)?[]:processedIpRulesSa
    containers: [
      {
        name: 'default'
      }
    ]
    files: [
      {
        name: 'default'
      }
    ]
    vnetRules: [
      subnet_genai_ref.id
      subnet_aks_ref.id
    ]
    corsRules: [
      {
        allowedOrigins: [
          'https://mlworkspace.azure.ai'
          'https://ml.azure.com'
          'https://*.ml.azure.com'
          'https://ai.azure.com'
          'https://*.ai.azure.com'
          'https://mlworkspacecanary.azure.ai'
          'https://mlworkspace.azureml-test.net'
          'https://42.${location}.instances.azureml.ms'
          'https://457c18fd-a6d7-4461-999a-be092e9d1ec0.workspace.${location}.api.azureml.ms'
          'https://*.instances.azureml.ms'
          'https://*.azureml.ms'
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
        maxAgeInSeconds: 2520
        exposedHeaders: [
          '*'
        ]
        allowedHeaders: [
          '*'
        ]
      }
    ]
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsStorageGenAI '../modules/privateDns.bicep' = if(!resourceExists.storageAccount2001 && centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDZoneSA2${genaiName}${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: sa4AIsearch.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

// Storage for Azure AI Search - END

// ------------------------------ Azure ML dependency- Keyvault, VM, Azure container registry, Loganalytics, AppInsights ------------------------------//

// Related to Azure Machine Learning: Cointainer Registry, Storage Account, KeyVault, LogAnalytics, ApplicationInsights

module acr '../modules/containerRegistry.bicep' = if (!resourceExists.acrProject && useCommonACR == false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLGenaIContReg4${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: acrProjectName
    skuName: 'Premium'
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}${locationSuffix}-containerreg-to-vnt-mlcmn'
    tags: projecttags
    location:location
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
  }
  dependsOn: [
    projectResourceGroup
  ]
}
resource acrCommon 'Microsoft.ContainerRegistry/registries@2021-09-01' existing = if (useCommonACR == true) {
  name: acrCommonName
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// Update simulation - since: "ACR sku cannot be retrieved because of internal error."
// pend-acr-cmnsdc-containerreg-to-vnt-mlcmn
module acrCommon2 '../modules/containerRegistry.bicep' = if (useCommonACR == true){
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'AMLGenaIContReg4${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: acrCommonName
    skuName: 'Premium'
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: common_subnet_name_local // snet-esml-cmn-001
    privateEndpointName: 'pend-acr-cmn${locationSuffix}-containerreg-to-vnt-mlcmn' // snet-esml-cmn-001
    tags: acrCommon.tags
    location:acrCommon.location
    enablePublicAccessWithPerimeter:acrCommon.properties.publicNetworkAccess == 'Enabled' ? true : enablePublicAccessWithPerimeter
  }

  dependsOn: [
    acrCommon
  ]
}

module sacc '../modules/storageAccount.bicep' = if(!resourceExists.storageAccount1001) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLGenAIStorageAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName:storageAccount1001Name //replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}1${prjResourceSuffixNoDash}${env}','-','')
    skuName: 'Standard_LRS'
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    location: location
    enablePublicGenAIAccess:enablePublicGenAIAccess
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}ml'
    filePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-file-${genaiName}ml'
    queuePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-queue-${genaiName}ml'
    tablePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-table-${genaiName}ml'
    tags: projecttags
    containers: [
      {
        name: 'default'
      }
    ]
    files: [
      {
        name: 'default'
      }
    ]
    vnetRules: [ // Require  ServiceEndpoints for Microsoft.Storage on the subnets
      subnet_genai_ref.id 
      subnet_aks_ref.id
    ]
    ipRules: empty(processedIpRulesSa)? []: processedIpRulesSa
    corsRules: [
      {
        allowedOrigins: [
          'https://mlworkspace.azure.ai'
          'https://ml.azure.com'
          'https://*.ml.azure.com'
          'https://ai.azure.com'
          'https://*.ai.azure.com'
          'https://mlworkspacecanary.azure.ai'
          'https://mlworkspace.azureml-test.net'
          'https://42.${location}.instances.azureml.ms'
          'https://457c18fd-a6d7-4461-999a-be092e9d1ec0.workspace.${location}.api.azureml.ms'
          'https://*.instances.azureml.ms'
          'https://*.azureml.ms'
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
        maxAgeInSeconds: 2520
        exposedHeaders: [
          '*'
        ]
        allowedHeaders: [
          '*'
        ]
      }
    ]
  }

  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsStorage '../modules/privateDns.bicep' = if(!resourceExists.storageAccount1001 && centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDZoneSA3${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: sacc.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

module kv1 '../modules/keyVault.bicep' = if(!resourceExists.keyvault) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMGenAILKeyV4${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyvaultName: keyvaultName
    location: location
    tags: projecttags
    enablePurgeProtection:keyvaultEnablePurgeProtection
    soft_delete_days: keyvaultSoftDeleteDays
    tenantIdentity: tenantId
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-kv1-to-vnt-mlcmn'
    keyvaultNetworkPolicySubnets: [
      subnet_genai_ref.id 
      subnet_aks_ref.id
    ]
    accessPolicies: [] 
    ipRules: empty(processedIpRulesKv)?[]:processedIpRulesKv
  }
  dependsOn: [
    projectResourceGroup
    subnet_genai_ref
    subnet_aks_ref
  ]
}

module privateDnsKeyVault '../modules/privateDns.bicep' = if(!resourceExists.keyvault && centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDnZoneKV${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: kv1.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}
module applicationInsightSWC '../modules/applicationInsightsRGmode.bicep' = { //= if(!resourceExists.applicationInsight){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AppInsightsSWC4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: applicationInsightName
    logWorkspaceName: laWorkspaceName
    logWorkspaceNameRG: commonResourceGroup
    tags: projecttags
    location: location
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module vmPrivate '../modules/virtualMachinePrivate.bicep' = if(!resourceExists.vm && serviceSettingDeployProjectVM == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privVM4${deploymentProjSpecificUniqueSuffix}'
  params: {
    adminUsername: adminUsername
    adminPassword: adminPassword
    hybridBenefit: hybridBenefit
    vmSize: vmSKU[vmSKUSelectedArrayIndex]
    location: location
    vmName: vmName
    subnetName: defaultSubnet
    vnetId: vnetId
    tags: projecttags
    keyvaultName: var_kv1_name
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// ------------------------------ SERVICES (GenaI) - Azure OpenAI, AI Search, CosmosDB, WebApp ------------------------------//


// ------------------------------ END - SERVICES (GenaI) - Azure OpenAI, AI Search, CosmosDB, WebApp ------------------------------//



// Seeding Keyvault - Copy secrets to project keyvault
resource externalKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription,inputKeyvaultResourcegroup)
}

module addSecret '../modules/kvSecretsPrj.bicep' = if(!resourceExists.keyvault) {
  name: '${keyvaultName}S2P${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    spAppIDValue:externalKv.getSecret(projectServicePrincipleAppID_SeedingKeyvaultName) //projectServicePrincipleAppID_SeedingKeyvaultName 
    spOIDValue: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)  // projectServicePrincipleOID_SeedingKeyvaultName
    spSecretValue: externalKv.getSecret(projectServicePrincipleSecret_SeedingKeyvaultName)
    keyvaultName: var_kv1_name
    keyvaultNameRG: projectResourceGroup.name
  }
  dependsOn: [
    projectResourceGroup
    kv1
  ]
}

// Access Policies and fetching secrets to project keyvault
var secretGetListSet = {
  secrets: [ 
    'get'
    'list'
    'set'
  ]
}
var secretGetList = {
  secrets: [ 
    'get'
    'list'
  ]
}
var secretGet = {
  secrets: [ 
    'get'
  ]
}

// PROJECT Keyvault where technicalContactId GET,LIST, SET

module kvPrjAccessPolicyTechnicalContactAll '../modules/kvCmnAccessPolicys.bicep' = if(!resourceExists.keyvault) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: '${keyvaultName}AP${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGetListSet
    keyVaultResourceName: var_kv1_name
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds:var_all_principals
  }
  dependsOn: [
    addSecret
    kv1
  ]
}

// COMMON Keyvault where technicalContactId GET,LIST
var kvNameCommon = kvNameFromCOMMON_param != '' ? kvNameFromCOMMON_param : 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
resource commonKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: kvNameCommon
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
}

module kvCommonAccessPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: '${kvNameCommon}GL${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGetList
    keyVaultResourceName: kvNameCommon
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds:p011_genai_team_lead_array
  }
  dependsOn: [
    commonKv
  ]
}

module spCommonKeyvaultPolicyGetList '../modules/kvCmnAccessPolicys.bicep'= {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'spGetList${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGet
    keyVaultResourceName: commonKv.name
    policyName: 'add'
    principalId: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    additionalPrincipalIds:[]
  }
  dependsOn: [
    commonKv
  ]
}

// Configure Private DNS Zones, if standalone AIFactory. (othwerwise the HUB DNS Zones will be used, and via policy auomatically create A-records in HUB DNS Zones)


module privateDnsContainerRegistry '../modules/privateDns.bicep' = if(!resourceExists.acrProject && !centralDnsZoneByPolicyInHub && !useCommonACR){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDnsZACR${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: acr.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

module bing '../modules/bing.bicep' = if(!resourceExists.bing && serviceSettingDeployBingSearch==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'BingSearch4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: bingName
    location: 'global'
    sku: bingSearchSKU
    tags: projecttags
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// DATABASES - START
// 'https://457c18fd-a6d7-4461-999a-be092e9d1ec0.workspace.${location}.api.azureml.ms'
module cosmosdb '../modules/databases/cosmosdb/cosmosdb.bicep' = if(!resourceExists.cosmosDB && serviceSettingDeployCosmosDB==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'CosmosDB4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: cosmosDBName
    location: location
    enablePublicGenAIAccess:enablePublicGenAIAccess
    ipRules:(empty(ipWhitelist_array) || !enablePublicGenAIAccess || enablePublicAccessWithPerimeter)? []:ipWhitelist_array
    totalThroughputLimit:cosmosTotalThroughputLimit
    subnetNamePend: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
    createPrivateEndpoint: enablePublicAccessWithPerimeter?false:true
    keyvaultName: var_kv1_name
    vNetRules: [
      subnet_genai_ref.id
      subnet_aks_ref.id
    ]
    kind: cosmosKind
    minimalTlsVersion:cosmosMinimalTlsVersion
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
    projectResourceGroup
    ...(resourceExists.keyvault ? [] : [kv1])
  ]
}

module cosmosdbRbac '../modules/databases/cosmosdb/cosmosRbac.bicep' = if(!resourceExists.cosmosDB && serviceSettingDeployCosmosDB==true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'cosmosRbac${deploymentProjSpecificUniqueSuffix}'
  params: {
    cosmosName: cosmosdb.outputs.name
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    cosmosdb
    spAndMI2Array
  ]
}

module privateDnsCosmos '../modules/privateDns.bicep' = if(!resourceExists.cosmosDB && !centralDnsZoneByPolicyInHub && serviceSettingDeployCosmosDB && !enablePublicAccessWithPerimeter){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkCosmos${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: cosmosdb.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

module postgreSQL '../modules/databases/postgreSQL/pgFlexibleServer.bicep' = if(!resourceExists.postgreSQL && serviceSettingDeployPostgreSQL){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'PostgreSQL4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: postgreSQLName
    location: location
    tags: projecttags
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    keyvaultName: var_kv1_name
    createPrivateEndpoint: enablePublicAccessWithPerimeter?false:true
    sku: postgreSQLSKU
    storage: postgreSQLStorage
    version: postgreSQLVersion
    tenantId: tenantId
    useAdGroups: useAdGroups
    highAvailability: postgreSQLHighAvailability
    availabilityZone:postgresAvailabilityZone
  }
  dependsOn: [
    projectResourceGroup
    ...(resourceExists.keyvault ? [] : [kv1])
  ]
}

module postgreSQLRbac '../modules/databases/postgreSQL/pgFlexibleServerRbac.bicep' = if(!resourceExists.postgreSQL && serviceSettingDeployPostgreSQL){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'PostgreSQLRbac4${deploymentProjSpecificUniqueSuffix}'
  params: {
    postgreSqlServerName: postgreSQL.outputs.name
    useAdGroups: useAdGroups
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    postgreSQL
    spAndMI2Array
    ...((!resourceExists.postgreSQL && serviceSettingDeployPostgreSQL) ? [postgreSQL] : [])
  ]
}

module privateDnsPostGreSQL '../modules/privateDns.bicep' = if(!resourceExists.postgreSQL && !centralDnsZoneByPolicyInHub && serviceSettingDeployPostgreSQL && !enablePublicAccessWithPerimeter){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkPostgreSQL${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: postgreSQL.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
    ...((!resourceExists.postgreSQL && serviceSettingDeployPostgreSQL) ? [postgreSQL] : [])
  ]
}

// REDIS

module redisCache '../modules/databases/redis/redis.bicep' = if(!resourceExists.redis && serviceSettingDeployRedisCache) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'RedisCache4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: redisName
    location: location
    tags: projecttags
    skuName: redisSKU
    subnetNamePend: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    keyvaultName: var_kv1_name
    createPrivateEndpoint: enablePublicAccessWithPerimeter?false:true
  }
  dependsOn: [
    projectResourceGroup
    ...(resourceExists.keyvault ? [] : [kv1])
  ]
}

module redisCacheRbac '../modules/databases/redis/redisRbac.bicep' = if(!resourceExists.redis && serviceSettingDeployRedisCache) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'RedisCacheRbac4${deploymentProjSpecificUniqueSuffix}'
  params: {
    redisName: redisCache.outputs.name
    useAdGroups: useAdGroups
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    redisCache
    spAndMI2Array
  ]
}

module privateDnsRedisCache '../modules/privateDns.bicep' = if(!resourceExists.redis && !centralDnsZoneByPolicyInHub && serviceSettingDeployRedisCache && !enablePublicAccessWithPerimeter){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkRedisCache${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: redisCache.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

// SQL DATABASE

module sqlServer '../modules/databases/sqldatabase/sqldatabase.bicep' = if(!resourceExists.sqlServer && serviceSettingDeploySQLDatabase) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'SqlServer4${deploymentProjSpecificUniqueSuffix}'
  params: {
    serverName: sqlServerName
    databaseName: sqlDBName
    location: location
    tags: projecttags
    skuObject: empty(sqlServerSKUObject_DTU)?{}:sqlServerSKUObject_DTU
    subnetNamePend: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    keyvaultName: var_kv1_name
    createPrivateEndpoint: enablePublicAccessWithPerimeter?false:true
  }
  dependsOn: [
    projectResourceGroup
    ...(resourceExists.keyvault ? [] : [kv1])
  ]
}

module sqlRbac '../modules/databases/sqldatabase/sqldatabaseRbac.bicep' = if(!resourceExists.sqlServer && serviceSettingDeploySQLDatabase) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'SqlServerRbac4${deploymentProjSpecificUniqueSuffix}'
  params: {
    sqlServerName: sqlServer.outputs.serverName
    useAdGroups: useAdGroups
    usersOrAdGroupArray: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray

  }
  dependsOn: [
    sqlServer
    spAndMI2Array
  ]
}

module privateDnsSql '../modules/privateDns.bicep' = if(!resourceExists.sqlDB && !centralDnsZoneByPolicyInHub && serviceSettingDeploySQLDatabase && !enablePublicAccessWithPerimeter){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkSqlServer${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: sqlServer.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

// DATABASES - END

module appinsights '../modules/appinsights.bicep' = if(!resourceExists.applicationInsight && serviceSettingDeployAppInsightsDashboard) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AppInsights4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'appinsights-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
    location: location
    tags: projecttags
    logAnalyticsWorkspaceId: logAnalyticsWorkspaceOpInsight.id
    dashboardName: dashboardInsightsName
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// It is critical that the identity is granted ACR pull access before the app is created
// otherwise the container app will throw a provision error
// This also forces us to use an user assigned managed identity since there would no way to 
// provide the system assigned identity with the ACR pull access before the app is created

module miForAca '../modules/mi.bicep' = if(!resourceExists.miACA){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'miForAca4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: miACAName
    location: location
    tags: projecttags
  }
  dependsOn: [
    projectResourceGroup
  ]
}
module miRbac '../modules/miRbac.bicep'  = if(!resourceExists.miACA && useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'miRbacCmn-${deployment().name}-${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: acrCommon2.outputs.containerRegistryName
    principalId: var_miAca_PrincipalId
  }
  dependsOn: [
    projectResourceGroup
    miForAca
    ...(useCommonACR ? [acrCommon2] : [])
  ]
}
module miRbacProj '../modules/miRbac.bicep'  = if(!resourceExists.miACA && !useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'miRbacProj-${deployment().name}-${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: acr.outputs.containerRegistryName
    principalId: var_miAca_PrincipalId
  }
  dependsOn: [
    projectResourceGroup
    miForAca
    ...(!useCommonACR ? [acr] : [])
  ]
}

module privateDnscontainerAppsEnv '../modules/privateDns.bicep' = if(!resourceExists.containerAppsEnv && !centralDnsZoneByPolicyInHub && serviceSettingDeployContainerApps && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkACAEnv${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: containerAppsEnv.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}
  // In your main deployment file
module subnetDelegationServerFarm '../modules/subnetDelegation.bicep' = if((!resourceExists.functionApp && !resourceExists.webApp) &&(serviceSettingDeployWebApp || serviceSettingDeployFunction)) {
  name: 'subnetDelegationServerFarm1${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(vnetResourceGroupName)
  params: {
    vnetName: vnetNameFull
    subnetName: aksSubnetName // TODO: Have a dedicated for WebApp and FunctionApp
    location: location
    vnetResourceGroupName: vnetResourceGroupName
    delegations: [
      {
        name: 'webapp-delegation'
        properties: {
          serviceName: 'Microsoft.Web/serverFarms'
        }
      }
    ]
  }
  
}

module subnetDelegationAca '../modules/subnetDelegation.bicep' = if (!resourceExists.containerAppsEnv && serviceSettingDeployContainerApps) {
  name: 'subnetDelegationAcaEnv${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(vnetResourceGroupName)
  params: {
    vnetName: vnetNameFull
    subnetName: acaSubnetName
    location: location
    vnetResourceGroupName: vnetResourceGroupName
    delegations: [
      {
        name: 'aca-delegation'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }

}


// AZURE WEBAPP
module webapp '../modules/webapp.bicep' = if(!resourceExists.webApp && serviceSettingDeployWebApp) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'WebApp4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: webAppName
    location: location
    tags: projecttags
    sku: webappSKU
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    subnetIntegrationName: aksSubnetName // at least /28 use 25 similar as AKS subnet
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    applicationInsightsName: var_app_insight_aca
    logAnalyticsWorkspaceName: laWorkspaceName
    logAnalyticsWorkspaceRG: commonResourceGroup
    runtime: webAppRuntime  // Set to 'python' for Python apps
    redundancyMode: appRedundancyMode
    byoACEv3: byoACEv3
    byoAceFullResourceId: byoAceFullResourceId
    byoAceAppServicePlanRID: byoAceAppServicePlanResourceId
    runtimeVersion: webAppRuntimeVersion // Specify the Python version
    ipRules: ipWhitelist_array
    appSettings: [
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: var_openAIEndpoint
      }
      {
        name: 'AZURE_AISERVICES_ENDPOINT'
        value: var_aiServicesOpenAIEndpoint
      }
      {
        name: 'AZURE_SEARCH_ENDPOINT'
        value: var_aisearch_endpoint
      }
      {
        name: 'WEBSITE_VNET_ROUTE_ALL'
        value: '1'
      }
    ]
  }
  dependsOn: [
    projectResourceGroup
    sacc
    ...((!resourceExists.webApp ||!resourceExists.functionApp) ? [subnetDelegationServerFarm] : [])
    ...((!resourceExists.aiHub && enableAIFoundryHub) ? [aiHub] : [])
    ...((!resourceExists.aiServices && enableAIServices) ? [aiServices] : [])
    ...((!resourceExists.aiSearch && enableAISearch) ? [aiSearchService] : [])
    ...((!resourceExists.openai && serviceSettingDeployAzureOpenAI) ? [csAzureOpenAI] : [])
  ]
}

module privateDnsWebapp '../modules/privateDns.bicep' = if(!resourceExists.webApp && !centralDnsZoneByPolicyInHub && serviceSettingDeployWebApp && !enablePublicAccessWithPerimeter){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkWebApp${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: webapp.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones

  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

// Add RBAC for WebApp MSI to access other resources
module rbacForWebAppMSI '../modules/webappRbac.bicep' = if(!resourceExists.webApp && serviceSettingDeployWebApp) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacForWebApp${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: var_storageAccountName
    storageAccountName2:var_storageAccountName2
    aiSearchName: var_aiSearchName
    webAppPrincipalId:resourceExists.webApp? webappREF.identity.principalId: webapp.outputs.principalId//var_webAppPrincipalId
    openAIName: var_openAIName
    aiServicesName:var_aiServicesName
  }
  dependsOn: [
    webapp
    sacc
    sa4AIsearch
  ]
}
// AZURE WEBAPP END

// AZURE FUNCTION
module function '../modules/function.bicep' = if(!resourceExists.functionApp && serviceSettingDeployFunction) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'Function4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: functionAppName
    location: location
    tags: projecttags
    sku: functionSKU
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    subnetIntegrationName: aksSubnetName // at least /28 use 25 similar as AKS subnet
    storageAccountName: var_storageAccountName
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    applicationInsightsName: var_app_insight_aca
    logAnalyticsWorkspaceName: laWorkspaceName
    logAnalyticsWorkspaceRG: commonResourceGroup
    redundancyMode: appRedundancyMode
    byoACEv3: byoACEv3
    byoAceFullResourceId: byoAceFullResourceId
    byoAceAppServicePlanRID: byoAceAppServicePlanResourceId
    ipRules:ipWhitelist_array
    appSettings: [
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: var_openAIEndpoint
      }
      {
        name: 'AZURE_AISERVICES_ENDPOINT'
        value: var_aiServicesOpenAIEndpoint
      }
      {
        name: 'AZURE_SEARCH_ENDPOINT'
        value: var_aisearch_endpoint
      }
    ]
    runtime: functionRuntime // Choose based on your needs: 'node', 'dotnet', 'java', 'python'
    runtimeVersion: functionVersion // Supported versions: 3.8, 3.9, 3.10, 3.11, 3.12 (if available)
  }
  dependsOn: [
    projectResourceGroup
    sacc
    ...((!resourceExists.webApp ||!resourceExists.functionApp) ? [subnetDelegationServerFarm] : [])
    ...((!resourceExists.aiHub && enableAIFoundryHub) ? [aiHub] : [])
    ...((!resourceExists.aiServices && enableAIServices) ? [aiServices] : [])
    ...((!resourceExists.aiSearch && enableAISearch) ? [aiSearchService] : [])
    ...((!resourceExists.openai && serviceSettingDeployAzureOpenAI) ? [csAzureOpenAI] : [])
  ]
}

// Add DNS zone configuration for the Azure Function private endpoint
module privateDnsFunction '../modules/privateDns.bicep' = if(!resourceExists.functionApp && !centralDnsZoneByPolicyInHub && serviceSettingDeployFunction && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkFunction${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: function.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

// Add RBAC for Function App MSI to access other resources
module rbacForFunctionMSI '../modules/functionRbac.bicep' = if(!resourceExists.functionApp && serviceSettingDeployFunction) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacForFunction${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: var_storageAccountName
    storageAccountName2: var_storageAccountName2
    aiSearchName: var_aiSearchName
    functionPrincipalId: var_functionPrincipalId
    openAIName: var_openAIName
    aiServicesName: var_aiServicesName
  }
  dependsOn: [
    function
  ]
}
// AZURE FUNCTION END

// Create IP security restrictions array with VNet CIDR first, then dynamically add whitelist IPs
var ipSecurityRestrictions =[for ip in ipWhitelist_array: {
    name: replace(replace(ip, ',', ''), '/', '_')  // Replace commas with nothing and slashes with underscores
    ipAddressRange: ip
    action: 'Allow'
  }]
  
var vnetAllow = [
  {
    name: 'AllowVNet'
    ipAddressRange: vnetCidr // VNet CIDR from your existing variable
    action: 'Allow'
  }
]

var unionIpSec = union(ipSecurityRestrictions,vnetAllow)

var allowedOrigins = [
  'https://portal.azure.com'
  'https://ms.portal.azure.com'
  'https://mlworkspace.azure.ai'
  'https://ml.azure.com'
  'https://ai.azure.com'
  'https://mlworkspacecanary.azure.ai'
  'https://mlworkspace.azureml-test.net'
  'https://42.${location}.instances.azureml.ms'
  'https://457c18fd-a6d7-4461-999a-be092e9d1ec0.workspace.${location}.api.azureml.ms'
]

//'https://*.instances.azureml.ms'
//'https://*.azureml.ms'
//'https://*.ai.azure.com'
//'https://*.ml.azure.com'
    
module containerAppsEnv '../modules/containerapps.bicep' = if(!resourceExists.containerAppsEnv && serviceSettingDeployContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'aca-env-${deploymentProjSpecificUniqueSuffix}-depl'
  params: {
    name: containerAppsEnvName
    location: location
    tags: projecttags
    logAnalyticsWorkspaceName: laWorkspaceName
    logAnalyticsWorkspaceRG: commonResourceGroup
    applicationInsightsName: var_app_insight_aca
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    subnetAcaDedicatedName: acaSubnetName // at least /23
    wlMinCountServerless:wlMinCountServerless
    wlMinCountDedicated: wlMinCountDedicated
    wlMaxCount: wlMaxCount
    wlProfileDedicatedName: wlProfileDedicatedName
    wlProfileGPUConsumptionName: wlProfileGPUConsumptionName
  }
  dependsOn: [
    projectResourceGroup
    ...(resourceExists.miACA ? [] : [miForAca])
    ...(useCommonACR && !resourceExists.miACA ? [miRbac] : []) // It is critical that the identity is granted ACR pull access before the app is created
    subnetDelegationAca
  ] 
}

module acaApi '../modules/containerappApi.bicep' = if(!resourceExists.containerAppA && serviceSettingDeployContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'aca-a-${deploymentProjSpecificUniqueSuffix}-depl'
  params: {
    name:containerAppAName
    location: location
    tags: projecttags
    ipSecurityRestrictions: enablePublicGenAIAccess? ipSecurityRestrictions: []
    allowedOrigins: allowedOrigins
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    subnetAcaDedicatedName: acaSubnetName
    customDomains:acaCustomDomainsArray
    resourceGroupName: targetResourceGroup
    identityId: var_miAca_PrincipalId
    identityName: miACAName
    containerRegistryName: var_acr_cmn_or_prj
    containerAppsEnvironmentName: var_aca_env_name
    containerAppsEnvironmentId:var_aca_env_id
    openAiDeploymentName: 'gpt'
    openAiEvalDeploymentName:'gpt-evals'
    openAiEmbeddingDeploymentName: 'text-embedding-ada-002'
    openAiEndpoint: var_aiservices_openai_endpoint
    openAiName: var_aiServicesName
    openAiType: 'azure'
    openAiApiVersion: openAiApiVersion
    aiSearchEndpoint: var_aisearch_endpoint
    aiSearchIndexName: 'index-${projectName}-${resourceSuffix}'
    appinsightsConnectionstring: var_appinsights_connectionstring
    bingName: var_bingName
    bingApiEndpoint: var_bing_endpoint
    bingApiKey: var_bing_api_Key
    aiProjectName: var_aiProjectName
    subscriptionId: subscriptionIdDevTestProd
    appWorkloadProfileName: acaAppWorkloadProfileName
    containerCpuCoreCount: containerCpuCoreCount // 0.5, 1.0, 2.0, 4.0, 8.0
    containerMemory: containerMemory // 0.5Gi, 1.0Gi, 2.0Gi, 4.0Gi, 8.0Gi
    keyVaultUrl: var_kv1_uri
    imageName: !empty(aca_a_registry_image) ? aca_a_registry_image: aca_default_image
    imageRegistryType: !empty(aca_a_registry_image)? imageRegistryTypeA: 'ms' // 'ms' 'dockerhub', 'private'
  }
  dependsOn: [
    cmnRbacACR
    ...(resourceExists.containerAppsEnv ? [] : [containerAppsEnv])
    ...(resourceExists.containerAppsEnv ? [] : [subnetDelegationAca])
    ...(resourceExists.miACA ? [] : [miForAca])
    ...(resourceExists.bing ? [] : [bing])
    ...(resourceExists.aiHub ? [] : [aiHub])
    ...(resourceExists.aiServices ? [] : [aiServices])
    ...(resourceExists.keyvault ? [] : [kv1])
    ...(useCommonACR? [cmnRbacACR] : [])
    ...(!useCommonACR? [acr] : [])
    
  ] 
}
module acaWebApp '../modules/containerappWeb.bicep' = if(!resourceExists.containerAppW && serviceSettingDeployContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name:'aca-w-${deploymentProjSpecificUniqueSuffix}-depl' 
  params: {
    location: location
    tags: projecttags
    name: containerAppWName
    apiEndpoint: acaApi.outputs.SERVICE_ACA_URI // TODO: MayTheForceBeWithYou - as var and REF.
    allowedOrigins: allowedOrigins
    containerAppsEnvironmentName: var_aca_env_name
    containerAppsEnvironmentId: var_aca_env_id
    containerRegistryName: var_acr_cmn_or_prj
    identityId: var_miAca_PrincipalId
    identityName: miACAName
    appWorkloadProfileName:acaAppWorkloadProfileName
    containerCpuCoreCount: containerCpuCoreCount // 0.5, 1.0, 2.0, 4.0, 8.0
    containerMemory: containerMemory // 0.5Gi, 1.0Gi, 2.0Gi, 4.0Gi, 8.0Gi
    keyVaultUrl: var_kv1_uri
    imageName: !empty(aca_w_registry_image) ? aca_w_registry_image: aca_default_image
    imageRegistryType: !empty(aca_w_registry_image)? imageRegistryTypeW: 'ms' // 'ms' 'dockerhub', 'private'
  }
  dependsOn: [
    cmnRbacACR
    ...(resourceExists.containerAppsEnv ? [] : [containerAppsEnv])
    ...(resourceExists.containerAppsEnv ? [] : [subnetDelegationAca])
    ...(resourceExists.containerAppA ? [] : [acaApi])
    ...(resourceExists.miACA ? [] : [miForAca])
    ...(resourceExists.keyvault ? [] : [kv1])
  ]
}

module rbacForContainerAppsMI '../modules/containerappRbac.bicep' = if (!resourceExists.miACA && serviceSettingDeployContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacForContainerAppsMI${deploymentProjSpecificUniqueSuffix}'
  params:{
    aiSearchName: var_aiSearchName
    appInsightsName: var_app_insight_aca
    principalIdMI: var_miAca_PrincipalId
    resourceGroupId: projectResourceGroup.outputs.rgId
  }
  dependsOn: [
    projectResourceGroup
    ...(!resourceExists.containerAppsEnv && serviceSettingDeployContainerApps? [containerAppsEnv] : [])
    ...(!resourceExists.containerAppA && serviceSettingDeployContainerApps ? [acaApi] : [])
    ...(!resourceExists.aiSearch && enableAISearch? [aiSearchService] : [])
    ...(!resourceExists.applicationInsight && serviceSettingDeployAppInsightsDashboard ? [appinsights] : [])
    ...(resourceExists.miACA ? [] : [miForAca])
  ]
}

// 
// ------------------------------ SERVICES (Azure Machine Learning)  ------------------------------//

// AKS: NB! Standard_D12 is not allowed in WE for agentpool   [standard_a4_v2]
param aks_dev_defaults array = [
  'Standard_B4ms' // 4 cores, 16GB, 32GB storage: Burstable (2022-11 this was the default in Azure portal)
  'Standard_A4m_v2' // 4cores, 32GB, 40GB storage (quota:100)
  'Standard_D3_v2' // 4 cores, 14GB RAM, 200GB storage
] 

param aks_testProd_defaults array = [
  'Standard_DS13-2_v2' // 8 cores, 14GB, 112GB storage
  'Standard_A8m_v2' // 8 cores, 64GB RAM, 80GB storage (quota:100)
]

param aml_dev_defaults array = [
  'Standard_DS3_v2' // 	4 cores, 14GB ram, 28GB storage = 0.27$ [Classical ML model training on small datasets]
  'Standard_F8s_v2' //  (8,16,64) 0.39$
  'Standard_DS12_v2' // 4 cores, 28GB RAM, 56GB storage = 0.38 [Data manipulation and training on medium-sized datasets (1-10GB)
]

param aml_testProd_defaults array = [
  'Standard_D13_v2' // 	(8 cores, 56GB, 400GB storage) = 0.76$ [Data manipulation and training on large datasets (>10 GB)]
  'Standard_D4_v2' // (8 cores, 28GB RAM, 400GB storage) = 0.54$
  'Standard_F16s_v2' //  (16 cores, 32GB RAM, 128GB storage) = 0.78$
]

param ci_dev_defaults array = [
  'Standard_DS11_v2' // 2 cores, 14GB RAM, 28GB storage
]
param ci_devTest_defaults array = [
  'Standard_D11_v2'
]

// AML AKS Cluster: defaults & overrides
var aks_dev_sku_param = aks_dev_sku_override != '' ? aks_dev_sku_override : aks_dev_defaults[0]
var aks_test_prod_sku_param = aks_test_prod_sku_override != '' ? aks_test_prod_sku_override : aks_testProd_defaults[0]

var aks_version_param = aks_version_override != '' ? aks_version_override :'1.30.3' //2024-09-05 did not work in SDC: '1.27.9' // 2024-03-14 LTS Earlier: (1.27.3 | 2024-01-25 to 2024-03-14) az aks get-versions --location westeurope --output table). Supported >='1.23.5'
var aks_dev_nodes_param = aks_dev_nodes_override != -1 ? aks_dev_nodes_override : 1
var aks_test_prod_nodes_param = aks_test_prod_nodes_override != -1 ? aks_test_prod_nodes_override : 3

// AML Compute Instance: defaults & overrides
var aml_ci_dev_sku_param = aml_ci_dev_sku_override != '' ? aml_ci_dev_sku_override : ci_dev_defaults[0]
var aml_ci_test_prod_sku_param = aml_ci_test_prod_sku_override != '' ? aml_ci_test_prod_sku_override : ci_devTest_defaults[0]

// AML cluster: defaults & overrides
var aml_cluster_dev_sku_param = aml_cluster_dev_sku_override != '' ? aml_cluster_dev_sku_override : aml_dev_defaults[0]
var aml_cluster_test_prod_sku_param = aml_cluster_test_prod_sku_override != '' ? aml_cluster_test_prod_sku_override : aml_testProd_defaults[1]
var aml_cluster_dev_nodes_param = aml_cluster_dev_nodes_override != -1 ? aml_cluster_dev_nodes_override : 3
var aml_cluster_test_prod_nodes_param = aml_cluster_test_prod_nodes_override != -1 ? aml_cluster_test_prod_nodes_override : 3

var processedIpRulesAzureML = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

// ERROR: "snt-prj003-aks cannot be used as it's a delegated subnet"
// TODO: add another dedicated subnet - not borrowing the AKS subnet
module amlv2 '../modules/machineLearningv2.bicep'= if(!resourceExists.aml && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AzureMLDepl_${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: amlName
    uniqueDepl: deploymentProjSpecificUniqueSuffix
    uniqueSalt5char: uniqueInAIFenv
    projectName:projectName
    projectNumber:projectNumber
    location: location
    locationSuffix:locationSuffix
    aifactorySuffix: aifactorySuffixRG
    skuName: 'basic'
    skuTier: 'basic'
    env:env
    aksSubnetId: aksSubnetId
    aksSubnetName:aksSubnetName
    aksDnsServiceIP:aksDnsServiceIP
    aksServiceCidr: aksServiceCidr
    tags: projecttags
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-aml-to-vnt-mlcmn'
    amlPrivateDnsZoneID: privateLinksDnsZones.amlworkspace.id
    notebookPrivateDnsZoneID:privateLinksDnsZones.notebooks.id
    allowPublicAccessWhenBehindVnet:(AMLStudioUIPrivate == true && empty(ipWhitelist_remove_ending_32))? false:true
    enablePublicAccessWithPerimeter: AMLStudioUIPrivate == false ? true: false
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
    aksVmSku_dev: aks_dev_sku_param
    aksVmSku_testProd: aks_test_prod_sku_param
    aksNodes_dev:aks_dev_nodes_param
    aksNodes_testProd:aks_test_prod_nodes_param
    kubernetesVersionAndOrchestrator:aks_version_param
    amlComputeDefaultVmSize_dev: aml_cluster_dev_sku_param
    amlComputeDefaultVmSize_testProd: aml_cluster_test_prod_sku_param
    amlComputeMaxNodex_dev: aml_cluster_dev_nodes_param
    amlComputeMaxNodex_testProd: aml_cluster_test_prod_nodes_param
    ciVmSku_dev: aml_ci_dev_sku_param
    ciVmSku_testProd: aml_ci_test_prod_sku_param
    ipRules: empty(processedIpRulesAzureML) ? [] : processedIpRulesAzureML
    ipWhitelist_array:empty(ipWhitelist_remove_ending_32)?[]:ipWhitelist_remove_ending_32
    saName:var_storageAccountName2
    kvName:var_kv1_name
    acrName: var_acr_cmn_or_prj
    acrRGName: useCommonACR? commonResourceGroup: targetResourceGroup
    appInsightsName:applicationInsightSWC.outputs.name
  }
  dependsOn: [
    projectResourceGroup
    ...(resourceExists.storageAccount2001 ? [] : [sa4AIsearch])
    ...(resourceExists.keyvault? [] : [kv1])
    ...(!resourceExists.acrProject && !useCommonACR? [acr] : [])
  ]
}

module rbacAmlv2 '../modules/rbacStorageAml.bicep' = if(!resourceExists.aml && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacUsersAmlVersion2${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: var_storageAccountName2
    userObjectIds: p011_genai_team_lead_array
    azureMLworkspaceName:var_aml_name
    servicePrincipleAndMIArray:spAndMiArray
    useAdGroups:useAdGroups
    user2Storage:true
  }
  dependsOn: [
    projectResourceGroup
    amlv2
    //...(!resourceExists.aml && enableAML? [amlv2] : [])
  ]
}

module aiFoundry '../modules/csFoundry/csAIFoundryBasic.bicep' = if(!resourceExists.aif && serviceSettingEnableAIFoundryPreview) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AIFoundryPrevview4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aifName
    projectName: aifPrjName
    enablePublicAccessWithPerimeter:true
    //location: location
  }
}

var aiHubNameShort ='ai-hub-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
//var storageAccountId1 = !resourceExists.storageAccount1001 ? sacc.outputs.storageAccountId : resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Storage/storageAccounts', storageAccount1001Name)

module aiHub '../modules/machineLearningAIHub.bicep' = if(!resourceExists.aiHub && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: '${aiHubNameShort}${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aiHubName
    defaultProjectName: aifProjectName
    location: location
    tags: projecttags
    aifactorySuffix: aifactorySuffixRG
    applicationInsightsName: resourceExists.applicationInsight? applicationInsightName: applicationInsightSWC.outputs.name
    acrName: var_acr_cmn_or_prj
    acrRGName: useCommonACR? commonResourceGroup: targetResourceGroup
    env: env
    keyVaultName: var_kv1_name
    privateEndpointName:'p-aihub-${projectName}${locationSuffix}${env}${genaiName}amlworkspace'
    aifactoryProjectNumber: projectNumber
    storageAccountName: var_storageAccountName
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    enablePublicAccessWithPerimeter:enablePublicAccessWithPerimeter
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    enablePublicGenAIAccess:enablePublicGenAIAccess
    aiSearchName:var_aiSearchName
    privateLinksDnsZones: privateLinksDnsZones
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    kindAIHub:'Hub'
    aiServicesName:var_aiServicesName
    logWorkspaceName:logAnalyticsWorkspaceOpInsight.name
    logWorkspaceResoureGroupName:commonResourceGroup
    locationSuffix:locationSuffix
    resourceSuffix:resourceSuffix
    aifactorySalt: uniqueInAIFenv
    ipRules: empty(processedIpRulesAIHub) ? [] : processedIpRulesAIHub
    //value:ip // Invalid","target":"workspaceDto","message":"IP allowlist contains one or more invalid IP address masks, or exceeds maximum of 200 entries.
    // ValidationError: workspaceDto: Can't enable network monitor in region: francecentral
    ipWhitelist_array: empty(ipWhitelist_remove_ending_32)?[]:ipWhitelist_remove_ending_32
  }
  dependsOn: [
    projectResourceGroup
    ...(!resourceExists.aiSearch && enableAISearch ? [aiSearchService] : [])
    ...(!resourceExists.aiServices && enableAIServices ? [aiServices] : [])
    ...(resourceExists.storageAccount1001 ? [] : [sacc])
    ...(resourceExists.keyvault? [] : [kv1])
    ...(resourceExists.acrProject && !useCommonACR? [] : [acr])
    ...(resourceExists.applicationInsight? [] : [applicationInsightSWC])
    //applicationInsightSWC
    subnet_genai_ref
    subnet_aks_ref
  ]
}

module rbacAcrProjectspecific '../modules/acrRbac.bicep' = if(useCommonACR == false) {
  scope:resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacAcrProject${deploymentProjSpecificUniqueSuffix}'
  params: {
    acrName: resourceExists.acrProject? acrProjectName:acr.outputs.containerRegistryName
    aiHubName: resourceExists.aiHub? aiHubName:aiHub.outputs.name
    aiHubRgName: targetResourceGroup
  }
}

module rbackSPfromDBX2AMLSWC '../modules/machinelearningRBAC.bicep' = if(!resourceExists.aml && enableAzureMachineLearning)  {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDBX2AMLGenAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlName:amlName
    servicePrincipleAndMIArray: spAndMiArray
    adfSP:resourceExists.miPrj? miPrjREF.properties.principalId: miForPrj.outputs.managedIdentityPrincipalId
    projectADuser:technicalContactId
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    ...(resourceExists.keyvault? [] : [kv1])
    ...(!resourceExists.aml && enableAzureMachineLearning? [amlv2] : [])
    logAnalyticsWorkspaceOpInsight // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    spAndMI2Array
  ]
}

// ------------------------------ END - SERVICES (Azure Machine Learning)  ------------------------------//

// Bastion in AIFactory COMMON RG, but with a custom name
module rbacKeyvaultCommon4Users '../modules/kvRbacReaderOnCommon.bicep'= if(empty(bastionResourceGroup) && addBastionHost){
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbac1GenAIReadUsersCmnKV${deploymentProjSpecificUniqueSuffix}'
  params: {
    common_kv_name:'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    user_object_ids: p011_genai_team_lead_array   
    bastion_service_name: empty(bastionName) ? 'bastion-${locationSuffix}-${env}${commonResourceSuffix}' : bastionName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    ...(resourceExists.keyvault? [] : [kv1])
    rbacReadUsersToCmnVnetBastion
  ]
}
// Bastion Externally (Connectvivity subscription and RG)
module rbacExternalBastion '../modules/rbacBastionExternal.bicep' = if(!empty(bastionResourceGroup) && !empty(bastionSubscription)) {
  scope: resourceGroup(bastionSubscription,bastionResourceGroup)
  name: 'rbac2GenAIUsersBastionExt${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    bastion_service_name: empty(bastionName) ? 'bastion-${locationSuffix}-${env}${commonResourceSuffix}' : bastionName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    ...(resourceExists.keyvault? [] : [kv1])
    rbacReadUsersToCmnVnetBastion
  ]
}

// ------------------- RBAC for AI Studio (AIServices) service pricipal, to services ---------------//
// -- DOCS: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/use-your-data-securely#create-shared-private-link --//

module rbacForOpenAI '../modules/aihubRbacOpenAI.bicep' = if (serviceSettingDeployAzureOpenAI && !resourceExists.openai) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbac3OpenAI${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: var_storageAccountName
    storageAccountName2:var_storageAccountName2
    aiSearchName: var_aiSearchName
    openAIServicePrincipal:var_openai_pricipalId
    servicePrincipleAndMIArray: spAndMiArray
    openAIName:var_openAIName
    userObjectIds:p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    ...(!resourceExists.aiSearch && enableAISearch? [aiSearchService] : [])
    ...(!resourceExists.openai && serviceSettingDeployAzureOpenAI? [csAzureOpenAI] : [])
    ...(resourceExists.storageAccount1001? [] : [sacc])
    ...(resourceExists.storageAccount2001? [] : [sa4AIsearch])
    ...(resourceExists.keyvault? [] : [kv1])
    rbacReadUsersToCmnVnetBastion
    spAndMI2Array // NB!
  ]
}
// 6 assignments: OK
module rbacModuleAIServices '../modules/aihubRbacAIServices.bicep' = if(!resourceExists.aiServices && enableAIServices) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbac4AIServices${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: var_storageAccountName
    storageAccountName2:var_storageAccountName2
    aiSearchName: var_aiSearchName
    aiServicesPrincipalId:var_aiServices_principalId
  }
  dependsOn: [
    ...(!resourceExists.aiServices && enableAIServices? [aiServices] : [])
    ...(!resourceExists.aiSearch && enableAISearch? [aiSearchService] : [])
    ...(resourceExists.storageAccount1001? [] : [sacc])
    ...(resourceExists.storageAccount2001? [] : [sa4AIsearch])
  ]
}

// 5 assignments: OK
module rbacModuleAISearch '../modules/aihubRbacAISearch.bicep' = if(!resourceExists.aiSearch && enableAISearch) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbac5Search${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName:var_storageAccountName
    storageAccountName2:var_storageAccountName2
    aiServicesName:var_aiServicesName
    aiSearchMIObjectId:var_search_pricipalId
  }
  dependsOn: [
    ...(!resourceExists.aiServices && enableAIServices? [aiServices] : [])
    ...(!resourceExists.aiSearch && enableAISearch? [aiSearchService] : [])
  ]
}

module rbacAihubRbacAmlRG '../modules/aihubRbacAmlRG.bicep'= if (!resourceExists.aiHub && !empty(azureMachineLearningObjectId) && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbac6Aml2RG${deploymentProjSpecificUniqueSuffix}'
  params:{
    azureMachineLearningObjectId: azureMachineLearningObjectId
    aiHubName: aiHubName
    aiHubPrincipalId: (!resourceExists.aiHub && enableAIFoundryHub)? aiHub.outputs.principalId: aiHubREF.identity.principalId
  }
  dependsOn: [
    aiHub
  ]
}

module rbacModuleUsers '../modules/aihubRbacUsers.bicep' = if (!resourceExists.aiHub && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbac7UsersAIHub${deploymentProjSpecificUniqueSuffix}'
  params:{
    aiServicesName:var_aiServicesName
    storageAccountName: var_storageAccountName
    storageAccountName2:var_storageAccountName2
    resourceGroupId: projectResourceGroup.outputs.rgId
    userObjectIds: p011_genai_team_lead_array
    aiHubName:aiHubName
    aiHubProjectName:var_aiProjectName
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups:useAdGroups
    disableContributorAccessForUsers:disableContributorAccessForUsers
  }
  dependsOn: [
    ...(!resourceExists.aiHub && enableAIFoundryHub? [aiHub] : [])
    ...(!resourceExists.aiServices && enableAIServices? [aiServices] : [])
    ...(!resourceExists.openai && serviceSettingDeployAzureOpenAI? [csAzureOpenAI] : [])
    ...(resourceExists.storageAccount1001? [] : [sacc])
    ...(resourceExists.storageAccount2001? [] : [sa4AIsearch])
    ...(resourceExists.keyvault? [] : [kv1])
    spAndMI2Array // NB!
  ]
}
module rbacModuleUsersToSearch '../modules/aiSearchRbacUsers.bicep' = if (!resourceExists.aiSearch && enableAISearch) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbac7Users2AISearch${deploymentProjSpecificUniqueSuffix}'
  params:{
    aiSearchName: var_aiSearchName
    userObjectIds: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups:useAdGroups
  }
  dependsOn: [
    ...(!resourceExists.aiSearch && enableAISearch? [aiSearchService] : [])
    ...(resourceExists.keyvault? [] : [kv1])
    spAndMI2Array // NB!
  ]
}

// #### OPTIONAL ####

module rbacVision '../modules/aihubRbacVision.bicep' = if(serviceSettingDeployAzureAIVision==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbac8Vision${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: var_storageAccountName
    storageAccountName2:var_storageAccountName2
    aiVisionMIObjectId: csVision.outputs.principalId
    userObjectIds: p011_genai_team_lead_array
    visonServiceName: csVision.outputs.name
    useAdGroups:useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    ...(resourceExists.storageAccount1001? [] : [sacc])
    ...(resourceExists.storageAccount2001? [] : [sa4AIsearch])
    ...(resourceExists.keyvault? [] : [kv1])
    spAndMI2Array // NB!
  ]
}

module rbacSpeech '../modules/aihubRbacSpeech.bicep' = if(serviceSettingDeployAzureSpeech==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbac9Speech${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: var_storageAccountName
    storageAccountName2:var_storageAccountName2
    aiSpeechMIObjectId: csSpeech.outputs.principalId
    userObjectIds: p011_genai_team_lead_array
    speechServiceName: csSpeech.outputs.name
    useAdGroups:useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    ...(resourceExists.storageAccount1001? [] : [sacc])
    ...(resourceExists.storageAccount2001? [] : [sa4AIsearch])
    ...(resourceExists.keyvault? [] : [kv1])
    spAndMI2Array // NB!
  ]
}
module rbacDocs '../modules/aihubRbacDoc.bicep' = if(serviceSettingDeployAIDocIntelligence==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbac10Docs${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: var_storageAccountName
    storageAccountName2:var_storageAccountName2
    userObjectIds: p011_genai_team_lead_array
    aiDocsIntelMIObjectId: csDocIntelligence.outputs.principalId
    docsServiceName: csDocIntelligence.outputs.name
    useAdGroups:useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    ...(resourceExists.storageAccount1001? [] : [sacc])
    ...(resourceExists.storageAccount2001? [] : [sa4AIsearch])
    ...(resourceExists.keyvault? [] : [kv1])
    spAndMI2Array // NB!
  ]
}

// RBAC - Read users to Bastion, IF Bastion is added in ESML-COMMON resource group. If Bastion is in HUB, an admin need to do this manually
module rbacReadUsersToCmnVnetBastion '../modules/vnetRBACReader.bicep' = if(addBastionHost && empty(bastionSubscription)) {
  scope: resourceGroup(subscriptionIdDevTestProd,vnetResourceGroupName)
  name: 'rbac12GenAIRUsersVnet${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    vNetName: vnetNameFull
    common_bastion_subnet_name: 'AzureBastionSubnet'
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups:useAdGroups

  }
  dependsOn: [
    rbacModuleUsers
    spAndMI2Array // NB!
  ]
}
// Bastion vNet Externally (Connectvivity subscription and RG || AI Factory Common RG)
module rbacReadUsersToCmnVnetBastionExt '../modules/vnetRBACReader.bicep' = if(addBastionHost && !empty(bastionSubscription)) {
  scope: resourceGroup(bastionSubscription,bastionResourceGroup)
  name: 'rbac13UsersVnet${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    vNetName: vnetNameFullBastion
    common_bastion_subnet_name: 'AzureBastionSubnet'
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups:useAdGroups
  }
  dependsOn: [
    rbacModuleUsers
    spAndMI2Array // NB!
  ]
}

// RBAC on ACR Push/Pull for users in Common Resource group

module cmnRbacACR '../modules/commonRGRbac.bicep' = if(useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbac14UsersToCmnACR${deploymentProjSpecificUniqueSuffix}'
  params: {
    commonRGId: resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', commonResourceGroup)
    servicePrincipleAndMIArray: spAndMiArray
    userObjectIds: p011_genai_team_lead_array
    useAdGroups:useAdGroups
  }
  dependsOn: [
    rbacModuleUsers
    spAndMI2Array // NB!
  ]
}

var datalakeName = datalakeName_param != '' ? datalakeName_param : '${commonLakeNamePrefixMax8chars}${uniqueInAIFenv}esml${replace(commonResourceSuffix,'-','')}${env}'
resource esmlCommonLake 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: datalakeName
  scope:resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
 
}

module rbacLakeFirstTime '../esml-common/modules-common/lakeRBAC.bicep' = if(!resourceExists.aiHub && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacLake4PrjFoundry${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlPrincipalId: ''//(!resourceExists.aml && enableAML)? amlv2.outputs.principalId: (enableAML)? amlREF.identity.principalId:''
    aiHubPrincipleId: (!resourceExists.aiHub && enableAIFoundryHub)? aiHub.outputs.principalId: aiHubREF.identity.principalId
    projectTeamGroupOrUser: p011_genai_team_lead_array
    adfPrincipalId: ''
    datalakeName: datalakeName
    useAdGroups:useAdGroups
  }
  dependsOn: [
    //cmnRbacACR
    esmlCommonLake
    ...(!resourceExists.aiHub && enableAIFoundryHub? [aiHub] : [])
    ...(!resourceExists.aml && enableAzureMachineLearning? [amlv2] : [])
  ]
}
module rbacLakeAml '../esml-common/modules-common/lakeRBAC.bicep' = if(!resourceExists.aml && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacLake4Amlv2${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlPrincipalId: var_aml_principal_id
    aiHubPrincipleId: ''//(!resourceExists.aiHub && enableAIFoundryHub)? aiHub.outputs.principalId: aiHubREF.identity.principalId
    projectTeamGroupOrUser: [] // p011_genai_team_lead_array
    adfPrincipalId: ''
    datalakeName: datalakeName
    useAdGroups:useAdGroups
  }
  dependsOn: [
    esmlCommonLake
    ...(!resourceExists.aml && enableAzureMachineLearning? [amlv2] : [])
  ]
}

output debug_vnetId string = vnetId
output debug_common_subnet_name_local string = common_subnet_name_local
output debug_genaiSubnetId string = genaiSubnetId
output debug_genaiSubnetName string = genaiSubnetName
output debug_defaultSubnet string = defaultSubnet
output debug_aksSubnetId string = aksSubnetId
output debug_aksSubnetName string = aksSubnetName
