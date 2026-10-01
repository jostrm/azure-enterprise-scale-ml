targetScope = 'subscription'

param context object
param deploymentSuffix string
param aiSearchName string
param location string
param aiSearchLocation string = ''
param skuName string
param tagsProject object = {}
param aiSearchExists bool = false
param enableAISearchSharedPrivateLink bool = true
param enableAIServices bool = true
param aiSearchReplicaCount int = 1
param aiSearchPartitionCount int = 1
@allowed(['disabled', 'free', 'standard'])
param semanticSearchTier string = 'free'
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param IPwhiteList string = ''
param centralDnsZoneByPolicyInHub bool = false
param skipDiagAISearch bool = true
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'gold'
param cmk bool = false
param cmkDisableForAISearch bool = false
param cmkKeyName string = ''
param admin_bicep_kv_fw string = ''
param admin_bicep_kv_fw_rg string = ''
param admin_bicep_input_keyvault_subscription string = ''

var cmkForAISearch = cmk && !cmkDisableForAISearch
var cmkIdentityId = resourceId(context.subscriptionId, context.targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', context.names.miPrjName)
var sharedPrivateLinks = enableAISearchSharedPrivateLink ? [
  {
    privateLinkResourceId: resourceId(context.subscriptionId, context.targetResourceGroup, 'Microsoft.Storage/storageAccounts', context.names.storageAccount2001Name)
    groupId: 'blob'
    requestMessage: 'AI Search shared private link to blob storage'
    resourceRegion: location
  }
] : []

module aiSearchService '../aiSearch.bicep' = {
  name: take('03-AzureAISearch4${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    aiSearchName: aiSearchName
    location: empty(aiSearchLocation) ? location : aiSearchLocation
    privateEndpointLocation: location
    replicaCount: aiSearchReplicaCount
    partitionCount: aiSearchPartitionCount
    privateEndpointName: '${aiSearchName}-pend'
    vnetName: context.vnetName
    vnetResourceGroupName: context.vnetResourceGroupName
    subnetName: context.names.defaultSubnet
    tags: tagsProject
    semanticSearchTier: semanticSearchTier
    publicNetworkAccess: enablePublicGenAIAccess
    skuName: skuName
    enableSharedPrivateLink: !empty(sharedPrivateLinks)
    sharedPrivateLinks: sharedPrivateLinks
    approveStorageSharedLinks: false
    storageAccountNameForSharedLinks: enableAISearchSharedPrivateLink ? context.names.storageAccount2001Name : ''
    approveAiServicesSharedLink: false
    aiServicesNameForSharedLink: (enableAISearchSharedPrivateLink && enableAIServices) ? context.names.aiServicesName : ''
    ipRules: [for ip in (!empty(IPwhiteList) ? split(IPwhiteList, ',') : []): {
      action: 'Allow'
      value: trim(ip)
    }]
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: union(
        !empty(context.names.miPrjName) ? [cmkIdentityId] : [],
        !empty(context.names.miACAName) ? [resourceId(context.subscriptionId, context.targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', context.names.miACAName)] : []
      )
    }
    cmk: cmkForAISearch
    cmkKeyName: cmkForAISearch ? cmkKeyName : ''
    cmkKeyVaultUri: cmkForAISearch ? 'https://${admin_bicep_kv_fw}${environment().suffixes.keyvaultDns}/' : ''
    cmkIdentityId: cmkForAISearch ? cmkIdentityId : ''
  }
}

#disable-next-line BCP073
module aiSearchCmkRbac '../kvRbacSingleAssignment.bicep' = if (!aiSearchExists && cmkForAISearch) {
  name: take('03-aiSearchCmkRbac-${deploymentSuffix}', 64)
  scope: resourceGroup(admin_bicep_input_keyvault_subscription, admin_bicep_kv_fw_rg)
  params: {
    keyVaultName: admin_bicep_kv_fw
    principalId: aiSearchService.outputs.principalId
    keyVaultRoleId: 'e147488a-f6f5-4113-8e2d-b22465e65bf6'
    assignmentName: 'cmk-rbac-aisearch-${aiSearchName}'
    principalType: 'ServicePrincipal'
  }
}

module privateDns '../privateDns.bicep' = if (!aiSearchExists && !centralDnsZoneByPolicyInHub) {
  name: take('03-privDnsAISearch${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    dnsConfig: !empty(aiSearchService.outputs.dnsConfig[0].name) ? aiSearchService.outputs.dnsConfig : []
    privateLinksDnsZones: context.privateLinksDnsZones
  }
}

module diagnostics '../diagnostics/aiSearchDiagnostics.bicep' = if (!skipDiagAISearch) {
  name: take('03-diagAISearch-${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    searchServiceName: aiSearchName
    logAnalyticsWorkspaceId: resourceId(context.subscriptionId, context.commonResourceGroup, 'Microsoft.OperationalInsights/workspaces', context.names.laWorkspaceName)
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    aiSearchService
  ]
}

output name string = aiSearchName
output principalId string = aiSearchService.outputs.principalId
output dnsConfig array = aiSearchService.outputs.dnsConfig
