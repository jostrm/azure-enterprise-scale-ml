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
  size: 'EP1'
  family: 'EP'
  capacity: 1
}

// Web App configuration
param webappSKU object = {
  name: 'P1v3'
  tier: 'PremiumV3'
  size: 'P1v3'
  family: 'Pv3'
  capacity: 1
}

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
param miACAExists bool = false
param bingExists bool = false

param serviceSettingDeployAppInsightsDashboard bool = true
param serviceSettingDeployBingSearch bool = false

// Enable flags from parameter files
@description('Enable Container Apps deployment')
param serviceSettingDeployContainerApps bool = false

@description('Enable Azure Function deployment')
param serviceSettingDeployFunction bool = false

@description('Enable Azure Web App deployment')
param serviceSettingDeployWebApp bool = false

// Security and networking
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param centralDnsZoneByPolicyInHub bool = false

// PS-Calculated and set by .JSON, that Powershell dynamically created in networking part.
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''

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
param functionRuntime string = 'python'
param functionVersion string = '3.11'

// Web App configuration
param webappAlwaysOn bool = true
param webAppRuntime string = 'python'
param webAppRuntimeVersion string = '3.11'

// ASE (App Service Environment) settings
param byoASEv3 bool = false
param byoAseFullResourceId string = ''
param byoAseAppServicePlanResourceId string = ''

// Container Apps settings
param wlMinCountServerless int = 0
param wlMinCountDedicated int = 1
param wlMaxCount int = 100
param wlProfileDedicatedName string = 'Dedicated'
param wlProfileGPUConsumptionName string = 'gpu-consumption'
param acaAppWorkloadProfileName string = 'consumption'
param containerCpuCoreCount int = 1
param containerMemory string = '1.0Gi'

// Container App images
param aca_a_registry_image string = ''
param aca_w_registry_image string = ''
param aca_default_image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param imageRegistryTypeA string = 'ms'
param imageRegistryTypeW string = 'ms'

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
param randomValue string = ''
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId

// Common ACR usage
param useCommonACR bool = true

// Common names for referencing other resources
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'

// ============== VARIABLES ==============

// Calculated variables
var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
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
  name: 'naming-05-${targetResourceGroup}'
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
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
  }
}

// Import specific names needed for compute services deployment
var webAppName = namingConvention.outputs.webAppName
var functionAppName = namingConvention.outputs.functionAppName
var containerAppsEnvName = namingConvention.outputs.containerAppsEnvName
var containerAppAName = namingConvention.outputs.containerAppAName
var containerAppWName = namingConvention.outputs.containerAppWName
var miACAName = namingConvention.outputs.miACAName
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var acrProjectName = namingConvention.outputs.acrProjectName
var acrCommonName = namingConvention.outputs.acrCommonName
var aiSearchName = namingConvention.outputs.safeNameAISearch
var aoaiName = namingConvention.outputs.aoaiName
var aiServicesName = namingConvention.outputs.aiServicesName
var bingName = namingConvention.outputs.bingName
var aiProjectName = namingConvention.outputs.aiProjectName
var applicationInsightName = namingConvention.outputs.applicationInsightName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName
var keyvaultName = namingConvention.outputs.keyvaultName

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

// ============================================================================
// SPECIAL - Get PRINICPAL ID, only if created in this module, else ignore.
// ============================================================================
#disable-next-line BCP318
var var_webAppPrincipalId = serviceSettingDeployWebApp && !webAppExists? webapp.outputs.principalId: 'BCP318'
#disable-next-line BCP318
var var_functionPrincipalId= serviceSettingDeployFunction && !functionAppExists? function.outputs.principalId: 'BCP318'

// Container App API domain/endpoint - using simplified logic
#disable-next-line BCP318
var var_containerAppApiDomain = serviceSettingDeployContainerApps && !containerAppAExists? acaApi.outputs.SERVICE_ACA_URI: 'BCP318'

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
var var_webapp_dnsConfig = webapp.outputs.dnsConfig

// var var_containerAppsEnv_dnsConfig = [
//   {
//     name: containerAppsEnvName
//     type: 'Microsoft.App/managedEnvironments'
//     groupIds: ['managedEnvironments']
//     resourceId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.App/managedEnvironments/${containerAppsEnvName}'
//   }
// ]

