targetScope = 'subscription'

@allowed(['dev', 'test', 'prod'])
param env string
param projectNumber string
param location string
param locationSuffix string
param commonResourceSuffix string
param resourceSuffix string
param randomValue string
param aifactorySuffixRG string
param commonRGNamePrefix string
param vnetNameBase string
param genaiSubnetId string
param aksSubnetId string = ''
param acaSubnetId string = ''
param aca2SubnetId string = ''
param aks2SubnetId string = ''
param aifactorySalt10char string = ''
param commonResourceGroup_param string = ''
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''
param centralDnsZoneByPolicyInHub bool = false
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'
param commonResourceName string = 'esml-common'
param tagsProject object = {}

@allowed(['free', 'basic', 'standard', 'standard2', 'standard3', 'storage_optimized_l1', 'storage_optimized_l2'])
param skuAISearchDev string = 'standard'
@allowed(['free', 'basic', 'standard', 'standard2', 'standard3', 'storage_optimized_l1', 'storage_optimized_l2'])
param skuAISearchStageProd string = 'standard'
param aiSearchLocation string = ''
param aiSearchExists bool = false
param enableAISearch bool = true
param enableAIFoundry bool = false
param addAISearch bool = false
param enableAISearchSharedPrivateLink bool = true
param enableAIServices bool = true
param aiSearchReplicaCount int = 1
param aiSearchPartitionCount int = 1
@allowed(['disabled', 'free', 'standard'])
param semanticSearchTier string = 'free'
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param IPwhiteList string = ''
param skipDiagAISearch bool = true
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'gold'
param cmk bool = false
param cmkDisableForAISearch bool = false
param cmkKeyName string = ''
param admin_bicep_kv_fw string = ''
param admin_bicep_kv_fw_rg string = ''
param admin_bicep_input_keyvault_subscription string = ''

var standaloneDeploymentSuffix = uniqueString(subscription().subscriptionId, commonRGNamePrefix, aifactorySuffixRG, projectNumber, env, locationSuffix, resourceSuffix)

module deploymentContext '../modules/common/CmnServiceDeploymentContext.bicep' = {
  name: '03b-context-${standaloneDeploymentSuffix}'
  params: {
    deploymentPrefix: '03b'
    env: env
    projectNumber: projectNumber
    location: location
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    randomValue: randomValue
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    vnetNameBase: vnetNameBase
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
    aca2SubnetId: aca2SubnetId
    aks2SubnetId: aks2SubnetId
    aifactorySalt10char: aifactorySalt10char
    commonResourceGroup_param: commonResourceGroup_param
    vnetResourceGroup_param: vnetResourceGroup_param
    vnetNameFull_param: vnetNameFull_param
    network_env: network_env
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    privDnsSubscription_param: privDnsSubscription_param
    privDnsResourceGroup_param: privDnsResourceGroup_param
    projectPrefix: projectPrefix
    projectSuffix: projectSuffix
    commonResourceName: commonResourceName
  }
}

var context = deploymentContext.outputs.context
var originalName = context.names.safeNameAISearch
var baseName = take(originalName, max(length(originalName) - 3, 0))
var suffix = substring(originalName, max(length(originalName) - 3, 0), min(3, length(originalName)))
var aiSearchName = take(addAISearch ? '${baseName}${take(context.names.randomSalt, 2)}${suffix}' : originalName, 60)
var needsAISearch = enableAISearch || (enableAIFoundry && !enablePublicGenAIAccess)

module search '../modules/services/aiSearchDeployment.bicep' = if (needsAISearch) {
  name: '03b-search-${standaloneDeploymentSuffix}'
  params: {
    context: context
    deploymentSuffix: '${projectNumber}${env}${context.targetResourceGroup}'
    aiSearchName: aiSearchName
    location: location
    aiSearchLocation: aiSearchLocation
    skuName: env == 'dev' ? skuAISearchDev : skuAISearchStageProd
    tagsProject: tagsProject
    aiSearchExists: aiSearchExists
    enableAISearchSharedPrivateLink: enableAISearchSharedPrivateLink
    enableAIServices: enableAIServices
    aiSearchReplicaCount: aiSearchReplicaCount
    aiSearchPartitionCount: aiSearchPartitionCount
    semanticSearchTier: semanticSearchTier
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    IPwhiteList: IPwhiteList
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    skipDiagAISearch: skipDiagAISearch
    diagnosticSettingLevel: diagnosticSettingLevel
    cmk: cmk
    cmkDisableForAISearch: cmkDisableForAISearch
    cmkKeyName: cmkKeyName
    admin_bicep_kv_fw: admin_bicep_kv_fw
    admin_bicep_kv_fw_rg: admin_bicep_kv_fw_rg
    admin_bicep_input_keyvault_subscription: admin_bicep_input_keyvault_subscription
  }
}

output aiSearchName string = needsAISearch ? aiSearchName : ''
output aiSearchDeployed bool = needsAISearch
