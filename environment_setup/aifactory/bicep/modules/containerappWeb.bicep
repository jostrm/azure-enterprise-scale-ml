param name string
param location string
param tags object

param identityUserPrincipalId string
param identityId string
param containerAppsEnvironmentName string
param containerRegistryName string
param serviceName string = 'web'
param apiEndpoint string
param targetPort int = 80

module app './containerappUpsert.bicep' = {
  name: 'depl-${name}-${deployment().name}'
  params: {
    name: name
    location: location
    tags: union(tags, { 'azd-service-name': serviceName })
    identityUserPrincipalId: identityUserPrincipalId
    identityType: 'UserAssigned'
    containerAppsEnvironmentName: containerAppsEnvironmentName
    containerRegistryName: containerRegistryName
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
