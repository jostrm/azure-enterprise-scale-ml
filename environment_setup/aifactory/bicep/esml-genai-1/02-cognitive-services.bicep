targetScope = 'subscription'

// ================================================================
// COGNITIVE SERVICES DEPLOYMENT - Phase 2 Implementation
// This file deploys all AI and Cognitive Services including:
// - Azure AI Services
// - Azure OpenAI
// - Content Safety  
// - Vision Services
// - Speech Services
// - Document Intelligence
// - AI Search
// ================================================================

// ============================================================================
// SKU for services
// ============================================================================
@allowed(['disabled', 'free', 'standard'])
param semanticSearchTier string = 'free'
@allowed(['S0', 'S1', 'standard', 'standard2'])
param aiSearchSKUName string = 'standard'
param aiSearchReplicaCount int = 1
param aiSearchPartitionCount int = 1
param csAIservicesSKU string = 'S0'
param csOpenAISKU string = 'S0'
param csContentSafetySKU string = 'S0'
param csVisionSKU string = 'S1'
param csSpeechSKU string = 'S0'
param csDocIntelligenceSKU string = 'S0'
param storageAccountSkuName string = 'Standard_LRS'

// ============================================================================
// PARAMETERS - Core Configuration
// ============================================================================

@description('AI Factory version information')
param aifactoryVersionMajor int = 1
param aifactoryVersionMinor int = 22
var activeVersion = 122

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

@description('Random value for deployment uniqueness')
param randomValue string = ''

// Resource exists flags from Azure DevOps
param aiServicesExists bool = false
param openaiExists bool = false
param aiSearchExists bool = false
param keyvaultExists bool = false
param storageAccount2001Exists bool = false
param storageAccount1001Exists bool = false

// Enable flags from parameter files
@description('Enable AI Services deployment')
param enableAIServices bool = true

@description('Enable AI Search deployment')
param enableAISearch bool = true

@description('Enable specific service deployments')
param serviceSettingDeployAzureOpenAI bool = false
param serviceSettingDeployContentSafety bool = false
param serviceSettingDeployAzureAIVision bool = false
param serviceSettingDeployAzureSpeech bool = false
param serviceSettingDeployAIDocIntelligence bool = false

// Model deployment settings
param deployModel_text_embedding_3_large bool = false
param deployModel_text_embedding_3_small bool = false
param deployModel_text_embedding_ada_002 bool = false
param default_embedding_capacity int = 25
param deployModel_gpt_4o_mini bool = false
param default_gpt_capacity int = 40
param default_model_sku string = 'Standard'
param deployModel_gpt_4 bool = false
param modelGPT4Name string = ''
param modelGPT4Version string = ''

// Security and networking
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param enablePublicNetworkAccessForCognitive bool = true
param disableLocalAuth bool = false

// Required resource references
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''

// Networking parameters for calculation
param vnetNameBase string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''

// Private DNS configuration
param centralDnsZoneByPolicyInHub bool = false
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// Resource group configuration
param commonResourceGroup_param string = ''

param aifactorySalt10char string = ''

// AI Search specific settings
param aiSearchEnableSharedPrivateLink bool = false

// Override regions
param serviceSettingOverrideRegionAzureAIVision string = ''
param serviceSettingOverrideRegionAzureAIVisionShort string = ''

// Tags
param tagsProject object = {}
param tags object = {}

// IP Rules
param IPwhiteList string = ''

// Dependencies and naming
param aifactorySuffixRG string
param commonRGNamePrefix string
param keyvaultSoftDeleteDays int = 90
param restore bool = false
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'

// ============================================================================
// CALCULATED VARIABLES
// ============================================================================
var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

// Networking calculations
var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup

// Private DNS calculations
var privDnsResourceGroupName = (!empty(privDnsResourceGroup_param) && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (!empty(privDnsSubscription_param) && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscription().subscriptionId

// ============================================================================
// FROM JSON files
// ============================================================================
// ============================================================================
// END - FROM JSON files
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

// ============== VARIABLES ==============
var subscriptionIdDevTestProd = subscription().subscriptionId
var deploymentProjSpecificUniqueSuffix = '${projectNumber}${env}${targetResourceGroup}'

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: 'naming-02-${targetResourceGroup}'
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
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
    acaSubnetId: acaSubnetId
    aksSubnetId:aksSubnetId
    genaiSubnetId:genaiSubnetId
  }
}

