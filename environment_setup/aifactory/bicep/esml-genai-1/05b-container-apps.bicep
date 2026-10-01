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
param subscriptionIdDevTestProd string = subscription().subscriptionId
param tagsProject object = {}

param enableContainerApps bool = true
@allowed(['Consumption', 'D4', 'D8'])
param skuContainerAppsDev string = 'Consumption'
@allowed(['Consumption', 'D4', 'D8'])
param skuContainerAppsStageProd string = 'Consumption'
param containerAppsEnvExists bool = false
param containerAppAExists bool = false
param containerAppWExists bool = false
@description('Opt in to replacing pre-existing app configuration. Original existence flags already allow reconciliation of resources created during this run.')
param updateExistingContainerApps bool = false
param wlMinCountServerless int = 0
param wlMinCountDedicated int = 1
param wlMaxCount int = 100
param wlProfileDedicatedName string = 'D4'
param wlProfileGPUConsumptionName string = 'Consumption-GPU-NC24-A100'
param acaAppWorkloadProfileName string = 'consumption'
param containerCpuCoreCount int = 1
param containerMemory string = '2.0Gi'
param aca_a_registry_image string = ''
param aca_w_registry_image string = ''
param aca_default_image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param acaCustomDomainsArray array = []
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param IPwhiteList string = ''
param useCommonACR bool = true
param enableAISearch bool = false
param addAISearch bool = false
param enableAIServices bool = false
param enableBingSearch bool = false
param openAiApiVersion string = '2024-06-01'
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'gold'

var standaloneDeploymentSuffix = uniqueString(subscriptionIdDevTestProd, commonRGNamePrefix, aifactorySuffixRG, projectNumber, env, locationSuffix, resourceSuffix)

module deploymentContext '../modules/common/CmnServiceDeploymentContext.bicep' = {
  name: '05b-context-${standaloneDeploymentSuffix}'
  params: {
    deploymentPrefix: '05b'
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
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
  }
}

var context = deploymentContext.outputs.context
var originalSearchName = context.names.safeNameAISearch
var baseSearchName = take(originalSearchName, max(length(originalSearchName) - 3, 0))
var searchSuffix = substring(originalSearchName, max(length(originalSearchName) - 3, 0), min(3, length(originalSearchName)))
var aiSearchName = enableAISearch ? take(addAISearch ? '${baseSearchName}${take(context.names.randomSalt, 2)}${searchSuffix}' : originalSearchName, 60) : ''
var workloadProfileType = env == 'dev' ? skuContainerAppsDev : skuContainerAppsStageProd

module containerApps '../modules/services/containerAppsDeployment.bicep' = if (enableContainerApps) {
  name: '05b-container-apps-${standaloneDeploymentSuffix}'
  params: {
    context: context
    deploymentSuffix: '${context.projectName}${env}${substring(uniqueString(subscription().subscriptionId, context.targetResourceGroup), 0, 5)}'
    location: location
    locationSuffix: locationSuffix
    env: env
    resourceSuffix: resourceSuffix
    tagsProject: tagsProject
    workloadProfileType: workloadProfileType
    containerAppsEnvExists: containerAppsEnvExists
    containerAppAExists: containerAppAExists
    containerAppWExists: containerAppWExists
    updateExistingContainerApps: updateExistingContainerApps
    delegateSubnet: !empty(acaSubnetId) || !empty(aca2SubnetId)
    wlMinCountServerless: wlMinCountServerless
    wlMinCountDedicated: wlMinCountDedicated
    wlMaxCount: wlMaxCount
    wlProfileDedicatedName: wlProfileDedicatedName
    wlProfileGPUConsumptionName: wlProfileGPUConsumptionName
    acaAppWorkloadProfileName: acaAppWorkloadProfileName
    containerCpuCoreCount: containerCpuCoreCount
    containerMemory: containerMemory
    aca_a_registry_image: aca_a_registry_image
    aca_w_registry_image: aca_w_registry_image
    aca_default_image: aca_default_image
    acaCustomDomainsArray: acaCustomDomainsArray
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    IPwhiteList: IPwhiteList
    useCommonACR: useCommonACR
    enableAISearch: enableAISearch
    aiSearchName: aiSearchName
    enableAIServices: enableAIServices
    enableBingSearch: enableBingSearch
    openAiApiVersion: openAiApiVersion
    diagnosticSettingLevel: diagnosticSettingLevel
  }
}

output containerAppsEnvDeployed bool = enableContainerApps && (!containerAppsEnvExists || updateExistingContainerApps)
output containerAppADeployed bool = enableContainerApps && (!containerAppAExists || updateExistingContainerApps)
output containerAppWDeployed bool = enableContainerApps && (!containerAppWExists || updateExistingContainerApps)
output containerAppsEnvName string = context.names.containerAppsEnvName
output containerAppAName string = context.names.containerAppAName
output containerAppWName string = context.names.containerAppWName
output acrRbacVerified bool = enableContainerApps
output acrRbacVerificationCompleted string = enableContainerApps ? 'RBAC verification included in deployment' : 'RBAC verification not required'
output workloadProfileType string = workloadProfileType
