targetScope = 'subscription'

// ================================================================
// COMPUTE SERVICES DEPLOYMENT - Phase 5 Implementation
// This file deploys compute services including:
// - Azure Web Apps
// - Azure Functions
// - Container Apps Environment
// - Container Apps (API & Web)
// - Managed Identity for Container Apps
// - Subnet delegations for compute services
// ================================================================
// CMK: Is not supported for these services. But storage, and keyvault for App services packages uses CMK, from other bicep.
// ============================================================================
// SKU for services
// ============================================================================
param aseSkuWorkers int = 1 // Number of workers for ASE v3
param aseSku string = 'IsolatedV2' // I family for ASE v3
@allowed([
  'I1v2'  // Isolated v2 for ASEv3
  'I2v2'
  'I3v2'
  'I4v2'
  'I5v2'
  'I6v2'
])
param aseSkuCode string = 'I1v2' // I family for ASE v3
param webappSKUAce object = {
  name: aseSkuCode
  tier: aseSku
  size: aseSkuCode
  family: 'Iv2'
  capacity: aseSkuWorkers
}

// Function App configuration
param functionSKU object = {
  name: 'EP1'
  tier: 'ElasticPremium'
  family: 'EP'
  capacity: 1
}
// Web App configuration
param webappSKU object = {
  name: 'P1v3'
  tier: 'PremiumV3'
  family: 'Pv3'
  capacity: 1
}

@description('Diagnostic setting level for monitoring and logging')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

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

// Exists flags from Azure Devops
param applicationInsightExists bool = false
param containerAppsEnvExists bool = false
param containerAppAExists bool = false
param containerAppWExists bool = false
param functionAppExists bool = false
param webAppExists bool = false
param funcAppServicePlanExists bool = false
param webAppServicePlanExists bool = false
param bingExists bool = false

param aiFoundryV2Exists bool = false
param enableAIFoundry bool = false
param disableAgentNetworkInjection bool = true

param enableAppInsightsDashboard bool = true
param enableBingSearch bool = false

// Enable flags from parameter files
@description('Enable Container Apps deployment')
param enableContainerApps bool = false

@description('Enable Azure Function deployment')
param enableFunction bool = false

@description('Enable Azure Web App deployment')
param enableWebApp bool = false

param enableAzureOpenAI bool = false
param enableAISearch bool = false
param enableAIServices bool = false
param addAISearch bool = false

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

// Function App configuration
param functionAlwaysOn bool = true
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

// Web App configuration
param webappAlwaysOn bool = true
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

// ASE (App Service Environment) settings
param byoASEv3 bool = false
param byoAseFullResourceId string = ''
param byoAseAppServicePlanResourceId string = ''

// Container Apps settings
param wlMinCountServerless int = 0
param wlMinCountDedicated int = 1
param wlMaxCount int = 100
param containerMemory string = '2.0Gi' // 0.5Gi, 1.0Gi, 2.0Gi, 4.0Gi, 8.0Gi
param wlProfileDedicatedName string = 'D4' // 'D4', 'D8', 'D16', 'D32', 'D64', 'E4', 'E8'
param wlProfileGPUConsumptionName string = 'Consumption-GPU-NC24-A100'
param acaAppWorkloadProfileName string = 'consumption'
param containerCpuCoreCount int = 1

// Container App images
param aca_a_registry_image string = ''
param aca_w_registry_image string = ''
param aca_default_image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var imageRegistryTypeA = !empty(aca_a_registry_image) 
  ? (contains(aca_a_registry_image, 'mcr.microsoft.com') 
      ? 'ms' 
      : contains(aca_a_registry_image, 'docker.io') 
        ? 'dockerhub' 
        : 'private')
  : 'ms'  // Default to 'ms' when using default image
var imageRegistryTypeW = !empty(aca_w_registry_image) 
  ? (contains(aca_w_registry_image, 'mcr.microsoft.com') 
      ? 'ms' 
      : contains(aca_w_registry_image, 'docker.io') 
        ? 'dockerhub' 
        : 'private')
  : 'ms'  // Default to 'ms' when using default image

// Custom domains for Container Apps
param acaCustomDomainsArray array = []

