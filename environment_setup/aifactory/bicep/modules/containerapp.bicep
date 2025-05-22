metadata description = 'Creates a container app in an Azure Container App environment.'
param name string
param location string
param tags object

@description('Allowed origins')
param allowedOrigins array

@description('Name of the environment for container apps')
param containerAppsEnvironmentName string
@description('ID of the environment for container apps')
param containerAppsEnvironmentId string

@description('CPU cores allocated to a single container instance, e.g., 0.5')
param containerCpuCoreCount int = 1 //0.5
@description('Memory allocated to a single container instance, e.g., 1Gi')
param containerMemory string = '2.0Gi' //'1.0Gi'

@description('The maximum number of replicas to run. Must be at least 1.')
@minValue(1)
param containerMaxReplicas int = 10

@description('The minimum number of replicas to run. Must be at least 1.')
param containerMinReplicas int = 1

@description('The name of the container')
param containerName string = 'main'

@description('The name of the container registry')
param containerRegistryName string

@description('Hostname suffix for container registry. Set when deploying to sovereign clouds')
param containerRegistryHostSuffix string = 'azurecr.io'

@description('The protocol used by Dapr to connect to the app, e.g., http or grpc')
@allowed([ 'http', 'grpc' ])
param daprAppProtocol string = 'http'

@description('The Dapr app ID')
param daprAppId string = containerName

@description('Enable Dapr')
param daprEnabled bool = false

@description('The environment variables for the container')
param env array = []

@description('Specifies if the resource ingress is exposed externally')
param external bool = true

@description('The ID of the user-assigned identity')
param identityName string = ''

@description('The type of identity for the resource')
@allowed([ 'None', 'SystemAssigned', 'UserAssigned' ])
param identityType string = 'None'

@description('The name of the container image')
param imageName string = ''

@description('Specifies if Ingress is enabled for the container app')
param ingressEnabled bool = true

param revisionMode string = 'Single'

@description('The secrets required for the container')
@secure()
param secrets object = {}

@description('The service binds associated with the container')
param serviceBinds array = []

@description('The name of the container apps add-on to use. e.g. redis')
param serviceType string = ''

@description('The target port for the container')
param targetPort int = 80
param customDomains array = []
param ipSecurityRestrictions array = []
param vnetCidr string = ''
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param vnetName string = ''
param vnetResourceGroupName string = ''
param subnetNamePend string = ''
param subnetAcaDedicatedName string = ''
param appWorkloadProfileName string = ''
param keyVaultUrl string = ''

// Private registry support requires both an ACR name and a User Assigned managed identity
var usePrivateRegistry = !empty(identityName) && !empty(containerRegistryName)

// Automatically set to `UserAssigned` when an `identityName` has been set
var normalizedIdentityType = !empty(identityName) ? 'UserAssigned' : identityType

//resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' existing = {
resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: containerAppsEnvironmentName
}

var rId = resourceId('Microsoft.App/managedEnvironments@2023-05-01', containerAppsEnvironmentName)

resource userIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = if (!empty(identityName)) {
  name: identityName
}


//resource app 'Microsoft.App/containerApps@2023-05-02-preview' = {
resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: name
  location: location
  tags: tags
  // It is critical that the identity is granted ACR pull access before the app is created
  // otherwise the container app will throw a provision error
  // This also forces us to use an user assigned managed identity since there would no way to 
  // provide the system assigned identity with the ACR pull access before the app is created
  //dependsOn: usePrivateRegistry ? [ containerRegistryAccess ] : []
  identity: {
    type: normalizedIdentityType
    userAssignedIdentities:{
      '${userIdentity.id}': {}
    }
  }
  properties: {
    //Deprecated: managedEnvironmentId: containerAppsEnvironmentId // containerAppsEnvironment.id
    workloadProfileName: empty(appWorkloadProfileName)? null : appWorkloadProfileName
    environmentId: containerAppsEnvironment.id
    configuration: {
      activeRevisionsMode: revisionMode
      ingress: ingressEnabled ? {
        external: external
        targetPort: targetPort
        allowInsecure: true
        transport: 'auto'
        ipSecurityRestrictions: (!empty(ipSecurityRestrictions) && !enablePublicGenAIAccess)? ipSecurityRestrictions: null
        corsPolicy: {
          maxAge: 3600
          allowCredentials: true
          allowedOrigins: union([ 'https://portal.azure.com', 'https://ms.portal.azure.com' ], allowedOrigins)
          allowedMethods: [ 'GET', 'POST', 'PUT', 'DELETE', 'OPTIONS' ]
          allowedHeaders: [ '*' ]
          exposeHeaders: [ '*' ]
        }
        customDomains: !empty(customDomains) ? customDomains : null
      } : null
      dapr: daprEnabled ? {
        enabled: true
        appId: daprAppId
        appProtocol: daprAppProtocol
        appPort: ingressEnabled ? targetPort : 0
      } : { enabled: false }
      secrets: [for secret in items(secrets): {
        name: secret.key
        #disable-next-line use-secure-value-for-secure-inputs
        value: secret.value
        //identity: userIdentity.id
        //keyVaultUrl: '${keyVaultUrl}secrets/aifactory-proj-${secret.key}'
      }]
      service: !empty(serviceType) ? { type: serviceType } : null
      registries: usePrivateRegistry ? [
        {
          server: '${containerRegistryName}.${containerRegistryHostSuffix}'
          identity: userIdentity.id
        }
      ] : []
    }
    template: {
      serviceBinds: !empty(serviceBinds) ? serviceBinds : null
      containers: [
        {
          image: !empty(imageName) ? imageName : 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          name: containerName
          env: env
          resources: {
            cpu: containerCpuCoreCount //json(containerCpuCoreCount)
            memory: containerMemory
          }
        }
      ]
      scale: {
        minReplicas: containerMinReplicas
        maxReplicas: containerMaxReplicas
      }
    }
  }
}


output defaultDomain string = containerAppsEnvironment.properties.defaultDomain
output identityPrincipalId string = normalizedIdentityType == 'None' ? '' : (empty(identityName) ? app.identity.principalId : userIdentity.properties.principalId)
output imageName string = imageName
output name string = app.name
output serviceBind object = !empty(serviceType) ? { serviceId: app.id, name: name } : {}
output uri string = ingressEnabled ? 'https://${app.properties.configuration.ingress.fqdn}' : ''
