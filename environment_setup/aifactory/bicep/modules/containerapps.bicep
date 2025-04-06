metadata description = 'Creates an Azure Container Registry and an Azure Container Apps environment.'
param name string
param location string
param tags object
param vnetName string
param vnetResourceGroupName string
param subnetNamePend string
param subnetAcaDedicatedName string
param logAnalyticsWorkspaceName string
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param containerRegistryAdminUserEnabled bool = false
param applicationInsightsName string = ''

module containerAppsEnvironment 'containerappsEnv.bicep' = {
  name: 'depl-${name}-${deployment().name}'
  params: {
    name: name
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

