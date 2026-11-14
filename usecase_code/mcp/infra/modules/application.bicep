targetScope = 'resourceGroup'

@description('Name of the new Container App.')
param appName string

@description('Azure region for the Container App.')
param location string

@description('Name of the existing internal Container Apps managed environment.')
param managedEnvironmentName string

@description('Name of the existing Azure Container Registry.')
param registryName string

@description('Resource ID of the user-assigned managed identity.')
param identityResourceId string

@description('Client ID of the user-assigned managed identity.')
param identityClientId string

@description('Name of the existing RBAC-enabled Key Vault.')
param keyVaultName string

@description('Name of the existing API-key secret.')
param apiKeySecretName string

@description('Immutable MCP image reference.')
param mcpImage string

@description('Immutable Factory API image reference.')
param apiImage string

@secure()
@description('Secret-free JSON pilot agent configuration.')
param agentConfigJson string

@secure()
@description('Secret-free JSON application authentication configuration.')
param applicationAuthJson string

@description('Governed pilot scope key.')
param scopeKey string

@description('Expected MCP resource URL.')
param resourceUrl string

@description('Required AppOnboard and workload ownership tags.')
param tags object

resource managedEnvironment 'Microsoft.App/managedEnvironments@2026-07-01' existing = {
  name: managedEnvironmentName
}

resource keyVault 'Microsoft.KeyVault/vaults@2026-05-15' existing = {
  name: keyVaultName
}

resource apiKeySecret 'Microsoft.KeyVault/vaults/secrets@2026-05-15' existing = {
  parent: keyVault
  name: apiKeySecretName
}

resource containerApp 'Microsoft.App/containerApps@2026-07-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityResourceId}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 8080
        transport: 'auto'
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: '${registryName}.azurecr.io'
          identity: identityResourceId
        }
      ]
      secrets: [
        {
          name: 'factory-api-key'
          #disable-next-line no-hardcoded-env-urls
          keyVaultUrl: 'https://${keyVault.name}.vault.azure.net/secrets/${apiKeySecretName}'
          identity: identityResourceId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'mcp'
          image: mcpImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AIFACTORY_PILOT_CONFIG_JSON'
              value: agentConfigJson
            }
            {
              name: 'AIFACTORY_APPLICATION_AUTH_JSON'
              value: applicationAuthJson
            }
            {
              name: 'AIFACTORY_MCP_SCOPE'
              value: scopeKey
            }
            {
              name: 'AIFACTORY_MCP_RESOURCE_URL'
              value: resourceUrl
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: identityClientId
            }
            {
              name: 'AIFACTORY_API_KEY'
              secretRef: 'factory-api-key'
            }
            {
              name: 'PYTHONUNBUFFERED'
              value: '1'
            }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/health/live'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 2
              periodSeconds: 5
              timeoutSeconds: 3
              failureThreshold: 30
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health/live'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 3
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health/ready'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 5
              timeoutSeconds: 3
              failureThreshold: 6
            }
          ]
        }
        {
          name: 'factory-api'
          image: apiImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AIFACTORY_API_KEY'
              secretRef: 'factory-api-key'
            }
            {
              name: 'PYTHONUNBUFFERED'
              value: '1'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output appId string = containerApp.id
output fqdn string = containerApp.properties.configuration.ingress.fqdn
