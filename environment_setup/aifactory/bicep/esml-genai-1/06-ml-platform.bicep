targetScope = 'subscription'

// ================================================================
// ML PLATFORM DEPLOYMENT - Phase 6 Implementation
// This file deploys ML and AI platform services including:
// - Azure Machine Learning Workspace (v2)
// - AI Foundry Hub and Project
// - Azure Kubernetes Service (AKS) for ML workloads
// - Compute Instances and Clusters
// - RBAC and permissions for ML platform
// ================================================================

// ============================================================================
// SKU for services
// ============================================================================
// Azure ML Workspace SKUs
param mlWorkspaceSkuName string = 'basic'
param mlWorkspaceSkuTier string = 'basic'

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

// Resource exists flags from Azure DevOps
param amlExists bool = false
param aiHubExists bool = false
param aifProjectExists bool = false
param aksExists bool = false

// Enable flags from parameter files
@description('Enable Azure Machine Learning deployment')
param enableAzureMachineLearning bool = true

@description('Enable AI Foundry Hub deployment')
param enableAIFoundryHub bool = true

@description('Enable AI Foundry Preview features')
param serviceSettingEnableAIFoundryPreview bool = false

// Security and networking
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param centralDnsZoneByPolicyInHub bool = false
param AMLStudioUIPrivate bool = true
param allowPublicAccessWhenBehindVnet bool = false

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

// AKS Configuration
param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aksDockerBridgeCidr string = '172.17.0.1/16'
param aksOutboundType string = 'loadBalancer'
var aksDefaultVersion = '1.30.3'

// AKS SKU overrides
param aks_dev_sku_override string = ''
param aks_test_prod_sku_override string = ''
param aks_version_override string = ''
param aks_dev_nodes_override int = -1
param aks_test_prod_nodes_override int = -1

// Azure ML Compute Instance overrides
param aml_ci_dev_sku_override string = ''
param aml_ci_test_prod_sku_override string = ''

// Azure ML Compute Cluster overrides
param aml_cluster_dev_sku_override string = ''
param aml_cluster_test_prod_sku_override string = ''
param aml_cluster_dev_nodes_override int = -1
param aml_cluster_test_prod_nodes_override int = -1

// Tags
param tagsProject object = {}
param tags object = {}

// IP Rules
param IPwhiteList string = ''

// Dependencies and naming
param aifactorySuffixRG string
param commonRGNamePrefix string

// Naming convention module
param aifactorySalt10char string = ''
param randomValue string = ''
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId

// Common ACR usage
param useCommonACR bool = true

// Technical contact and user groups
param technicalContactId string = ''
param p011_genai_team_lead_array array = []
param spAndMiArray array = []
param useAdGroups bool = false
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
var deploymentProjSpecificUniqueSuffix = '${projectName}${env}${randomSalt}'

// ============================================================================
// COMPUTED VARIABLES - Networking subnets
// ============================================================================
var segments = split(genaiSubnetId, '/')
var vnetName = segments[length(segments) - 3] // Get the vnet name
var defaultSubnet = genaiSubnetName

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: 'naming-convention-${projectName}-${env}'
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

// AML
var amlName = namingConvention.outputs.amlName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName
//var aksClusterName = namingConvention.outputs.aksClusterName

// AI Foundry Hub
var aiHubName = namingConvention.outputs.aiHubName
var aifName = namingConvention.outputs.aifName
var aifProjectName = namingConvention.outputs.aifPrjName
var aiSearchName = namingConvention.outputs.safeNameAISearch
var aiServicesName = namingConvention.outputs.aiServicesName

// Common: AML, AI Fondry Hub
var acrProjectName = namingConvention.outputs.acrProjectName
var acrCommonName = namingConvention.outputs.acrCommonName
var var_acr_cmn_or_prj = useCommonACR ? acrCommonName : acrProjectName
var genaiSubnetName = namingConvention.outputs.genaiSubnetName
var aksSubnetName = namingConvention.outputs.aksSubnetName
var genaiName = namingConvention.outputs.projectTypeGenAIName
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var keyvaultName = namingConvention.outputs.keyvaultName
var applicationInsightName = namingConvention.outputs.applicationInsightName
//var cmnName = namingConvention.outputs.cmnName
//var uniqueInAIFenv = namingConvention.outputs.uniqueInAIFenv
//var prjResourceSuffixNoDash = namingConvention.outputs.prjResourceSuffixNoDash

// IP Rules processing
var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []
var ipWhitelist_remove_ending_32 = [for ip in ipWhitelist_array: replace(ip, '/32', '')]

var processedIpRulesAzureML = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

var processedIpRulesAIHub = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: trim(ip)
}]

// Network references using proper resource references
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  scope: resourceGroup(subscription().subscriptionId, vnetResourceGroupName)
  name: vnetNameFull
}

// Private DNS zones (simplified structure)
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones
// ============== AKS AND ML COMPUTE DEFAULTS ==============