var uniqueInAIFenv = namingConvention.outputs.uniqueInAIFenv
var defaultSubnet = namingConvention.outputs.defaultSubnet
var genaiSubnetName = namingConvention.outputs.genaiSubnetName
var genaiName = namingConvention.outputs.genaiName
var aoaiName = namingConvention.outputs.aoaiName
var safeNameAISearch = namingConvention.outputs.safeNameAISearch
var aiServicesName = namingConvention.outputs.aiServicesName
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var keyvaultName = namingConvention.outputs.keyvaultName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName
//var miACAName = namingConvention.outputs.miACAName
//var miPrjName = namingConvention.outputs.miPrjName
//var p011_genai_team_lead_email_array = namingConvention.outputs.p011_genai_team_lead_email_array
//var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array
//var aksSubnetName = namingConvention.outputs.aksSubnetName
//var acaSubnetName = namingConvention.outputs.acaSubnetName
//var randomSalt = namingConvention.outputs.randomSalt

// IP Rules processing
var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []
var processedIpRulesAIServices = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: trim(ip)
}]
var processedIpRulesAISearch = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: trim(ip)
}]
var processedIpRulesSa = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: trim(ip)
}]

// Network references - using proper resource references
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetNameFull
  scope: resourceGroup(vnetResourceGroupName)
}

// Service kind configurations
var kindContentSafety = 'ContentSafety'
var kindAIServices = 'AIServices'
var kindAOpenAI = 'OpenAI'

// Target resource group reference
resource resourceExists_struct 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: targetResourceGroup
  location: location
}

// ============== COGNITIVE SERVICES ==============

