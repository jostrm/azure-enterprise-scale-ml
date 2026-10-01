targetScope = 'subscription'

param context object
param deploymentSuffix string
param location string
param locationSuffix string
param env string
param resourceSuffix string
param tagsProject object = {}
@allowed(['Consumption', 'D4', 'D8'])
param workloadProfileType string = 'Consumption'
param containerAppsEnvExists bool = false
param containerAppAExists bool = false
param containerAppWExists bool = false
param updateExistingContainerApps bool = false
param delegateSubnet bool = true
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
param centralDnsZoneByPolicyInHub bool = false
param IPwhiteList string = ''
param useCommonACR bool = true
param enableAISearch bool = false
param aiSearchName string = ''
param enableAIServices bool = false
param enableBingSearch bool = false
param openAiApiVersion string = '2024-06-01'
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'gold'

var deployEnvironment = !containerAppsEnvExists || updateExistingContainerApps
var deployApi = !containerAppAExists || updateExistingContainerApps
var deployWeb = !containerAppWExists || updateExistingContainerApps
var acaSubnetName = !empty(context.names.acaSubnetName) ? context.names.acaSubnetName : context.names.aca2SubnetName
var appWorkloadProfileName = workloadProfileType == 'Consumption'
  ? (toLower(acaAppWorkloadProfileName) == 'consumption' ? 'Consumption' : acaAppWorkloadProfileName)
  : 'aifactory-dedicated'
