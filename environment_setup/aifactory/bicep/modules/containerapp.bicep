metadata description = 'Creates a container app in an Azure Container App environment.'
param name string
param location string
param tags object

@description('Allowed origins')
param allowedOrigins array = []

@description('Name of the environment for container apps')
param containerAppsEnvironmentName string

@description('CPU cores allocated to a single container instance, e.g., 0.5')
param containerCpuCoreCount string = '0.5'

@description('The maximum number of replicas to run. Must be at least 1.')
@minValue(1)
param containerMaxReplicas int = 10

@description('Memory allocated to a single container instance, e.g., 1Gi')
param containerMemory string = '1.0Gi'

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
param identityUserPrincipalId string = ''

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

// Private registry support requires both an ACR name and a User Assigned managed identity
var usePrivateRegistry = !empty(identityUserPrincipalId) && !empty(containerRegistryName)

// Automatically set to `UserAssigned` when an `identityName` has been set
var normalizedIdentityType = !empty(identityUserPrincipalId) ? 'UserAssigned' : identityType

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnetPend 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetNamePend
  parent: vnet
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' existing = {
  name: containerAppsEnvironmentName
}

resource app 'Microsoft.App/containerApps@2023-05-02-preview' = {
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
      '${identityUserPrincipalId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironment.id
    configuration: {
      activeRevisionsMode: revisionMode
      ingress: ingressEnabled ? {
        external: external
        targetPort: targetPort
        transport: 'auto'
        ipSecurityRestrictions: (!empty(ipSecurityRestrictions) && !enablePublicGenAIAccess)? ipSecurityRestrictions: null
        corsPolicy: {
          maxAge: 3600
          allowCredentials: true
          allowedOrigins: allowedOrigins //union([ 'https://portal.azure.com', 'https://ms.portal.azure.com' ], allowedOrigins)
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
        value: secret.value
      }]
      service: !empty(serviceType) ? { type: serviceType } : null
      registries: usePrivateRegistry ? [
        {
          server: '${containerRegistryName}.${containerRegistryHostSuffix}'
          identity: identityUserPrincipalId
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
            cpu: json(containerCpuCoreCount)
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


resource pendAca 'Microsoft.Network/privateEndpoints@2022-01-01' = {
  name: 'pend-aca-${name}'
  location: location
  properties: {
    subnet: {
      id: subnetPend.id
    }
    privateLinkServiceConnections: [
      {
        name: 'pend-aca-${name}'
        properties: {
          privateLinkServiceId: app.id
          groupIds: [
            'managedEnvironments'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
  
}

output defaultDomain string = containerAppsEnvironment.properties.defaultDomain
output identityPrincipalId string = normalizedIdentityType == 'None' ? '' : (empty(identityUserPrincipalId) ? app.identity.principalId : identityUserPrincipalId)
output imageName string = imageName
output name string = app.name
output serviceBind object = !empty(serviceType) ? { serviceId: app.id, name: name } : {}
output uri string = ingressEnabled ? 'https://${app.properties.configuration.ingress.fqdn}' : ''
output dnsConfig array = [
  {
    name: pendAca.name
    type: 'managedEnvironments'
    id:pendAca.id
  }
]