// Content Safety
module csContentSafety '../modules/csContentSafety.bicep' = if(serviceSettingDeployContentSafety == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'ContentSafety4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csContentSafetySKU
    location: location
    restore: restore
    vnetResourceGroupName: vnetResourceGroupName
    contentsafetyName: 'cs-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: kindContentSafety
    pendCogSerName: 'p-${projectName}-contentsafety-${genaiName}'
    subnetName: genaiSubnetName
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess ? true : enablePublicNetworkAccessForCognitive
    vnetRules: [
      genaiSubnetId
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// Vision Services
module csVision '../modules/csVision.bicep' = if(serviceSettingDeployAzureAIVision == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'Vision4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csVisionSKU
    location: (!empty(serviceSettingOverrideRegionAzureAIVision)) ? serviceSettingOverrideRegionAzureAIVision : location
    restore: restore
    keyvaultName: keyvaultName
    vnetResourceGroupName: vnetResourceGroupName
    name: (!empty(serviceSettingOverrideRegionAzureAIVisionShort)) ? 'vision-${projectName}-${serviceSettingOverrideRegionAzureAIVisionShort}-${env}-${uniqueInAIFenv}${commonResourceSuffix}' : 'vision-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: 'ComputerVision'
    pendCogSerName: 'p-${projectName}-vision-${genaiName}'
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess ? true : enablePublicNetworkAccessForCognitive
    vnetRules: [
      genaiSubnetId
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// Speech Services
module csSpeech '../modules/csSpeech.bicep' = if(serviceSettingDeployAzureSpeech == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AISpeech4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csSpeechSKU
    location: location
    restore: restore
    keyvaultName: keyvaultName
    vnetResourceGroupName: vnetResourceGroupName
    name: 'speech-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: 'SpeechServices'
    pendCogSerName: 'p-${projectName}-speech-${genaiName}'
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess ? true : enablePublicNetworkAccessForCognitive
    vnetRules: [
      genaiSubnetId
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// Document Intelligence
module csDocIntelligence '../modules/csDocIntelligence.bicep' = if(serviceSettingDeployAIDocIntelligence == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AIDocIntelligence4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csDocIntelligenceSKU
    location: location
    restore: restore
    keyvaultName: keyvaultName
    vnetResourceGroupName: vnetResourceGroupName
    name: 'docs-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: 'FormRecognizer'
    pendCogSerName: 'p-${projectName}-docs-${genaiName}'
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess ? true : enablePublicNetworkAccessForCognitive
    vnetRules: [
      genaiSubnetId
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// Storage for AI Search
module sa4AIsearch '../modules/storageAccount.bicep' = if(!storageAccount2001Exists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'GenAISAAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount2001Name
    skuName: storageAccountSkuName
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    location: location
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}'
    filePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-file-${genaiName}'
    queuePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-queue-${genaiName}'
    tablePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-table-${genaiName}'
    tags: tagsProject
    ipRules: empty(processedIpRulesSa) ? [] : processedIpRulesSa
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
      genaiSubnetId
      
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
        allowedHeaders: [
          '*'
        ]
        exposedHeaders: [
          '*'
        ]
        maxAgeInSeconds: 86400
      }
    ]
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// AI Search Service
module aiSearchService '../modules/aiSearch.bicep' = if (!aiSearchExists && enableAISearch) {
  name: 'AzureAISearch4${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    aiSearchName: safeNameAISearch
    location: location
    replicaCount: aiSearchReplicaCount
    partitionCount: aiSearchPartitionCount
    privateEndpointName: 'p-${projectName}-aisearch-${genaiName}'
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    tags: tagsProject
    semanticSearchTier: semanticSearchTier
    publicNetworkAccess: enablePublicGenAIAccess
    skuName: aiSearchSKUName
    enableSharedPrivateLink: aiSearchEnableSharedPrivateLink
    sharedPrivateLinks: []
    ipRules: empty(processedIpRulesAISearch) ? [] : processedIpRulesAISearch
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
  }
  dependsOn: [
    resourceExists_struct
    ...(!storageAccount2001Exists ? [sa4AIsearch] : [])
  ]
}

// AI Services (Multi-service account)
module aiServices '../modules/csAIServices.bicep' = if(!aiServicesExists && enableAIServices) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AIServices4${deploymentProjSpecificUniqueSuffix}'
  params: {
    location: location
    sku: csAIservicesSKU
    tags: tagsProject
    vnetResourceGroupName: vnetResourceGroupName
    cognitiveName: aiServicesName
    pendCogSerName: 'p-${projectName}-aiservices-${genaiName}'
    restore: restore
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    keyvaultName: keyvaultName
    modelGPT4Version: modelGPT4Version
    kind: kindAIServices
    publicNetworkAccess: enablePublicGenAIAccess
    vnetRules: [
      genaiSubnetId
    ]
    ipRules: empty(processedIpRulesAIServices) ? [] : processedIpRulesAIServices
    disableLocalAuth: disableLocalAuth
    privateLinksDnsZones: privateLinksDnsZones
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    deployModel_gpt_4: deployModel_gpt_4
    modelGPT4Name: modelGPT4Name
    deployModel_gpt_4o_mini: deployModel_gpt_4o_mini
    deployModel_text_embedding_3_small: deployModel_text_embedding_3_small
    deployModel_text_embedding_3_large: deployModel_text_embedding_3_large
    deployModel_text_embedding_ada_002: deployModel_text_embedding_ada_002
    default_embedding_capacity: default_embedding_capacity
    default_gpt_capacity: default_gpt_capacity
    default_model_sku: default_model_sku
  }
  dependsOn: [
    resourceExists_struct
    ...(!storageAccount2001Exists ? [sa4AIsearch] : [])
  ]
}

// Get AI Search principal ID - always called but with conditional logic inside
module getAISearchInfo '../modules/get-aisearch-info.bicep' = {
  name: 'getAISearchInfo-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    aiSearchName: safeNameAISearch
    aiSearchExists: aiSearchExists
  }
}

// Azure OpenAI - with conditional AI Search principal ID
module csAzureOpenAI '../modules/csOpenAI.bicep' = if(!openaiExists && serviceSettingDeployAzureOpenAI) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AzureOpenAI4${deploymentProjSpecificUniqueSuffix}'
  params: {
    cognitiveName: aoaiName
    tags: tagsProject
    laWorkspaceName: laWorkspaceName
    restore: restore
    location: location
    vnetResourceGroupName: vnetResourceGroupName
    commonResourceGroupName: commonResourceGroup
    sku: csOpenAISKU
    vnetName: vnetNameFull
    subnetName: genaiSubnetName
    keyvaultName: keyvaultName
    modelGPT4Version: modelGPT4Version
    aiSearchPrincipalId: getAISearchInfo.outputs.principalId
    kind: kindAOpenAI
    pendCogSerName: 'p-${projectName}-openai-${genaiName}'
    publicNetworkAccess: enablePublicGenAIAccess
    disableLocalAuth: disableLocalAuth
    vnetRules: [
      genaiSubnetId
      aksSubnetId
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
  }
  dependsOn: [
    resourceExists_struct
    ...(!storageAccount2001Exists ? [sa4AIsearch] : [])
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs removed to avoid conditional module reference issues
// Resource outputs should be retrieved from foundation deployment or
// through separate queries after deployment completion
