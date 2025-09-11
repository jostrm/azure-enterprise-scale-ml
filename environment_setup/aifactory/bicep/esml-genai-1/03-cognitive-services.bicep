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
@allowed(['free', 'basic', 'standard', 'standard2', 'standard3', 'storage_optimized_l1', 'storage_optimized_l2'])
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
param miACAExists bool = false
param miPrjExists bool = false

// Users
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''

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

// GPT X
@description('Whether to deploy GPT-X model')
param deployModel_gpt_X bool = false
@description('GPT-X model name if deploying')
param modelGPTXName string = 'gpt-5-mini'
@description('GPT-X model version if deploying')
param modelGPTXVersion string = '1'
@allowed(['Standard','DataZoneStandard','GlobalStandard'])
param modelGPTXSku string = 'DataZoneStandard'
@description('TPM:Tokens per Minute Rate Limit in K=1000) 30 meaning 30K')
param modelGPTXCapacity int = 30

// Model deployment settings
param deployModel_text_embedding_3_large bool = false
param deployModel_text_embedding_3_small bool = false
param deployModel_text_embedding_ada_002 bool = false
param default_embedding_capacity int = 25

// 4o-mini
param deployModel_gpt_4o_mini bool = false
param default_gpt_capacity int = 40
param default_model_sku string = 'Standard'

//param deployModel_gpt_4o bool = false
//param modelGPT4Name string = ''
//param modelGPT4Version string = ''

// Security and networking
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param enablePublicNetworkAccessForCognitive bool = true
param disableLocalAuth bool = false

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
  name: take('03-getPrivDnsZ-${targetResourceGroup}', 64)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

// Get managed identity principal IDs using helper modules
module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = if (!miPrjExists) {
  name: take('03-getPrMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

module getACAMIPrincipalId '../modules/get-managed-identity-info.bicep' = if (!miACAExists) {
  name: take('03-getACAMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miACAName
  }
}

// ============== VARIABLES ==============
var subscriptionIdDevTestProd = subscription().subscriptionId
var deploymentProjSpecificUniqueSuffix = '${projectNumber}${env}${targetResourceGroup}'

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('03-naming-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
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
var miACAName = namingConvention.outputs.miACAName
var miPrjName = namingConvention.outputs.miPrjName
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

// Service kind configurations
var kindContentSafety = 'ContentSafety'
var kindAIServices = 'AIServices'
var kindAOpenAI = 'OpenAI'

resource projectResourceGroupExists 'Microsoft.Resources/resourceGroups@2025-04-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// Keyvault existing reference
resource existingKeyvault 'Microsoft.KeyVault/vaults@2024-11-01' existing = if (keyvaultExists) {
  name: keyvaultName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

// ============== DNS CONFIGURATIONS ==============
// DNS configurations for private endpoints - using dynamic outputs from modules
#disable-next-line BCP318
var var_csContentSafety_dnsConfig = csContentSafety.outputs.dnsConfig

#disable-next-line BCP318
var var_csVision_dnsConfig = csVision.outputs.dnsConfig

#disable-next-line BCP318
var var_csSpeech_dnsConfig = csSpeech.outputs.dnsConfig

#disable-next-line BCP318
var var_csDocIntelligence_dnsConfig = csDocIntelligence.outputs.dnsConfig

#disable-next-line BCP318
var var_csAzureOpenAI_dnsConfig = csAzureOpenAI.outputs.dnsConfig

#disable-next-line BCP318
var var_aiSearchService_dnsConfig = enableAISearch ? (!empty(aiSearchService.outputs.dnsConfig[0].name) ? aiSearchService.outputs.dnsConfig : []) : []

#disable-next-line BCP318
var var_sa4AIsearch_dnsConfig = sa4AIsearch.outputs.dnsConfig

// ============== COGNITIVE SERVICES ==============

// Content Safety
module csContentSafety '../modules/csContentSafety.bicep' = if(serviceSettingDeployContentSafety == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-ContentSafety${deploymentProjSpecificUniqueSuffix}', 64)
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
    projectResourceGroupExists
  ]
}

// Vision Services
module csVision '../modules/csVision.bicep' = if(serviceSettingDeployAzureAIVision == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-Vision4${deploymentProjSpecificUniqueSuffix}', 64)
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
    projectResourceGroupExists
    ...(keyvaultExists ? [existingKeyvault] : [])
  ]
}

// Speech Services
module csSpeech '../modules/csSpeech.bicep' = if(serviceSettingDeployAzureSpeech == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-AISpeech4${deploymentProjSpecificUniqueSuffix}', 64)
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
    projectResourceGroupExists
    ...(keyvaultExists ? [existingKeyvault] : [])
  ]
}

// Document Intelligence
module csDocIntelligence '../modules/csDocIntelligence.bicep' = if(serviceSettingDeployAIDocIntelligence == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-AIDocInt4${deploymentProjSpecificUniqueSuffix}', 64)
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
    projectResourceGroupExists
    ...(keyvaultExists ? [existingKeyvault] : [])
  ]
}

// Storage for AI Search
module sa4AIsearch '../modules/storageAccount.bicep' = if(!storageAccount2001Exists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-GenAISAAcc4${deploymentProjSpecificUniqueSuffix}', 64)
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
      {
        allowedOrigins: [
          '*'
        ]
        allowedMethods: [
          'GET'
          'OPTIONS'
          'POST'
          'PUT'
        ]
        maxAgeInSeconds: 200
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
    projectResourceGroupExists
  ]
}