#disable-next-line BCP318
var var_containerAppsEnv_dnsConfig = containerAppsEnv.outputs.dnsConfig

// var var_function_dnsConfig = [
//   {
//     name: functionAppName
//     type: 'Microsoft.Web/sites'
//     groupIds: ['sites']
//     resourceId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.Web/sites/${functionAppName}'
//   }
// ]

#disable-next-line BCP318
var var_function_dnsConfig = function.outputs.dnsConfig

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}
resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laWorkspaceName
  scope:commonResourceGroupRef
}

resource existingTargetRG 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============== Private DNS Zones ==============
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

// ============== MANAGED IDENTITY FOR CONTAINER APPS ==============

module miForAca '../modules/mi.bicep' = if(!miACAExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-miForAca4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: miACAName
    location: location
    tags: tagsProject
  }
  dependsOn: [
    existingTargetRG
  ]
}

// Assumes the principals exists.
module getACAMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: '05-getACAMI-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miACAName
  }
}

// Array vars - use principal IDs from helper modules
var miPrincipalId = getACAMIPrincipalId.outputs.principalId

module miRbac '../modules/miRbac.bicep' = if(!miACAExists && useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: '05-miRbacCmn-${deployment().name}-${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: acrCommonName
    principalId: miPrincipalId
  }
  dependsOn: [
    miForAca
  ]
}

module miRbacProj '../modules/miRbac.bicep' = if(!miACAExists && !useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-miRbacProj-${deployment().name}-${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: acrProjectName
    principalId: miPrincipalId
  }
  dependsOn: [
    miForAca
  ]
}

// ============== SUBNET DELEGATIONS ==============

// Subnet delegation for Web Apps and Function Apps
module subnetDelegationServerFarm '../modules/subnetDelegation.bicep' = if((!functionAppExists && !webAppExists) && (serviceSettingDeployWebApp || serviceSettingDeployFunction) && !byoASEv3) {
  name: '05-snetDelegSF1${deploymentProjSpecificUniqueSuffix}'
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
module subnetDelegationAca '../modules/subnetDelegation.bicep' = if (!containerAppsEnvExists && serviceSettingDeployContainerApps) {
  name: '05-snetDelegACA${deploymentProjSpecificUniqueSuffix}'
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

module appinsights '../modules/appinsights.bicep' = if(!applicationInsightExists && serviceSettingDeployAppInsightsDashboard) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: '05-AppInsights4${deploymentProjSpecificUniqueSuffix}'
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

module webapp '../modules/webapp.bicep' = if(!webAppExists && serviceSettingDeployWebApp) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-WebApp4${deploymentProjSpecificUniqueSuffix}'
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
    byoAseFullResourceId: byoAseFullResourceId
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

module privateDnsWebapp '../modules/privateDns.bicep' = if(!webAppExists && !centralDnsZoneByPolicyInHub && serviceSettingDeployWebApp && !enablePublicAccessWithPerimeter && !byoASEv3) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-privDnsWeb${deploymentProjSpecificUniqueSuffix}'
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
module rbacForWebAppMSI '../modules/webappRbac.bicep' = if(!webAppExists && serviceSettingDeployWebApp) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-rbacForWebApp${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount1001Name // Using same storage account
    aiSearchName: aiSearchName
    webAppPrincipalId: var_webAppPrincipalId // Using computed variable for principal ID
    openAIName: aoaiName
    aiServicesName: aiServicesName
  }
  dependsOn: [
    webapp
  ]
}

// ============== AZURE FUNCTION ==============

module function '../modules/function.bicep' = if(!functionAppExists && serviceSettingDeployFunction) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-Function4${deploymentProjSpecificUniqueSuffix}'
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
    byoAseFullResourceId: byoAseFullResourceId
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
module privateDnsFunction '../modules/privateDns.bicep' = if(!functionAppExists && !centralDnsZoneByPolicyInHub && serviceSettingDeployFunction && !enablePublicAccessWithPerimeter && !byoASEv3) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-privDnsFunc${deploymentProjSpecificUniqueSuffix}'
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
module rbacForFunctionMSI '../modules/functionRbac.bicep' = if(!functionAppExists && serviceSettingDeployFunction) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-rbacForFunction${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount1001Name // Using same storage account
    aiSearchName: aiSearchName
    functionPrincipalId: var_functionPrincipalId // Using computed variable for principal ID
    openAIName: aoaiName
    aiServicesName: aiServicesName
  }
  dependsOn: [
    function
  ]
}