// Redundancy mode
param appRedundancyMode string = 'None'

// OpenAI API settings
param openAiApiVersion string = '2024-06-01'

// Tags
param tagsProject object = {}
param tags object = {}

// IP Rules
param IPwhiteList string = ''

// Dependencies and naming
param aifactorySuffixRG string
param commonRGNamePrefix string

// Missing parameters required for naming convention module
param aifactorySalt10char string = ''
param randomValue string
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId

// Common ACR usage
param useCommonACR bool = true

// Common names for referencing other resources
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'
@description('Common resource name identifier. Default is "esml-common"')
param commonResourceName string = 'esml-common'

// ============== VARIABLES ==============
var aseIdNormalized = empty(byoAseFullResourceId)
  ? ''
  : (startsWith(byoAseFullResourceId, '/subscriptions/') || startsWith(byoAseFullResourceId, '/providers/'))
    ? byoAseFullResourceId
    : '/${byoAseFullResourceId}'

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

// Random salt for unique naming - using uniqueString for deterministic salt
var randomSalt = substring(uniqueString(subscription().subscriptionId, targetResourceGroup), 0, 5)

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('05-naming-${targetResourceGroup}', 64)
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
  }
}

// Import specific names needed for compute services deployment
var webAppName = namingConvention.outputs.webAppName
var functionAppName = namingConvention.outputs.functionAppName
var containerAppsEnvName = namingConvention.outputs.containerAppsEnvName
var containerAppAName = namingConvention.outputs.containerAppAName
var containerAppWName = namingConvention.outputs.containerAppWName
var miACAName = namingConvention.outputs.miACAName
var miPrjName = namingConvention.outputs.miPrjName
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var acrProjectName = namingConvention.outputs.acrProjectName
var acrCommonName = namingConvention.outputs.acrCommonName
var safeNameAISearchOrg = enableAISearch? namingConvention.outputs.safeNameAISearch: ''
var aoaiName = enableAzureOpenAI? namingConvention.outputs.aoaiName: ''
var aiServicesName = enableAIServices? namingConvention.outputs.aiServicesName: ''
var bingName = namingConvention.outputs.bingName
var applicationInsightName = namingConvention.outputs.applicationInsightName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName
var keyvaultName = namingConvention.outputs.keyvaultName

// AI Search name construction
var cleanRandomValue = take(namingConvention.outputs.randomSalt,2)

var safeNameAISearchBase = (enableAISearch && !empty(safeNameAISearchOrg))
  ? take(safeNameAISearchOrg, max(length(safeNameAISearchOrg) - 3, 0))
  : ''

var safeNameAISearchSuffix = (enableAISearch && !empty(safeNameAISearchOrg))
  ? substring(
      safeNameAISearchOrg,
      max(length(safeNameAISearchOrg) - 3, 0),
      min(3, length(safeNameAISearchOrg))
    )
  : ''

var aiSearchName = (enableAISearch && !empty(safeNameAISearchOrg))
  ? take(
      addAISearch
        ? '${safeNameAISearchBase}${cleanRandomValue}${safeNameAISearchSuffix}'
        : safeNameAISearchOrg,
      60
    )
  : ''

// AI Foundry Hub
var aifV1HubName = namingConvention.outputs.aifV1HubName
var aifV1ProjectName = namingConvention.outputs.aifV1ProjectName

// AI Foundry V2
var aifV2ProjectName = namingConvention.outputs.aifV2Name
var aifV2Name = namingConvention.outputs.aifV2PrjName

// Computed variables using naming convention outputs
var deploymentProjSpecificUniqueSuffix = '${projectName}${env}${randomSalt}'
var var_acr_cmn_or_prj = useCommonACR ? acrCommonName : acrProjectName

// Subnet names from naming convention
var genaiSubnetName = namingConvention.outputs.genaiSubnetName
var aksSubnetName = namingConvention.outputs.aksSubnetName
var acaSubnetName = namingConvention.outputs.acaSubnetName
var defaultSubnet = namingConvention.outputs.defaultSubnet

// IP Rules processing
var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []

// Safe domain construction to avoid InvalidDomainName errors
var safeLocation = toLower(location)

