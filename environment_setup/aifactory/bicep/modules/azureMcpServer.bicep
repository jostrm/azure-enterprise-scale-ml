targetScope = 'resourceGroup'

metadata description = 'Private, Entra-authenticated Azure MCP inventory server with a dedicated project-scoped identity.'

@export()
type inventoryTool = 'group_resource_list'

func isSubnetResourceId(id string) bool => !contains([
  length(split(id, '/')) == 11
  split(toLower(id), '/')[?0] == ''
  split(toLower(id), '/')[?1] == 'subscriptions'
  !empty(split(id, '/')[?2])
  split(toLower(id), '/')[?3] == 'resourcegroups'
  !empty(split(id, '/')[?4])
  split(toLower(id), '/')[?5] == 'providers'
  split(toLower(id), '/')[?6] == 'microsoft.network'
  split(toLower(id), '/')[?7] == 'virtualnetworks'
  !empty(split(id, '/')[?8])
  split(toLower(id), '/')[?9] == 'subnets'
  !empty(split(id, '/')[?10])
], false)

@export()
func requireInfrastructureSubnetId(id string) string => isSubnetResourceId(id)
  ? id
  : fail('infrastructureSubnetId must be a complete existing Microsoft.Network/virtualNetworks/subnets resource ID.')

@export()
func requirePrivateEndpointSubnetId(id string, infrastructureId string) string => isSubnetResourceId(id) && toLower(id) != toLower(infrastructureId)
  ? id
  : fail('privateEndpointSubnetId must be a complete subnet resource ID different from infrastructureSubnetId (case-insensitive).')

func isSha256Digest(digest string) bool => length(digest) == 64 && empty(filter(range(0, length(digest)), i => !contains('0123456789abcdef', substring(digest, i, 1))))

@export()
func requirePinnedAzureMcpImage(image string) string => image == 'mcr.microsoft.com/azure-sdk/azure-mcp@sha256:${last(split(image, '@sha256:'))}' && isSha256Digest(last(split(image, '@sha256:')))
  ? image
  : fail('containerImage must be mcr.microsoft.com/azure-sdk/azure-mcp@sha256: followed by exactly 64 lowercase hexadecimal characters; tags are not accepted.')

@export()
func requirePrivateDnsZoneResourceId(id string) string => !contains([
  length(split(id, '/')) == 9
  split(toLower(id), '/')[?0] == ''
  split(toLower(id), '/')[?1] == 'subscriptions'
  !empty(split(id, '/')[?2])
  split(toLower(id), '/')[?3] == 'resourcegroups'
  !empty(split(id, '/')[?4])
  split(toLower(id), '/')[?5] == 'providers'
  split(toLower(id), '/')[?6] == 'microsoft.network'
  split(toLower(id), '/')[?7] == 'privatednszones'
  !empty(split(id, '/')[?8])
], false)
  ? id
  : fail('privateDnsZoneResourceId must be a complete existing Microsoft.Network/privateDnsZones resource ID.')

@description('Azure region of both existing subnets and the new Container Apps environment.')
@minLength(1)
param location string = resourceGroup().location

@description('Container app name: lowercase letters, numbers and hyphens; start with a letter and end with an alphanumeric character.')
@minLength(2)
@maxLength(32)
param name string

@description('Existing, unused ACA infrastructure subnet, delegated to Microsoft.App/environments, at least /27. Never use the Foundry or PE subnet.')
param infrastructureSubnetId string

@description('Existing nondelegated private-endpoint subnet (for example the project genai PE subnet), distinct from the ACA subnet.')
param privateEndpointSubnetId string

@description('Tenant of the existing single-tenant Entra API application.')
@minLength(36)
@maxLength(36)
param tenantId string

@description('Existing Entra API application client ID, not a managed identity client ID. Inbound callers need the configured MCP scope or app role.')
@minLength(36)
@maxLength(36)
param entraApiApplicationClientId string

@description('Reviewed official Azure MCP image by immutable SHA-256 digest. No default, tags, private registries or alternate images.')
param containerImage string

@description('Exact inventory allowlist; only group_resource_list is supported. Never use namespaces or proxy tools.')
@minLength(1)
@maxLength(1)
param allowedTools inventoryTool[]

@description('Existing regional ACA private-link DNS zone resource ID, including its owning subscription and resource group. No zone or VNet link is created.')
param privateDnsZoneResourceId string

@description('True: hub policy exclusively owns the PE DNS zone group. False: associate the PE with the supplied existing zone using privateDns.bicep.')
param centralDnsZoneByPolicyInHub bool

param tags object = {}

// Stable fail() guards also protect direct module callers without experimental Bicep assertions.
var validatedInfrastructureSubnetId = requireInfrastructureSubnetId(infrastructureSubnetId)
var validatedPrivateEndpointSubnetId = requirePrivateEndpointSubnetId(privateEndpointSubnetId, infrastructureSubnetId)
var validatedContainerImage = requirePinnedAzureMcpImage(containerImage)
var validatedPrivateDnsZoneResourceId = requirePrivateDnsZoneResourceId(privateDnsZoneResourceId)
var readerRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')