// AI Search Service
module aiSearchService '../modules/aiSearch.bicep' = if (!aiSearchExists && enableAISearch) {
  name: take('03-AzureAISearch4${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    aiSearchName: safeNameAISearch
    location: location
    replicaCount: aiSearchReplicaCount
    partitionCount: aiSearchPartitionCount
    privateEndpointName: '${safeNameAISearch}-pend'
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
    managedIdentities: {
    systemAssigned: true
    userAssignedResourceIds: union(
      !empty(miPrjName) ? [resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)] : [],
      !empty(miACAName) ? [resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miACAName)] : []
      )
    }
  }
  dependsOn: [
    projectResourceGroupExists
    ...(!storageAccount2001Exists ? [sa4AIsearch] : [])
    ...(!miPrjExists ? [getProjectMIPrincipalId] : [])
    ...(!miACAExists ? [getACAMIPrincipalId] : [])
  ]
}

// AI Services (Multi-service account)
module aiServices '../modules/csAIServices.bicep' = if(!aiServicesExists && enableAIServices) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-AIServices4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    location: location
    managedIdentities: {
    systemAssigned: true
    userAssignedResourceIds: union(
      !empty(miPrjName) ? [resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)] : [],
      !empty(miACAName) ? [resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miACAName)] : []
      )
    }
    sku: csAIservicesSKU
    tags: tagsProject
    vnetResourceGroupName: vnetResourceGroupName
    cognitiveName: aiServicesName
    pendCogSerName: 'aiservices${projectName}${env}${uniqueInAIFenv}${resourceSuffix}-pend'
    restore: restore
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    keyvaultName: keyvaultName
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
    deployModel_gpt_X: deployModel_gpt_X
    modelGPTXName: modelGPTXName
    modelGPTXVersion: modelGPTXVersion
    modelGPTXSku:modelGPTXSku
    modelGPTXCapacity:modelGPTXCapacity
    deployModel_gpt_4o_mini: deployModel_gpt_4o_mini
    deployModel_text_embedding_3_small: deployModel_text_embedding_3_small
    deployModel_text_embedding_3_large: deployModel_text_embedding_3_large
    deployModel_text_embedding_ada_002: deployModel_text_embedding_ada_002
    default_embedding_capacity: default_embedding_capacity
    default_gpt_capacity: default_gpt_capacity
    default_model_sku: default_model_sku
  }
  dependsOn: [
    projectResourceGroupExists
    ...(keyvaultExists ? [existingKeyvault] : [])
    ...(!storageAccount2001Exists ? [sa4AIsearch] : [])
  ]
}

// Get AI Search principal ID - always called but with conditional logic inside
module getAISearchInfo '../modules/get-aisearch-info.bicep' = {
  name: take('03-getAISearchI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    aiSearchName: safeNameAISearch
    aiSearchExists: aiSearchExists
  }
}

// Azure OpenAI - with conditional AI Search principal ID
module csAzureOpenAI '../modules/csOpenAI.bicep' = if(!openaiExists && serviceSettingDeployAzureOpenAI) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-AzureOpenAI4${deploymentProjSpecificUniqueSuffix}', 64)
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
    aiSearchPrincipalId: getAISearchInfo.outputs.principalId // will return empty if AI Search does not exist''
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
    projectResourceGroupExists
    ...(!storageAccount2001Exists ? [sa4AIsearch] : [])
    ...(keyvaultExists ? [existingKeyvault] : [])
  ]
}

// ============== PRIVATE DNS MODULES ==============

// Content Safety Private DNS
module privateDnsContentSafety '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployContentSafety == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-privDnsCS${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_csContentSafety_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    projectResourceGroupExists
  ]
}

// Vision Services Private DNS
module privateDnsVision '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployAzureAIVision == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-privDnsVision${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_csVision_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    projectResourceGroupExists
  ]
}

// Speech Services Private DNS
module privateDnsSpeech '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployAzureSpeech == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-privDnsSpeech${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_csSpeech_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    projectResourceGroupExists
  ]
}

// Document Intelligence Private DNS
module privateDnsDocInt '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployAIDocIntelligence == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-privDnsDocInt${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_csDocIntelligence_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    projectResourceGroupExists
  ]
}

// Azure OpenAI Private DNS
module privateDnsAzureOpenAI '../modules/privateDns.bicep' = if(!openaiExists && serviceSettingDeployAzureOpenAI && !centralDnsZoneByPolicyInHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-privDnsLAOAI${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_csAzureOpenAI_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    projectResourceGroupExists
  ]
}

// AI Search Service Private DNS
module privateDnsAiSearchService '../modules/privateDns.bicep' = if(!aiSearchExists && !centralDnsZoneByPolicyInHub && enableAISearch) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-privDnsAISearch${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_aiSearchService_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    projectResourceGroupExists
  ]
}

// Storage for AI Search Private DNS
module privateDnsStorageGenAI '../modules/privateDns.bicep' = if(!storageAccount2001Exists && centralDnsZoneByPolicyInHub == false) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('03-privDnsSAGenAI${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_sa4AIsearch_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    projectResourceGroupExists
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs removed to avoid conditional module reference issues
// Resource outputs should be retrieved from foundation deployment or
// through separate queries after deployment completion