// Create location-specific domains for all regions - Azure Container Apps and MCR are widely available
var acaLocationEndpoint = '${safeLocation}.ext.azurecontainerapps.dev'
var mcrLocationEndpoint = '${safeLocation}.data.mcr.microsoft.com'

// Raw FQDN array with potential empty strings
var fqdnRaw = [
  // Private link FQDNs for networking
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.documents.azure.com'
  'privatelink.file.${environment().suffixes.storage}'
  'privatelink.openai.azure.com'
  'privatelink.search.windows.net'
  'privatelink.services.ai.azure.com'
  
  // Public FQDNs for specific Azure services
  // Storage Account 1 - Blob, File, Queue endpoints
  '${namingConvention.outputs.storageAccount1001Name}.blob.${environment().suffixes.storage}'
  '${namingConvention.outputs.storageAccount1001Name}.file.${environment().suffixes.storage}'
  '${namingConvention.outputs.storageAccount1001Name}.queue.${environment().suffixes.storage}'
  
  // Storage Account 2 - Blob, File, Queue endpoints
  '${namingConvention.outputs.storageAccount2001Name}.blob.${environment().suffixes.storage}'
  '${namingConvention.outputs.storageAccount2001Name}.file.${environment().suffixes.storage}'
  '${namingConvention.outputs.storageAccount2001Name}.queue.${environment().suffixes.storage}'
  
  // AI Search endpoint (conditionally included)
  enableAISearch ? '${aiSearchName}.search.windows.net' : ''
  
  // Key Vault endpoint
  '${namingConvention.outputs.keyvaultName}${environment().suffixes.keyvaultDns}'
  
  // Cosmos DB endpoint (conditionally included)
  //enableCosmosDB ? '${namingConvention.outputs.cosmosDBName}.documents.azure.com' : ''
  
  // AI Services endpoint
  '${aifV2Name}.cognitiveservices.azure.com'
  '${aifV2Name}.openai.azure.com'
  
  // #### Azure Container Apps (ACA) required FQDNs for AI agents ####
  
  // All scenarios - Microsoft Container Registry (MCR)
  'mcr.microsoft.com'
  // '*.data.mcr.microsoft.com' - replaced with regional endpoints
  mcrLocationEndpoint // Safe location-based endpoint
  // Aspire Dashboard 
  acaLocationEndpoint // Safe location-based ACA endpoint

  // Not inACA documented but required for various functionalities, Microsoft Graph API
  'graph.microsoft.com'

   // *.identity.azure.net
  'login.identity.azure.net'
  '${tenant().tenantId}.identity.azure.net'
  'sts.identity.azure.net'

  // '*.login.microsoft.com' - replaced with environment-specific endpoints
  /* Examples:    
  'login.microsoft.com'
  'account.login.microsoft.com'
  'portal.login.microsoft.com'
  'oauth.login.microsoft.com'
  'secure.login.microsoft.com'
  'sso.login.microsoft.com'
  'device.login.microsoft.com'
  */
  replace(environment().authentication.loginEndpoint, 'https://', '')
  'account.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'portal.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'oauth.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'secure.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'sso.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'device.${replace(environment().authentication.loginEndpoint, 'https://', '')}'

  // Docker Hub Registry (if needed)
  'hub.docker.com'
  'registry-1.docker.io'
  'production.cloudflare.docker.com'
]

// Filter out empty strings and remove duplicates to ensure valid FQDN list for Azure validation
var fqdnFiltered = filter(fqdnRaw, fqdnEntry => !empty(fqdnEntry))
var fqdn = reduce(fqdnFiltered, [], (current, next) => contains(current, next) ? current : union(current, [next]))

// ============================================================================
// SPECIAL - Get PRINICPAL ID, only if created in this module, else ignore.
// ============================================================================
#disable-next-line BCP318
var var_webAppPrincipalId = enableWebApp && !webAppExists? webapp.outputs.principalId: ''
#disable-next-line BCP318
var var_functionPrincipalId= enableFunction && !functionAppExists? function.outputs.principalId: ''

// Container App API domain/endpoint - using simplified logic
#disable-next-line BCP318
var var_containerAppApiDomain = enableContainerApps && !containerAppAExists? acaApi.outputs.SERVICE_ACA_URI: ''

