targetScope = 'subscription'

// ================================================================
// AI FOUNDRY 2025 DEPLOYMENT - Phase 9 Implementation
// This file deploys the latest AI Foundry 2025 platform including:
// - AI Foundry Hub with advanced capabilities
// - AI Foundry Projects
// - Model deployments (GPT, embedding models)
// - Private endpoints and networking
// - RBAC and security configurations
// ================================================================

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

// Enable flags
@description('Enable AI Foundry 2 features')
param enableAIFoundryV2 bool = false
param enableAIFoundryV21 bool = false

@description('Enable AI Search integration')
param enableAISearch bool = true

@description('Enable Cosmos DB integration')
param serviceSettingDeployCosmosDB bool = false

// AI Models deployment parameters
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

@description('Whether to deploy text-embedding-ada-002 model')
param deployModel_text_embedding_ada_002 bool = false
@description('Whether to deploy text-embedding-3-large model')
param deployModel_text_embedding_3_large bool = false
@description('Whether to deploy text-embedding-3-small model')
param deployModel_text_embedding_3_small bool = false
@description('Default capacity for embedding models')
param default_embedding_capacity int = 25

@description('Default capacity for GPT models')
param default_gpt_capacity int = 40
@description('Whether to deploy GPT-4o model')
param deployModel_gpt_4o bool = false
param default_gpt_4o_version string = '2024-11-20'
@description('Whether to deploy GPT-4o-mini model')
param deployModel_gpt_4o_mini bool = false
param default_gpt_4o_mini_version string = '2024-07-18'

@description('Default SKU for models')
@allowed(['Standard','DataZoneStandard','GlobalStandard'])
param default_model_sku string = 'Standard'

// Security and networking
param enablePublicAccessWithPerimeter bool = false
param centralDnsZoneByPolicyInHub bool = false

// Networking subnet IDs
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''

// Networking parameters for calculation
param vnetNameBase string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''
param common_subnet_name string
param subnetCommon string = ''

// Private DNS configuration
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// Resource group configuration
param commonResourceGroup_param string = ''

// Tags
param tagsProject object = {}

// Dependencies and naming
param aifactorySuffixRG string
param commonRGNamePrefix string
param aifactorySalt10char string = ''
param randomValue string = ''
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId
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

// Random salt for unique naming
var randomSalt = substring(uniqueString(subscription().subscriptionId, targetResourceGroup), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${env}${randomSalt}'

// Subnet calculations
var commonSubnetPends = subnetCommon != '' ? replace(subnetCommon, '<network_env>', network_env) : common_subnet_name

// Get the subnet resource ID for the common subnet used for private endpoints
resource commonSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-04-01' existing = {
  name: '${vnetNameFull}/${commonSubnetPends}'
  scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)
}
var commonSubnetResourceId = commonSubnet.id

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: '09-naming-${targetResourceGroup}'
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

// AI Foundry V2 specific names
var aifV2ProjectName = namingConvention.outputs.aifV2Name
var aifV2Name = namingConvention.outputs.aifV2PrjName

// Private DNS zones
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  name: '09-getPrivDnsZ-${targetResourceGroup}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

resource existingTargetRG 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============== AI FOUNDRY V2 - 2025 ==============

// Dynamically build array of models to deploy based on parameters
var aiModels = concat(
  deployModel_gpt_X ? [{
    modelName: modelGPTXName
    version: modelGPTXVersion
    capacity: modelGPTXCapacity
    skuLocation: modelGPTXSku
  }] : [],
  deployModel_gpt_4o_mini ? [{
    modelName: 'gpt-4o-mini'
    version: default_gpt_4o_mini_version
    capacity: default_gpt_capacity
    skuLocation: default_model_sku
  }] : [],
  deployModel_gpt_4o ? [{
    modelName: 'gpt-4o'
    version: default_gpt_4o_version
    capacity: default_gpt_capacity
    skuLocation: default_model_sku
  }] : [],
  deployModel_text_embedding_ada_002 ? [{
    modelName: 'text-embedding-ada-002'
    version: '2'
    capacity: default_embedding_capacity
    skuLocation: default_model_sku
  }] : [],
  deployModel_text_embedding_3_large ? [{
    modelName: 'text-embedding-3-large'
    version: '1'
    capacity: default_embedding_capacity
    skuLocation: default_model_sku
  }] : [],
  deployModel_text_embedding_3_small ? [{
    modelName: 'text-embedding-3-small'
    version: '1'
    capacity: default_embedding_capacity
    skuLocation: default_model_sku
  }] : []
)

