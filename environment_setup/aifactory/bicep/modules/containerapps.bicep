metadata description = 'Creates an Azure Container Registry and an Azure Container Apps environment.'
param name string
param location string
param tags object

param containerAppsEnvironmentName string
param containerRegistryName string
param vnetName string
param vnetResourceGroupName string
param subnetNamePend string
param subnetAcaDedicatedName string
param logAnalyticsWorkspaceName string
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param containerRegistryAdminUserEnabled bool = false
param applicationInsightsName string = ''
param containerRegistryResourceGroupName string = ''

module containerAppsEnvironment 'containerappsEnv.bicep' = {
  name: 'aca-env-${name}-${deployment().name}-depl'
  params: {
    name: containerAppsEnvironmentName
    location: location
    tags: tags
    logAnalyticsWorkspaceName: logAnalyticsWorkspaceName
    applicationInsightsName: applicationInsightsName
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: vnetName
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: subnetNamePend
    subnetAcaDedicatedName: subnetAcaDedicatedName
  }
}

output defaultDomain string = containerAppsEnvironment.outputs.defaultDomain
output environmentName string = containerAppsEnvironment.outputs.name
output environmentId string = containerAppsEnvironment.outputs.id