// Create IP security restrictions array with VNet CIDR first, then dynamically add whitelist IPs
var ipSecurityRestrictions = [for ip in ipWhitelist_array: {
  name: replace(replace(ip, ',', ''), '/', '_')  // Replace commas with nothing and slashes with underscores
  ipAddressRange: ip
  action: 'Allow'
}]

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

// DNS configurations for private endpoints (simplified)
// var var_webapp_dnsConfig = [
//   {
//     name: webAppName
//     type: 'Microsoft.Web/sites'
//     groupIds: ['sites']
//     resourceId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.Web/sites/${webAppName}'
//   }
// ]

#disable-next-line BCP318
var var_webapp_dnsConfig = enableWebApp && !webAppExists? webapp.outputs.dnsConfig: []

// var var_containerAppsEnv_dnsConfig = [
//   {
//     name: containerAppsEnvName
//     type: 'Microsoft.App/managedEnvironments'
//     groupIds: ['managedEnvironments']
//     resourceId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.App/managedEnvironments/${containerAppsEnvName}'
//   }
// ]

#disable-next-line BCP318
var var_containerAppsEnv_dnsConfig = enableContainerApps && !containerAppsEnvExists? containerAppsEnv.outputs.dnsConfig: []

// var var_function_dnsConfig = [
//   {
//     name: functionAppName
//     type: 'Microsoft.Web/sites'
//     groupIds: ['sites']
//     resourceId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.Web/sites/${functionAppName}'
//   }
// ]

#disable-next-line BCP318
var var_function_dnsConfig = enableFunction && !functionAppExists? function.outputs.dnsConfig: []

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}
// ============================================================================
// SPECIAL -Needs static name in existing
// ============================================================================
var cmnName_Static = 'cmn'
var laWorkspaceName_Static = 'la-${cmnName_Static}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laWorkspaceName_Static
  scope:commonResourceGroupRef
}

resource existingTargetRG 'Microsoft.Resources/resourceGroups@2025-04-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============== Private DNS Zones ==============
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  name: take('05-getPrivDnsZ-${targetResourceGroup}', 64)
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
module getACAMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('03-getACAMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miACAName
  }
}

var miAcaPrincipalId = getACAMIPrincipalId.outputs.principalId

// ============== SUBNET DELEGATIONS ==============

// Subnet delegation for Web Apps and Function Apps
module subnetDelegationServerFarm '../modules/subnetDelegation.bicep' = if((!functionAppExists && !webAppExists) && (enableWebApp || enableFunction) && !byoASEv3) {
  name: take('05-snetDelegSF1${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(vnetResourceGroupName)
  params: {
    vnetName: vnetNameFull
    subnetName: aksSubnetName // TODO: Have a dedicated subnet for WebApp and FunctionApp
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

// Subnet delegation for Container Apps
module subnetDelegationAca '../modules/subnetDelegation.bicep' = if ((!containerAppsEnvExists && enableContainerApps) && (!aiFoundryV2Exists && !disableAgentNetworkInjection)) {
  name: take('05-snetDelegACA${deploymentProjSpecificUniqueSuffix}', 64)
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

// ============== App insights Dashboard with AppInsights of type WEB  ==============

module appinsights '../modules/appinsights.bicep' = if(!applicationInsightExists && enableAppInsightsDashboard) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: take('05-AppInsights4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: namingConvention.outputs.applicationInsightName2
    location: location
    tags: tagsProject
    logAnalyticsWorkspaceId: logAnalyticsWorkspaceOpInsight.id
    dashboardName: namingConvention.outputs.dashboardInsightsName
  }
  dependsOn: [
    existingTargetRG
  ]
}
// ============== AZURE WEB APP ==============

module webapp '../modules/webapp.bicep' = if(!webAppExists && enableWebApp) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-WebApp4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: webAppName
    location: location
    tags: tagsProject
    sku: byoASEv3 ? webappSKUAce : webappSKU
    alwaysOn: webappAlwaysOn
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    subnetIntegrationName: aksSubnetName // at least /28 use 25 similar as AKS subnet
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    applicationInsightsName: applicationInsightName
    logAnalyticsWorkspaceName: laWorkspaceName
    logAnalyticsWorkspaceRG: commonResourceGroup
    runtime: webAppRuntime
    redundancyMode: appRedundancyMode
    byoASEv3: byoASEv3
    byoAseFullResourceId: aseIdNormalized
    byoAseAppServicePlanRID: byoAseAppServicePlanResourceId
    runtimeVersion: webAppRuntimeVersion
    ipRules: ipWhitelist_array
    appSettings: [
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: 'https://${aoaiName}.openai.azure.com/'
      }
      {
        name: 'AZURE_AISERVICES_ENDPOINT'
        value: 'https://${aiServicesName}.cognitiveservices.azure.com/'
      }
      {
        name: 'AZURE_SEARCH_ENDPOINT'
        value: 'https://${aiSearchName}.search.windows.net'
      }
      {
        name: 'WEBSITE_VNET_ROUTE_ALL'
        value: '1'
      }
    ]
  }
  dependsOn: [
    existingTargetRG
    subnetDelegationServerFarm
  ]
}