// AKS: Azure Kubernetes Service defaults
param aks_dev_defaults array = [
  'Standard_B4ms' // 4 cores, 16GB, 32GB storage: Burstable
  'Standard_A4m_v2' // 4cores, 32GB, 40GB storage
  'Standard_D3_v2' // 4 cores, 14GB RAM, 200GB storage
]

param aks_testProd_defaults array = [
  'Standard_DS13-2_v2' // 8 cores, 14GB, 112GB storage
  'Standard_A8m_v2' // 8 cores, 64GB RAM, 80GB storage
]

// Azure ML Compute defaults
param aml_dev_defaults array = [
  'Standard_DS3_v2' // 4 cores, 14GB ram, 28GB storage
  'Standard_F8s_v2' // 8,16,64
  'Standard_DS12_v2' // 4 cores, 28GB RAM, 56GB storage
]

param aml_testProd_defaults array = [
  'Standard_D13_v2' // 8 cores, 56GB, 400GB storage
  'Standard_D4_v2' // 8 cores, 28GB RAM, 400GB storage
  'Standard_F16s_v2' // 16 cores, 32GB RAM, 128GB storage
]

// Compute Instance defaults
param ci_dev_defaults array = [
  'Standard_DS11_v2' // 2 cores, 14GB RAM, 28GB storage
]
param ci_devTest_defaults array = [
  'Standard_D11_v2'
]

// Compute parameter resolution with overrides
var aks_dev_sku_param = !empty(aks_dev_sku_override) ? aks_dev_sku_override : aks_dev_defaults[0]
var aks_test_prod_sku_param = !empty(aks_test_prod_sku_override) ? aks_test_prod_sku_override : aks_testProd_defaults[0]
var aks_version_param = !empty(aks_version_override) ? aks_version_override : aksDefaultVersion
var aks_dev_nodes_param = aks_dev_nodes_override != -1 ? aks_dev_nodes_override : 1
var aks_test_prod_nodes_param = aks_test_prod_nodes_override != -1 ? aks_test_prod_nodes_override : 3

var aml_ci_dev_sku_param = !empty(aml_ci_dev_sku_override) ? aml_ci_dev_sku_override : ci_dev_defaults[0]
var aml_ci_test_prod_sku_param = !empty(aml_ci_test_prod_sku_override) ? aml_ci_test_prod_sku_override : ci_devTest_defaults[0]

var aml_cluster_dev_sku_param = !empty(aml_cluster_dev_sku_override) ? aml_cluster_dev_sku_override : aml_dev_defaults[0]
var aml_cluster_test_prod_sku_param = !empty(aml_cluster_test_prod_sku_override) ? aml_cluster_test_prod_sku_override : aml_testProd_defaults[1]
var aml_cluster_dev_nodes_param = aml_cluster_dev_nodes_override != -1 ? aml_cluster_dev_nodes_override : 3
var aml_cluster_test_prod_nodes_param = aml_cluster_test_prod_nodes_override != -1 ? aml_cluster_test_prod_nodes_override : 3

resource existingTargetRG 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// Log Analytics Workspace reference
resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laWorkspaceName
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// ============== AZURE MACHINE LEARNING WORKSPACE ==============

module amlv2 '../modules/machineLearningv2.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AzureMLDepl_${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: amlName
    uniqueDepl: deploymentProjSpecificUniqueSuffix
    uniqueSalt5char: namingConvention.outputs.uniqueInAIFenv
    projectName: projectName
    projectNumber: projectNumber
    location: location
    locationSuffix: locationSuffix
    aifactorySuffix: aifactorySuffixRG
    skuName: mlWorkspaceSkuName
    skuTier: mlWorkspaceSkuTier
    env: env
    aksSubnetId: aksSubnetId
    aksSubnetName: aksSubnetName
    aksDnsServiceIP: aksDnsServiceIP
    aksServiceCidr: aksServiceCidr
    tags: tagsProject
    vnetId: vnet.id
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-aml-to-vnt-mlcmn'
    amlPrivateDnsZoneID: privateLinksDnsZones.amlworkspace.id
    notebookPrivateDnsZoneID: privateLinksDnsZones.notebooks.id
    allowPublicAccessWhenBehindVnet: (AMLStudioUIPrivate == true && empty(ipWhitelist_remove_ending_32)) ? false : true
    enablePublicAccessWithPerimeter: AMLStudioUIPrivate == false ? true : false
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    aksVmSku_dev: aks_dev_sku_param
    aksVmSku_testProd: aks_test_prod_sku_param
    aksNodes_dev: aks_dev_nodes_param
    aksNodes_testProd: aks_test_prod_nodes_param
    kubernetesVersionAndOrchestrator: aks_version_param
    amlComputeDefaultVmSize_dev: aml_cluster_dev_sku_param
    amlComputeDefaultVmSize_testProd: aml_cluster_test_prod_sku_param
    amlComputeMaxNodex_dev: aml_cluster_dev_nodes_param
    amlComputeMaxNodex_testProd: aml_cluster_test_prod_nodes_param
    ciVmSku_dev: aml_ci_dev_sku_param
    ciVmSku_testProd: aml_ci_test_prod_sku_param
    ipRules: empty(processedIpRulesAzureML) ? [] : processedIpRulesAzureML
    ipWhitelist_array: empty(ipWhitelist_remove_ending_32) ? [] : ipWhitelist_remove_ending_32
    saName: storageAccount2001Name
    kvName: keyvaultName
    acrName: var_acr_cmn_or_prj
    acrRGName: useCommonACR ? commonResourceGroup : targetResourceGroup
    appInsightsName: applicationInsightName
  }
  dependsOn: [
    existingTargetRG
    // Dependencies handled through parameters - storage, keyvault, ACR should exist from previous phases
  ]
}