// ============== CONTAINER APPS ENVIRONMENT ==============

module containerAppsEnv '../modules/containerapps.bicep' = if(!containerAppsEnvExists && serviceSettingDeployContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-aca-env-${deploymentProjSpecificUniqueSuffix}'
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
  }
  dependsOn: [
    existingTargetRG
    ...(miACAExists ? [] : [miForAca])
    ...(useCommonACR && !miACAExists ? [miRbac] : [])
    ...(!useCommonACR && !miACAExists ? [miRbacProj] : [])
    subnetDelegationAca
  ]
}

module privateDnscontainerAppsEnv '../modules/privateDns.bicep' = if(!containerAppsEnvExists && !centralDnsZoneByPolicyInHub && serviceSettingDeployContainerApps && !enablePublicAccessWithPerimeter) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-privDnsACAEnv${deploymentProjSpecificUniqueSuffix}'
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
resource bingREF 'Microsoft.Bing/accounts@2020-06-10' existing = if(serviceSettingDeployBingSearch) {
  name: bingName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318 BCP422
var var_bing_api_Key = serviceSettingDeployBingSearch? bingREF.listKeys().key1:'BCP318'

// ============== CONTAINER APPS - API ==============

module acaApi '../modules/containerappApi.bicep' = if(!containerAppAExists && serviceSettingDeployContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-aca-a-${deploymentProjSpecificUniqueSuffix}'
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
    identityId: miPrincipalId // Using the variable instead of module output
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
    aiProjectName: aiProjectName
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
    ...(miACAExists ? [] : [miForAca])
  ]
}

// ============== CONTAINER APPS - WEB ==============

module acaWebApp '../modules/containerappWeb.bicep' = if(!containerAppWExists && serviceSettingDeployContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05-aca-w-${deploymentProjSpecificUniqueSuffix}'
  params: {
    location: location
    tags: tagsProject
    name: containerAppWName
    apiEndpoint: 'https://${containerAppAName}.${var_containerAppApiDomain}' // Using computed domain variable
    allowedOrigins: allowedOrigins
    containerAppsEnvironmentName: containerAppsEnvName // Using direct name
    containerAppsEnvironmentId: '${subscription().subscriptionId}/resourceGroups/${targetResourceGroup}/providers/Microsoft.App/managedEnvironments/${containerAppsEnvName}'
    containerRegistryName: var_acr_cmn_or_prj
    identityId: miPrincipalId // Using the variable instead of module output
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
    acaApi
    ...(miACAExists ? [] : [miForAca])
  ]
}

// ============== RBAC FOR CONTAINER APPS ==============

module rbacForContainerAppsMI '../modules/containerappRbac.bicep' = if (!miACAExists && serviceSettingDeployContainerApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '05rbacACAMI${deploymentProjSpecificUniqueSuffix}'
  params: {
    aiSearchName: aiSearchName
    appInsightsName: applicationInsightName
    principalIdMI: miPrincipalId // Using the variable instead of module output
    resourceGroupId: existingTargetRG.id
  }
  dependsOn: [
    containerAppsEnv
    acaApi
    ...(miACAExists ? [] : [miForAca])
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs simplified to avoid conditional module reference issues
// Resource information should be retrieved through Azure CLI queries after deployment

@description('Web App deployment status')
output webAppDeployed bool = (!webAppExists && serviceSettingDeployWebApp)

@description('Function App deployment status')
output functionAppDeployed bool = (!functionAppExists && serviceSettingDeployFunction)

@description('Container Apps Environment deployment status')
output containerAppsEnvDeployed bool = (!containerAppsEnvExists && serviceSettingDeployContainerApps)

@description('Container App API deployment status')
output containerAppADeployed bool = (!containerAppAExists && serviceSettingDeployContainerApps)

@description('Container App Web deployment status')
output containerAppWDeployed bool = (!containerAppWExists && serviceSettingDeployContainerApps)

@description('Managed Identity for Container Apps deployment status')
output miACADeployed bool = !miACAExists