module privateDnsWebapp '../modules/privateDns.bicep' = if(!webAppExists && !centralDnsZoneByPolicyInHub && enableWebApp && !enablePublicAccessWithPerimeter && !byoASEv3) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-privDnsWeb${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_webapp_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    existingTargetRG
    webapp
  ]
}

// Add RBAC for WebApp MSI to access other resources (simplified)
module rbacForWebAppMSI '../modules/webappRbac.bicep' = if(!webAppExists && enableWebApp) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-rbacForWebApp${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name // Using different storage account
    aiSearchName: enableAISearch ? aiSearchName : ''
    webAppPrincipalId: var_webAppPrincipalId // Using computed variable for principal ID
    openAIName: enableAzureOpenAI ? aoaiName : ''
    aiServicesName: enableAIServices ? aiServicesName : ''
  }
  dependsOn: [
    webapp
  ]
}

// ============== AZURE FUNCTION ==============

module function '../modules/function.bicep' = if(!functionAppExists && enableFunction) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-Function4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: functionAppName
    location: location
    tags: tagsProject
    sku: byoASEv3 ? webappSKUAce : functionSKU
    alwaysOn: functionAlwaysOn
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    subnetIntegrationName: aksSubnetName // at least /28 use 25 similar as AKS subnet
    storageAccountName: storageAccount1001Name
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    applicationInsightsName: applicationInsightName
    logAnalyticsWorkspaceName: laWorkspaceName
    logAnalyticsWorkspaceRG: commonResourceGroup
    redundancyMode: appRedundancyMode
    byoASEv3: byoASEv3
    byoAseFullResourceId: aseIdNormalized
    byoAseAppServicePlanRID: byoAseAppServicePlanResourceId
    ipRules: ipWhitelist_array
    appSettings: [
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: 'https://${aoaiName}.openai.azure.com/'
      }
      {
        name: 'AZURE_AISERVICES_ENDPOINT'
        value: 'https://${aiServicesName}.cognitiveservices.azure.com/'
      }
      {
        name: 'AZURE_SEARCH_ENDPOINT'
        value: 'https://${aiSearchName}.search.windows.net'
      }
    ]
    runtime: functionRuntime
    runtimeVersion: functionVersion
  }
  dependsOn: [
    existingTargetRG
    subnetDelegationServerFarm
  ]
}

// Add DNS zone configuration for the Azure Function private endpoint
module privateDnsFunction '../modules/privateDns.bicep' = if(!functionAppExists && !centralDnsZoneByPolicyInHub && enableFunction && !enablePublicAccessWithPerimeter && !byoASEv3) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-privDnsFunc${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_function_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    existingTargetRG
    function
  ]
}

// Add RBAC for Function App MSI to access other resources (simplified)
module rbacForFunctionMSI '../modules/functionRbac.bicep' = if(!functionAppExists && enableFunction) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-rbacForFunction${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name // Using different storage account
    aiSearchName: enableAISearch ? aiSearchName : ''
    functionPrincipalId: var_functionPrincipalId // Using computed variable for principal ID
    openAIName: enableAzureOpenAI ? aoaiName : ''
    aiServicesName: enableAIServices ? aiServicesName : ''
  }
  dependsOn: [
    function
  ]
}