// RBAC for Azure ML
module rbacAmlv2 '../modules/rbacStorageAml.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbacUsersAmlVersion2${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount2001Name
    userObjectIds: p011_genai_team_lead_array
    azureMLworkspaceName: amlName
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups: useAdGroups
    user2Storage: true
  }
  dependsOn: [
    ...(!amlExists && enableAzureMachineLearning ? [amlv2] : [])
  ]
}

// ============== AI FOUNDRY BASIC (PREVIEW) ==============

module aiFoundry '../modules/csFoundry/csAIFoundryBasic.bicep' = if(!aifProjectExists && serviceSettingEnableAIFoundryPreview) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AIFoundryPrevview4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aifName
    projectName: aifProjectName
    enablePublicAccessWithPerimeter: true
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== AI FOUNDRY HUB ==============

module aiHub '../modules/machineLearningAIHub.bicep' = if(!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'aiHubModule${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aiHubName
    defaultProjectName: aifProjectName
    location: location
    tags: tagsProject
    aifactorySuffix: aifactorySuffixRG
    applicationInsightsName: applicationInsightName
    acrName: var_acr_cmn_or_prj
    acrRGName: useCommonACR ? commonResourceGroup : targetResourceGroup
    env: env
    keyVaultName: keyvaultName
    privateEndpointName: 'p-aihub-${projectName}${locationSuffix}${env}${genaiName}amlworkspace'
    aifactoryProjectNumber: projectNumber
    storageAccountName: storageAccount1001Name
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    enablePublicGenAIAccess: enablePublicGenAIAccess
    aiSearchName: aiSearchName
    privateLinksDnsZones: privateLinksDnsZones
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    kindAIHub: 'Hub'
    aiServicesName: aiServicesName
    logWorkspaceName: logAnalyticsWorkspaceOpInsight.name
    logWorkspaceResoureGroupName: commonResourceGroup
    locationSuffix: locationSuffix
    resourceSuffix: resourceSuffix
    aifactorySalt: namingConvention.outputs.uniqueInAIFenv
    ipRules: empty(processedIpRulesAIHub) ? [] : processedIpRulesAIHub
    ipWhitelist_array: empty(ipWhitelist_remove_ending_32) ? [] : ipWhitelist_remove_ending_32
  }
  dependsOn: [
    existingTargetRG
    // Dependencies handled through parameters - storage, keyvault, ACR, AI Search should exist from previous phases
  ]
}

// ============== RBAC FOR PROJECT-SPECIFIC ACR ==============

module rbacAcrProjectspecific '../modules/acrRbac.bicep' = if(useCommonACR == false && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbacAcrProject${deploymentProjSpecificUniqueSuffix}'
  params: {
    acrName: var_acr_cmn_or_prj
    aiHubName: aiHubName
    aiHubRgName: targetResourceGroup
  }
  dependsOn: [
    ...(!aiHubExists && enableAIFoundryHub ? [aiHub] : [])
  ]
}

// ============== MACHINE LEARNING RBAC ==============

module rbackSPfromDBX2AMLSWC '../modules/machinelearningRBAC.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbacDBX2AMLGenAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlName: amlName
    servicePrincipleAndMIArray: spAndMiArray
    adfSP: '' // ADF Service Principal - empty if not using ADF integration
    projectADuser: technicalContactId
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    ...(!amlExists && enableAzureMachineLearning ? [amlv2] : [])
    logAnalyticsWorkspaceOpInsight
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs simplified to avoid conditional module reference issues
// Resource information should be retrieved through Azure CLI queries after deployment

@description('Azure ML Workspace deployment status')
output azureMLDeployed bool = (!amlExists && enableAzureMachineLearning)

@description('AI Foundry Hub deployment status')
output aiFoundryHubDeployed bool = (!aiHubExists && enableAIFoundryHub)

@description('AI Foundry Preview deployment status')
output aiFoundryPreviewDeployed bool = (!aifProjectExists && serviceSettingEnableAIFoundryPreview)

@description('Project-specific ACR RBAC deployment status')
output acrRbacDeployed bool = (useCommonACR == false && enableAIFoundryHub)

@description('ML Platform RBAC deployment status')
output mlPlatformRbacDeployed bool = (!amlExists && enableAzureMachineLearning)
