targetScope = 'subscription'

@description('Internal: resolve the exact v1.24 naming context without provisioning Search.')
param contextOnly bool = false
@allowed(['dev', 'test', 'prod'])
param env string
param projectNumber string
param location string
param aiSearchLocation string = ''
param locationSuffix string
param commonResourceSuffix string
param resourceSuffix string
param randomValue string
param aifactorySalt10char string
param aifactorySuffixRG string
param commonRGNamePrefix string = ''
param commonResourceName string = 'esml-common'
param commonResourceGroup_param string = ''
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'
param resolvedManagedIdentityNames object = {}
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string
param aca2SubnetId string = ''
param aks2SubnetId string = ''
param addAISearch bool = false
param tagsProject object = {}
param skuAISearchDev string = 'standard'
param skuAISearchStageProd string = 'standard'
@allowed(['disabled', 'free', 'standard'])
param semanticSearchTier string = 'free'
param aiSearchReplicaCount int = 1
param aiSearchPartitionCount int = 1
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param IPwhiteList string = ''
param cmk bool = false
param cmkDisableForAISearch bool = false

var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('03b-search-naming-${targetResourceGroup}', 64)
  scope: resourceGroup(commonResourceGroup)
  params: {
    resolvedManagedIdentityNames: resolvedManagedIdentityNames
    env: env
    projectNumber: projectNumber
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    aifactorySalt10char: aifactorySalt10char
    randomValue: randomValue
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    commonResourceGroupName: commonResourceGroup
    subscriptionIdDevTestProd: subscription().subscriptionId
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
    aca2SubnetId: aca2SubnetId
    aks2SubnetId: aks2SubnetId
  }
}

// Preserve the cognitive batch's historical addAISearch naming, including salt handling.
var originalName = namingConvention.outputs.safeNameAISearch
var nameBase = take(originalName, max(length(originalName) - 3, 0))
var nameSuffix = substring(originalName, max(length(originalName) - 3, 0), min(3, length(originalName)))
var cleanRandomValue = take(namingConvention.outputs.randomSalt, 2)
var searchName = take(addAISearch ? '${nameBase}${cleanRandomValue}${nameSuffix}' : originalName, 60)
var searchLocation = empty(aiSearchLocation) ? location : aiSearchLocation
var searchSku = env == 'dev' ? skuAISearchDev : skuAISearchStageProd
var miPrjName = namingConvention.outputs.miPrjName
var miACAName = namingConvention.outputs.miACAName

module search '../modules/aiSearch.bicep' = if (!contextOnly) {
  name: take('03b-search-service-${targetResourceGroup}', 64)
  scope: resourceGroup(targetResourceGroup)
  params: {
    aiSearchName: searchName
    location: searchLocation
    privateEndpointLocation: location
    serviceOnly: true
    skuName: searchSku
    semanticSearchTier: semanticSearchTier
    replicaCount: aiSearchReplicaCount
    partitionCount: aiSearchPartitionCount
    tags: tagsProject
    publicNetworkAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    ipRules: [for ip in (!empty(IPwhiteList) ? split(IPwhiteList, ',') : []): {
      action: 'Allow'
      value: trim(ip)
    }]
    cmk: cmk && !cmkDisableForAISearch
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: union(
        !empty(miPrjName) ? [resourceId(targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)] : [],
        !empty(miACAName) ? [resourceId(targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miACAName)] : []
      )
    }
    // Unused in serviceOnly mode; networking remains in task 63 with its original dependencies.
    enableSharedPrivateLink: false
    privateEndpointName: '${searchName}-pend'
    subnetName: ''
    vnetName: ''
    vnetResourceGroupName: targetResourceGroup
  }
}

output aiSearchName string = searchName
output aiSearchResourceId string = resourceId(targetResourceGroup, 'Microsoft.Search/searchServices', searchName)
output targetResourceGroup string = targetResourceGroup
output effectiveAiSearchLocation string = searchLocation
output effectiveAiSearchSku string = searchSku
