param name string
param location string
param tags object
param identityName string
param identityId string
param containerAppsEnvironmentName string
param containerAppsEnvironmentId string
param containerRegistryName string
param serviceName string = 'web'
param apiEndpoint string
param targetPort int = 80
param appWorkloadProfileName string = ''
@description('CPU cores allocated to a single container instance, e.g., 0.5')
param containerCpuCoreCount int = 1 //0.5
@description('Memory allocated to a single container instance, e.g., 1Gi')
param containerMemory string = '2.0Gi' //'1.0Gi'
param keyVaultUrl string = ''

module app './containerappUpsert.bicep' = {
  name: 'depl-${name}-${deployment().name}'
  params: {
    name: name
    location: location
    tags: union(tags, { 'azd-service-name': serviceName })
    identityName: identityName
    identityType: 'UserAssigned'
    containerAppsEnvironmentName: containerAppsEnvironmentName
    containerAppsEnvironmentId: containerAppsEnvironmentId
    containerRegistryName: containerRegistryName
    appWorkloadProfileName: appWorkloadProfileName
    containerCpuCoreCount: containerCpuCoreCount
    containerMemory: containerMemory
    keyVaultUrl: keyVaultUrl
    env: [
      {
        name: 'AZURE_CLIENT_ID'
        value: identityId
      }
      {
        name: 'API_ENDPOINT'
        value: apiEndpoint
      }
    ]
    targetPort: targetPort
  }
}

output SERVICE_ACA_NAME string = app.outputs.name
output SERVICE_ACA_URI string = app.outputs.uri
output SERVICE_ACA_IMAGE_NAME string = app.outputs.imageName
