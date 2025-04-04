param name string
param location string
param resourceGroupName string
param tags object
param identityUserPrincipalId string
param identityId string
param containerAppsEnvironmentName string
param containerRegistryName string
param serviceName string = 'api'
param openAiDeploymentName string
param openAiEvalDeploymentName string
param openAiEndpoint string
param openAiName string
param bingName string
param openAiApiVersion string
param openAiEmbeddingDeploymentName string
param openAiType string
param aiSearchEndpoint string
param aiSearchIndexName string
param appinsightsConnectionstring string
param aiProjectName string
param subscriptionId string
param targetPort int = 80
param customDomains array = []
param ipSecurityRestrictions array = []
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param vnetName string = ''
param vnetResourceGroupName string = ''
param subnetNamePend string = ''
param subnetAcaDedicatedName string = ''

@secure()
param bingApiKey string
param bingApiEndpoint string
param allowedOrigins array = []

module appApi './containerappUpsert.bicep' = {
  name: 'depl-${name}-${deployment().name}'
  params: {
    name: name
    location: location
    tags: union(tags, { 'azd-service-name': serviceName })
    identityUserPrincipalId: identityUserPrincipalId
    identityType: 'UserAssigned'
    containerAppsEnvironmentName: containerAppsEnvironmentName
    containerRegistryName: containerRegistryName
    customDomains:customDomains
    ipSecurityRestrictions: ipSecurityRestrictions
    enablePublicGenAIAccess:enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: vnetName
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: subnetNamePend
    subnetAcaDedicatedName: subnetAcaDedicatedName
    allowedOrigins: allowedOrigins
    secrets: {
      'bing-search-key': bingApiKey
    }
    env: [
      {
        name: 'AZURE_LOCATION'
        value: location
      }
      {
        name: 'AZURE_RESOURCE_GROUP'
        value: resourceGroupName
      }
      {
        name: 'AZURE_SUBSCRIPTION_ID'
        value: subscriptionId
      }
      {
        name: 'AZURE_CLIENT_ID'
        value: identityId
      }
      {
        name: 'AZURE_SEARCH_ENDPOINT'
        value: aiSearchEndpoint
      }
      {
        name: 'AZUREAISEARCH__INDEX_NAME'
        value: aiSearchIndexName
      }
      {
        name: 'OPENAI_TYPE'
        value: openAiType
      }
      {
        name: 'AZURE_OPENAI_API_VERSION'
        value: openAiApiVersion
      }
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: openAiEndpoint
      }
      {
        name: 'AZURE_OPENAI_NAME'
        value: openAiName
      }
      {
        name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
        value: openAiDeploymentName
      }
      {
        name: 'AZURE_OPENAI_4_EVAL_DEPLOYMENT_NAME'
        value: openAiEvalDeploymentName
      }
      {
        name: 'AZURE_AI_PROJECT_NAME'
        value: aiProjectName
      }
      {
        name: 'AZURE_EMBEDDING_NAME'
        value: openAiEmbeddingDeploymentName
      }
      {
        name: 'appinsightsConnectionstring'
        value: appinsightsConnectionstring
      }
      {
        name: 'BING_SEARCH_ENDPOINT'
        value: bingApiEndpoint
      }
      {
        name: 'BING_SEARCH_KEY'
        secretRef: 'bing-search-key'
      }
      {
        name: 'BING_SEARCH_NAME'
        value: bingName
      }
    ]
    targetPort: targetPort
  }
}

output SERVICE_ACA_NAME string = appApi.outputs.name
output SERVICE_ACA_URI string = appApi.outputs.uri
output SERVICE_ACA_IMAGE_NAME string = appApi.outputs.imageName
