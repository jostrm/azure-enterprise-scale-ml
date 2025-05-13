metadata description = 'Creates an Azure Container Registry and an Azure Container Apps environment.'
param name string
param location string
param tags object
param vnetName string
param vnetResourceGroupName string
param subnetNamePend string
param subnetAcaDedicatedName string
param logAnalyticsWorkspaceName string
param logAnalyticsWorkspaceRG string
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param containerRegistryAdminUserEnabled bool = false
param applicationInsightsName string
param wlMinCountServerless int = 0
param wlMinCountDedicated int = 1
param wlMaxCount int = 5
param wlProfileDedicatedName string = 'D4' // 'D4', 'D8', 'D16', 'D32', 'D64', 'E4', 'E8'
param wlProfileGPUConsumptionName string = 'Consumption-GPU-NC24-A100'

module containerAppsEnvironment 'containerappsEnv.bicep' = {
  name: 'depl-${name}'
  params: {
    name: name
    location: location
    tags: tags
    logAnalyticsWorkspaceName: logAnalyticsWorkspaceName
    logAnalyticsWorkspaceRG: logAnalyticsWorkspaceRG
    applicationInsightsName: applicationInsightsName
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    createPrivateEndpoint: enablePublicAccessWithPerimeter?false:true
    vnetName: vnetName
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: subnetNamePend
    subnetAcaDedicatedName: subnetAcaDedicatedName
    wlMinCountServerless: wlMinCountServerless
    wlMinCountDedicated: wlMinCountDedicated
    wlMaxCount: wlMaxCount
    wlProfileDedicatedName: wlProfileDedicatedName
    wlProfileGPUConsumptionName: wlProfileGPUConsumptionName
  }
}

output defaultDomain string = containerAppsEnvironment.outputs.defaultDomain
output environmentName string = containerAppsEnvironment.outputs.name
output environmentId string = containerAppsEnvironment.outputs.id
output dnsConfig array = containerAppsEnvironment.outputs.dnsConfig