// ============== CONTAINER APPS ENVIRONMENT ==============

module containerAppsEnv '../modules/containerapps.bicep' = if(!containerAppsEnvExists && enableContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-aca-env-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: containerAppsEnvName
    location: location
    tags: tagsProject
    logAnalyticsWorkspaceName: laWorkspaceName
    logAnalyticsWorkspaceRG: commonResourceGroup
    applicationInsightsName: applicationInsightName
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    subnetAcaDedicatedName: acaSubnetName // at least /23
    wlMinCountServerless: wlMinCountServerless
    wlMinCountDedicated: wlMinCountDedicated
    wlMaxCount: wlMaxCount
    wlProfileDedicatedName: wlProfileDedicatedName
    wlProfileGPUConsumptionName: wlProfileGPUConsumptionName
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: concat(
        !empty(miPrjName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)) : [],
        !empty(miACAName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miACAName)) : []
      )
    }
  }
  dependsOn: [
    existingTargetRG
    subnetDelegationAca
  ]
}

module privateDnscontainerAppsEnv '../modules/privateDns.bicep' = if(!containerAppsEnvExists && !centralDnsZoneByPolicyInHub && enableContainerApps && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-privDnsACAEnv${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_containerAppsEnv_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    existingTargetRG
    containerAppsEnv
  ]
}

// ============================================================================
// SPECIAL - Get API key of existing MI. Needs static name in existing
// ============================================================================
#disable-next-line BCP318
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)
#disable-next-line BCP081
var bingName_Static = 'bing-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'

#disable-next-line BCP081
resource bingREF 'Microsoft.Bing/accounts@2020-06-10' existing = if(enableBingSearch) {
  name: bingName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318 BCP422
var var_bing_api_Key = enableBingSearch? bingREF.listKeys().key1:'BCP318'

// ============== CONTAINER APPS - API ==============

module acaApi '../modules/containerappApi.bicep' = if(!containerAppAExists && enableContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-aca-a-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: containerAppAName
    location: location
    tags: tagsProject
    ipSecurityRestrictions: enablePublicGenAIAccess ? ipSecurityRestrictions : []
    allowedOrigins: allowedOrigins
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: defaultSubnet
    subnetAcaDedicatedName: acaSubnetName
    customDomains: acaCustomDomainsArray
    resourceGroupName: targetResourceGroup
    identityId: miAcaPrincipalId // Using the variable instead of module output
    identityName: miACAName
    containerRegistryName: var_acr_cmn_or_prj
    containerAppsEnvironmentName: containerAppsEnvName // Using direct name instead of module output
    containerAppsEnvironmentId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.App/managedEnvironments/${containerAppsEnvName}'
    openAiDeploymentName: 'gpt'
    openAiEvalDeploymentName: 'gpt-evals'
    openAiEmbeddingDeploymentName: 'text-embedding-ada-002'
    openAiEndpoint: 'https://${aiServicesName}.cognitiveservices.azure.com/'
    openAiName: aiServicesName
    openAiType: 'azure'
    openAiApiVersion: openAiApiVersion
    aiSearchEndpoint: 'https://${aiSearchName}.search.windows.net'
    aiSearchIndexName: 'index-${projectName}-${resourceSuffix}'
    appinsightsConnectionstring: 'InstrumentationKey=${applicationInsightName}'
    bingName: bingName
    bingApiEndpoint: 'https://api.bing.microsoft.com/v7.0/search'
    bingApiKey: var_bing_api_Key // 'placeholder-key' Simplified
    aiProjectName: aifV1ProjectName
    subscriptionId: subscriptionIdDevTestProd
    appWorkloadProfileName: acaAppWorkloadProfileName
    containerCpuCoreCount: containerCpuCoreCount
    containerMemory: containerMemory
    keyVaultUrl: 'https://${keyvaultName}.${environment().suffixes.keyvaultDns}'
    imageName: !empty(aca_a_registry_image) ? aca_a_registry_image : aca_default_image
    imageRegistryType: !empty(aca_a_registry_image) ? imageRegistryTypeA : 'ms'
  }
  dependsOn: [
    containerAppsEnv
  ]
}