// The official image ENTRYPOINT already contains "server start"; retain it.
// Tool metadata: microsoft/mcp core/Azure.Mcp.Core/src/Areas/Group/Commands/ResourceListCommand.cs
var serverArgs = concat([
  '--transport'
  'http'
  '--outgoing-auth-strategy'
  'UseHostingEnvironmentIdentity'
  '--mode'
  'all'
  '--read-only'
], flatten(map(allowedTools, tool => [
  '--tool'
  tool
])))

resource managedEnvironment 'Microsoft.App/managedEnvironments@2025-07-01' = {
  name: '${name}-env'
  location: location
  tags: tags
  properties: {
    publicNetworkAccess: 'Disabled'
    vnetConfiguration: {
      internal: true
      infrastructureSubnetId: validatedInfrastructureSubnetId
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        // In an internal environment, external means other VNet clients, NOT the public internet.
        external: true
        allowInsecure: false
        targetPort: 8080
        transport: 'http'
      }
    }
    template: {
      containers: [
        {
          name: 'azure-mcp'
          image: validatedContainerImage
          command: []
          args: serverArgs
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AZURE_TOKEN_CREDENTIALS'
              value: 'managedidentitycredential'
            }
            {
              name: 'AZURE_MCP_INCLUDE_PRODUCTION_CREDENTIALS'
              value: 'true'
            }
            {
              name: 'AZURE_MCP_COLLECT_TELEMETRY'
              value: 'false'
            }
            {
              name: 'AzureAd__Instance'
              value: environment().authentication.loginEndpoint
            }
            {
              name: 'AzureAd__TenantId'
              value: tenantId
            }
            {
              name: 'AzureAd__ClientId'
              value: entraApiApplicationClientId
            }
            {
              name: 'ASPNETCORE_ENVIRONMENT'
              value: 'Production'
            }
            {
              name: 'DOTNET_ENVIRONMENT'
              value: 'Production'
            }
            {
              name: 'ASPNETCORE_URLS'
              value: 'http://0.0.0.0:8080'
            }
            {
              // ACA terminates TLS and sends internal HTTP to 8080. Disable only redirect loops;
              // Entra incoming authentication remains enabled and forwarded headers are not trusted.
              name: 'AZURE_MCP_DANGEROUSLY_DISABLE_HTTPS_REDIRECTION'
              value: 'true'
            }
            {
              name: 'Logging__LogLevel__Default'
              value: 'Warning'
            }
            {
              name: 'Logging__LogLevel__Azure'
              value: 'Warning'
            }
            {
              name: 'Logging__LogLevel__Microsoft'
              value: 'Warning'
            }
          ]
          // TCP checks startup/liveness without introducing an unauthenticated HTTP health endpoint.
          probes: [
            {
              type: 'Startup'
              tcpSocket: {
                port: 8080
              }
              initialDelaySeconds: 10
              periodSeconds: 5
              timeoutSeconds: 2
              failureThreshold: 30
            }
            {
              type: 'Readiness'
              tcpSocket: {
                port: 8080
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 2
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              tcpSocket: {
                port: 8080
              }
              initialDelaySeconds: 30
              periodSeconds: 30
              timeoutSeconds: 2
              failureThreshold: 3
            }
          ]
        }
      ]
      // A single replica avoids cross-replica MCP session affinity requirements.
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

resource projectReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, app.id, readerRoleDefinitionId)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: readerRoleDefinitionId
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${name}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: validatedPrivateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${name}-environment'
        properties: {
          privateLinkServiceId: managedEnvironment.id
          groupIds: [
            'managedEnvironments'
          ]
        }
      }
    ]
  }
}

module privateDns 'privateDns.bicep' = if (!centralDnsZoneByPolicyInHub) {
  name: '${name}-dns'
  params: {
    dnsConfig: [
      {
        name: privateEndpoint.name
        type: 'azurecontainerapps'
      }
    ]
    privateLinksDnsZones: {
      azurecontainerapps: {
        id: validatedPrivateDnsZoneResourceId
      }
    }
  }
  dependsOn: [
    privateEndpoint
  ]
}

output containerAppResourceId string = app.id
output identityPrincipalId string = app.identity.principalId
output appIdentity object = {
  type: 'SystemAssigned'
  resourceId: app.id
  principalId: app.identity.principalId
  tenantId: app.identity.tenantId
}
output managedEnvironmentResourceId string = managedEnvironment.id
output defaultDomain string = managedEnvironment.properties.defaultDomain
output staticIp string = managedEnvironment.properties.staticIp
output mcpUrl string = 'https://${app.properties.configuration.ingress.fqdn}/mcp'
output privateEndpointResourceId string = privateEndpoint.id
output readerRoleAssignmentResourceId string = projectReader.id
output readerRoleDefinitionResourceId string = readerRoleDefinitionId
output deploymentInputs object = {
  subscriptionId: subscription().subscriptionId
  projectResourceGroup: resourceGroup().name
  projectResourceGroupId: resourceGroup().id
  location: location
  name: name
  infrastructureSubnetId: validatedInfrastructureSubnetId
  privateEndpointSubnetId: validatedPrivateEndpointSubnetId
  tenantId: tenantId
  entraApiApplicationClientId: entraApiApplicationClientId
  containerImage: validatedContainerImage
  allowedTools: allowedTools
  privateDnsZoneResourceId: validatedPrivateDnsZoneResourceId
  centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
}