var aiFoundryZones = !enablePublicAccessWithPerimeter? [
  privateLinksDnsZones.openai.id
  privateLinksDnsZones.cognitiveservices.id
] : []

// Role assignments are now managed in 07-rbac-security.bicep
// We use deployment scripts to update permissions if needed after deployment
module aiFoundry2025 '../modules/csFoundry/aiFoundry2025.bicep' = if(enableAIFoundryV2) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '09-AifV2_${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aifV2Name
    defaultProjectName: '${aifV2ProjectName}-d'
    allowProjectManagement: true
    location:location
    // Provided subnet must be of the proper address space. Please provide a subnet which has address space in the range of 172 or 192
    agentSubnetResourceId: acaSubnetId // Delegated to Microsoft.App/environment due to ContainerApps hosting agents.
    enableTelemetry:false
    tags: tagsProject
    aiModelDeployments: [
      for model in aiModels: {
        name: model.modelName
        model: {
          name: model.modelName
          format: 'OpenAI'
          version: model.version
        }
        sku: {
          name: model.skuLocation
          capacity: model.capacity
        }
        raiPolicyName: 'Microsoft.DefaultV2'
        versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
      }
    ]
    privateEndpointSubnetResourceId: commonSubnetResourceId
    privateDnsZoneResourceIds:aiFoundryZones
    //roleAssignments: allRoleAssignments
    //lock:
  }
  dependsOn: [
    existingTargetRG
    // Dependencies handled through parameters - storage, keyvault, ACR, AI Search should exist from previous phases
  ]
}

// Add the new FDP cognitive services module
module project '../modules/csFoundry/aiFoundry2025project.bicep' = if(enableAIFoundryV2) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '09-AifV2_Prj_${deploymentProjSpecificUniqueSuffix}'
  params: {
    cosmosDBname: serviceSettingDeployCosmosDB? namingConvention.outputs.cosmosDBName : ''
    name: aifV2ProjectName
    location: location
    storageName: namingConvention.outputs.storageAccount1001Name
    #disable-next-line BCP318
    aiFoundryV2Name: aiFoundry2025.outputs.name
    aiSearchName: enableAISearch ? namingConvention.outputs.safeNameAISearch : ''
    }
    dependsOn: [
      existingTargetRG
      aiFoundry2025
    ]
}

// AI V2.1 - Cognitive Services Module (Alternative Implementation)
module aiFoundry2025NoAvm '../modules/csFoundry/aiFoundry2025AvmOff.bicep' = if (enableAIFoundryV21) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '09-AifV2-Avm_${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aifV2Name
    kind: 'AIServices'
    sku: 'S0'
    location: location
    enableTelemetry: false
    tags: tagsProject
    customSubDomainName: aifV2Name
    publicNetworkAccess: enablePublicAccessWithPerimeter ? 'Enabled' : 'Disabled'
    deployments: [
      for model in aiModels: {
        name: model.modelName
        model: {
          name: model.modelName
          format: 'OpenAI'
          version: model.version
        }
        sku: {
          name: model.skuLocation
          capacity: model.capacity
        }
        raiPolicyName: 'Microsoft.DefaultV2'
        versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
      }
    ]
    privateEndpoints: !enablePublicAccessWithPerimeter ? [
      {
        name: '${aifV2Name}-pe'
        subnetResourceId: commonSubnetResourceId
        privateDnsZoneResourceIds: aiFoundryZones
        service: 'account'
      }
    ] : null
  }
  dependsOn: [
    existingTargetRG
    // Dependencies handled through parameters - storage, keyvault, ACR, AI Search should exist from previous phases
  ]
}
// ============== OUTPUTS ==============

@description('AI Foundry V2 deployment status')
output aiFoundryV2Deployed bool = enableAIFoundryV2

@description('AI Foundry V2 name')
output aiFoundryV2Name string = enableAIFoundryV2 ? aiFoundry2025!.outputs.name : ''

@description('AI Foundry V2 resource ID')
output aiFoundryV2ResourceId string = enableAIFoundryV2 ? aiFoundry2025!.outputs.resourceId : ''

@description('AI Foundry Project deployment status')
output aiFoundryProjectDeployed bool = enableAIFoundryV2

@description('AI Models deployed count')
output aiModelsDeployed int = length(aiModels)