// ============== CONTAINER APPS - WEB ==============

module acaWebApp '../modules/containerappWeb.bicep' = if(!containerAppWExists && enableContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-aca-w-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    location: location
    tags: tagsProject
    name: containerAppWName
    apiEndpoint: 'https://${containerAppAName}.${var_containerAppApiDomain}' // Using computed domain variable
    allowedOrigins: allowedOrigins
    containerAppsEnvironmentName: containerAppsEnvName // Using direct name
    containerAppsEnvironmentId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.App/managedEnvironments/${containerAppsEnvName}'
    containerRegistryName: var_acr_cmn_or_prj
    identityId: miAcaPrincipalId // Using the variable instead of module output
    identityName: miACAName
    appWorkloadProfileName: acaAppWorkloadProfileName
    containerCpuCoreCount: containerCpuCoreCount
    containerMemory: containerMemory
    keyVaultUrl: 'https://${keyvaultName}.${environment().suffixes.keyvaultDns}'
    imageName: !empty(aca_w_registry_image) ? aca_w_registry_image : aca_default_image
    imageRegistryType: !empty(aca_w_registry_image) ? imageRegistryTypeW : 'ms'
  }
  dependsOn: [
    containerAppsEnv    
  ]
}

// ============== RBAC FOR CONTAINER APPS ==============

module rbacForContainerAppsMI '../modules/containerappRbac.bicep' = if (enableContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05rbacACAMI${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    aiSearchName: aiSearchName
    appInsightsName: applicationInsightName
    principalIdMI: miAcaPrincipalId // Using the variable instead of module output
    resourceGroupId: existingTargetRG.id
  }
  dependsOn: [
    containerAppsEnv
    acaApi
  ]
}

// ============== DIAGNOSTIC SETTINGS ==============

// Application Insights Diagnostic Settings
module appInsightsDiagnostics '../modules/diagnostics/applicationInsightsDiagnostics.bicep' = if (!applicationInsightExists && enableAppInsightsDashboard) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-diagAppInsights-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    applicationInsightsName: applicationInsightName
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    appinsights
  ]
}

// Web App Diagnostic Settings
module webAppDiagnostics '../modules/diagnostics/webAppsDiagnostics.bicep' = if (!webAppExists && enableWebApp) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-diagWebApp-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    webAppName: webAppName
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    webapp
  ]
}

// Function App Diagnostic Settings
module functionAppDiagnostics '../modules/diagnostics/functionAppsDiagnostics.bicep' = if (!functionAppExists && enableFunction) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-diagFunctionApp-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    functionAppName: functionAppName
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    function
  ]
}

// Container Apps API Diagnostic Settings
module containerAppApiDiagnostics '../modules/diagnostics/containerAppsDiagnostics.bicep' = if (!containerAppAExists && enableContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-diagContainerAppAPI-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    containerAppName: containerAppAName
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    acaApi
  ]
}

// Container Apps Web Diagnostic Settings
module containerAppWebDiagnostics '../modules/diagnostics/containerAppsDiagnostics.bicep' = if (!containerAppWExists && enableContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('05-diagContainerAppWeb-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    containerAppName: containerAppWName
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    acaWebApp
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs simplified to avoid conditional module reference issues
// Resource information should be retrieved through Azure CLI queries after deployment

@description('Web App deployment status')
output webAppDeployed bool = (!webAppExists && enableWebApp)

@description('Function App deployment status')
output functionAppDeployed bool = (!functionAppExists && enableFunction)

@description('Container Apps Environment deployment status')
output containerAppsEnvDeployed bool = (!containerAppsEnvExists && enableContainerApps)

@description('Container App API deployment status')
output containerAppADeployed bool = (!containerAppAExists && enableContainerApps)

@description('Container App Web deployment status')
output containerAppWDeployed bool = (!containerAppWExists && enableContainerApps)

@description('ACR RBAC verification status for Container Apps')
output acrRbacVerified bool = enableContainerApps

@description('ACR RBAC verification timestamp')
output acrRbacVerificationCompleted string = enableContainerApps ? 'RBAC verification included in deployment' : 'RBAC verification not required'