var containerRegistryName = useCommonACR ? context.names.acrCommonName : context.names.acrProjectName
var aiServicesName = enableAIServices ? context.names.aiServicesName : ''
var ipSecurityRestrictions = [for ip in (!empty(IPwhiteList) ? split(IPwhiteList, ',') : []): {
  name: replace(replace(ip, ',', ''), '/', '_')
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
var imageRegistryTypeA = contains(aca_a_registry_image, 'mcr.microsoft.com') ? 'ms' : contains(aca_a_registry_image, 'docker.io') ? 'dockerhub' : 'private'
var imageRegistryTypeW = contains(aca_w_registry_image, 'mcr.microsoft.com') ? 'ms' : contains(aca_w_registry_image, 'docker.io') ? 'dockerhub' : 'private'

module getACAMIPrincipalId '../get-managed-identity-info.bicep' = {
  name: take('03-getACAMI-${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    managedIdentityName: context.names.miACAName
  }
}

module subnetDelegation '../subnetDelegation.bicep' = if (deployEnvironment && delegateSubnet) {
  name: take('05-snetDelegACA${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.vnetResourceGroupName)
  params: {
    vnetName: context.vnetName
    subnetName: acaSubnetName
    location: location
    vnetResourceGroupName: context.vnetResourceGroupName
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

module containerAppsEnv '../containerapps.bicep' = if (deployEnvironment) {
  name: take('05-aca-env-${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    name: context.names.containerAppsEnvName
    location: location
    tags: tagsProject
    logAnalyticsWorkspaceName: context.names.laWorkspaceName
    logAnalyticsWorkspaceRG: context.commonResourceGroup
    applicationInsightsName: context.names.applicationInsightName
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: context.vnetName
    vnetResourceGroupName: context.vnetResourceGroupName
    subnetNamePend: context.names.defaultSubnet
    subnetAcaDedicatedName: acaSubnetName
    wlMinCountServerless: wlMinCountServerless
    wlMinCountDedicated: wlMinCountDedicated
    wlMaxCount: wlMaxCount
    wlProfileDedicatedName: wlProfileDedicatedName
    wlProfileGPUConsumptionName: wlProfileGPUConsumptionName
    workloadProfileType: workloadProfileType
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: concat(
        !empty(context.names.miPrjName) ? [resourceId(context.subscriptionId, context.targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', context.names.miPrjName)] : [],
        !empty(context.names.miACAName) ? [resourceId(context.subscriptionId, context.targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', context.names.miACAName)] : []
      )
    }
  }
  dependsOn: [
    subnetDelegation
  ]
}

module privateDns '../privateDns.bicep' = if (deployEnvironment && !centralDnsZoneByPolicyInHub && !enablePublicAccessWithPerimeter) {
  name: take('05-privDnsACAEnv${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    dnsConfig: containerAppsEnv!.outputs.dnsConfig
    privateLinksDnsZones: context.privateLinksDnsZones
  }
}

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: context.commonResourceGroup
  scope: subscription(context.subscriptionId)
}
resource targetResourceGroupRef 'Microsoft.Resources/resourceGroups@2025-04-01' existing = {
  name: context.targetResourceGroup
  scope: subscription(context.subscriptionId)
}

var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)
#disable-next-line BCP081
resource bingREF 'Microsoft.Bing/accounts@2020-06-10' existing = if (enableBingSearch) {
  name: 'bing-${context.projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
}

module acaApi '../containerappApi.bicep' = if (deployApi) {
  name: take('05-aca-a-${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    name: context.names.containerAppAName
    location: location
    tags: tagsProject
    ipSecurityRestrictions: enablePublicGenAIAccess ? ipSecurityRestrictions : []
    allowedOrigins: allowedOrigins
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: context.vnetName
    vnetResourceGroupName: context.vnetResourceGroupName
    subnetNamePend: context.names.defaultSubnet
    subnetAcaDedicatedName: acaSubnetName
    customDomains: acaCustomDomainsArray
    resourceGroupName: context.targetResourceGroup
    identityId: getACAMIPrincipalId.outputs.principalId
    identityName: context.names.miACAName
    containerRegistryName: containerRegistryName
    containerAppsEnvironmentName: context.names.containerAppsEnvName
    containerAppsEnvironmentId: resourceId(context.subscriptionId, context.targetResourceGroup, 'Microsoft.App/managedEnvironments', context.names.containerAppsEnvName)
    openAiDeploymentName: 'gpt'
    openAiEvalDeploymentName: 'gpt-evals'
    openAiEmbeddingDeploymentName: 'text-embedding-ada-002'
    openAiEndpoint: 'https://${aiServicesName}.cognitiveservices.azure.com/'
    openAiName: aiServicesName
    openAiType: 'azure'
    openAiApiVersion: openAiApiVersion
    aiSearchEndpoint: 'https://${aiSearchName}.search.windows.net'
    aiSearchIndexName: 'index-${context.projectName}-${resourceSuffix}'
    appinsightsConnectionstring: 'InstrumentationKey=${context.names.applicationInsightName}'
    bingName: context.names.bingName
    bingApiEndpoint: 'https://api.bing.microsoft.com/v7.0/search'
    #disable-next-line BCP318 BCP422
    bingApiKey: enableBingSearch ? bingREF.listKeys().key1 : 'BCP318'
    aiProjectName: context.names.aifV1ProjectName
    subscriptionId: context.subscriptionId
    appWorkloadProfileName: appWorkloadProfileName
    containerCpuCoreCount: containerCpuCoreCount
    containerMemory: containerMemory
    keyVaultUrl: 'https://${context.names.keyvaultName}.${environment().suffixes.keyvaultDns}'
    imageName: !empty(aca_a_registry_image) ? aca_a_registry_image : aca_default_image
    imageRegistryType: !empty(aca_a_registry_image) ? imageRegistryTypeA : 'ms'
  }
  dependsOn: [
    containerAppsEnv
  ]
}

resource existingApi 'Microsoft.App/containerApps@2025-01-01' existing = if (!deployApi) {
  name: context.names.containerAppAName
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
}

module acaWebApp '../containerappWeb.bicep' = if (deployWeb) {
  name: take('05-aca-w-${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    location: location
    tags: tagsProject
    name: context.names.containerAppWName
    apiEndpoint: deployApi ? acaApi!.outputs.SERVICE_ACA_URI : 'https://${existingApi!.properties.configuration.ingress.fqdn}'
    allowedOrigins: allowedOrigins
    containerAppsEnvironmentName: context.names.containerAppsEnvName
    containerAppsEnvironmentId: resourceId(context.subscriptionId, context.targetResourceGroup, 'Microsoft.App/managedEnvironments', context.names.containerAppsEnvName)
    containerRegistryName: containerRegistryName
    identityId: getACAMIPrincipalId.outputs.principalId
    identityName: context.names.miACAName
    appWorkloadProfileName: appWorkloadProfileName
    containerCpuCoreCount: containerCpuCoreCount
    containerMemory: containerMemory
    keyVaultUrl: 'https://${context.names.keyvaultName}.${environment().suffixes.keyvaultDns}'
    imageName: !empty(aca_w_registry_image) ? aca_w_registry_image : aca_default_image
    imageRegistryType: !empty(aca_w_registry_image) ? imageRegistryTypeW : 'ms'
  }
  dependsOn: [
    containerAppsEnv
  ]
}

module rbac '../containerappRbac.bicep' = {
  name: take('05rbacACAMI${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    aiSearchName: enableAISearch ? aiSearchName : ''
    appInsightsName: context.names.applicationInsightName
    principalIdMI: getACAMIPrincipalId.outputs.principalId
    resourceGroupId: targetResourceGroupRef.id
  }
  dependsOn: [
    containerAppsEnv
    acaApi
  ]
}

module apiDiagnostics '../diagnostics/containerAppsDiagnostics.bicep' = if (deployApi) {
  name: take('05-diagContainerAppAPI-${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    containerAppName: context.names.containerAppAName
    logAnalyticsWorkspaceId: resourceId(context.subscriptionId, context.commonResourceGroup, 'Microsoft.OperationalInsights/workspaces', context.names.laWorkspaceName)
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    acaApi
  ]
}

module webDiagnostics '../diagnostics/containerAppsDiagnostics.bicep' = if (deployWeb) {
  name: take('05-diagContainerAppWeb-${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    containerAppName: context.names.containerAppWName
    logAnalyticsWorkspaceId: resourceId(context.subscriptionId, context.commonResourceGroup, 'Microsoft.OperationalInsights/workspaces', context.names.laWorkspaceName)
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    acaWebApp
  ]
}

output containerAppsEnvDeployed bool = deployEnvironment
output containerAppADeployed bool = deployApi
output containerAppWDeployed bool = deployWeb
output appWorkloadProfileName string = appWorkloadProfileName
