metadata description = 'Creates or updates an existing Azure Container App.'
param name string
param location string
param tags object

@description('The environment name for the container apps')
param containerAppsEnvironmentName string
param containerAppsEnvironmentId string

@description('CPU cores allocated to a single container instance, e.g., 0.5')
param containerCpuCoreCount int = 1 //0.5
@description('Memory allocated to a single container instance, e.g., 1Gi')
param containerMemory string = '2.0Gi' //'1.0Gi'
param wlMinCountServerless int = 0
param wlMinCountDedicated int = 1
param wlMaxCount int = 5

@description('The maximum number of replicas to run. Must be at least 1.')
@minValue(1)
param containerMaxReplicas int = 10

@description('The minimum number of replicas to run. Must be at least 1.')
@minValue(1)
param containerMinReplicas int = 1

@description('The name of the container')
param containerName string = 'main'

@description('The name of the container registry')
param containerRegistryName string

@description('Hostname suffix for container registry. Set when deploying to sovereign clouds')
param containerRegistryHostSuffix string = 'azurecr.io'

@allowed([ 'http', 'grpc' ])
@description('The protocol used by Dapr to connect to the app, e.g., HTTP or gRPC')
param daprAppProtocol string = 'http'

@description('Enable or disable Dapr for the container app')
param daprEnabled bool = false

@description('The Dapr app ID')
param daprAppId string = containerName

@description('Specifies if Ingress is enabled for the container app')
param ingressEnabled bool = true

@description('The type of identity for the resource')
@allowed([ 'None', 'SystemAssigned', 'UserAssigned' ])
param identityType string = 'None'

@description('The ID of the user-assigned identity')
param identityUserPrincipalId string = ''

// ############## NB! 
@description('The secrets required for the container')
@secure()
param secrets object = {}

@description('The environment variables for the container')
param env array = []

// ############## NB! 

@description('Specifies if the resource ingress is exposed externally')
param external bool = true

@description('The service binds associated with the container')
param serviceBinds array = []

@description('The target port for the container')
param targetPort int = 80
param allowedOrigins array = []
param imageName string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param customDomains array = []
param ipSecurityRestrictions array = []
param enablePublicGenAIAccess bool = false
@description('Enable public access with network perimeter security')
param enablePublicAccessWithPerimeter bool = false

@description('Name of the virtual network')
param vnetName string = ''

@description('Resource group name containing the virtual network')
param vnetResourceGroupName string = ''

@description('Subnet name for the private endpoints')
param subnetNamePend string = ''

@description('Subnet name for the dedicated container apps subnet')
param subnetAcaDedicatedName string = ''
param appWorkloadProfileName string = ''

module appUpsert 'containerapp.bicep' = {
  name: 'depl-${name}-2'
  params: {
    name: name
    location: location
    tags: tags
    enablePublicGenAIAccess: enablePublicGenAIAccess
    ipSecurityRestrictions: ipSecurityRestrictions
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: vnetName
    vnetResourceGroupName: vnetResourceGroupName
    subnetNamePend: subnetNamePend
    subnetAcaDedicatedName: subnetAcaDedicatedName
    identityType: identityType
    identityUserPrincipalId:identityUserPrincipalId
    ingressEnabled: ingressEnabled
    containerName: containerName
    containerAppsEnvironmentName: containerAppsEnvironmentName
    containerAppsEnvironmentId: containerAppsEnvironmentId
    containerRegistryName: containerRegistryName
    containerRegistryHostSuffix: containerRegistryHostSuffix
    containerCpuCoreCount: containerCpuCoreCount
    containerMemory: containerMemory
    containerMinReplicas: containerMinReplicas
    containerMaxReplicas: containerMaxReplicas
    daprEnabled: daprEnabled
    daprAppId: daprAppId
    daprAppProtocol: daprAppProtocol
    secrets: secrets
    allowedOrigins:allowedOrigins
    external: external
    env: env
    imageName: imageName
    targetPort: targetPort
    serviceBinds: serviceBinds
    customDomains: customDomains
    appWorkloadProfileName: appWorkloadProfileName

  }
}

output defaultDomain string = appUpsert.outputs.defaultDomain
output imageName string = appUpsert.outputs.imageName
output name string = appUpsert.outputs.name
output uri string = appUpsert.outputs.uri
