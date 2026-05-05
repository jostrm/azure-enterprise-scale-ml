// ============================================================================
// Kong ACI - Azure Container Instances running Kong Gateway (DB-less mode)
// ============================================================================

@description('Location')
param location string

@description('Tags')
param tags object

@description('Environment')
param env string

@description('Location suffix')
param locationSuffix string

@description('Kong container image')
param kongImage string

@description('Kong CPU cores')
param kongCpu int

@description('Kong memory in GB')
param kongMemoryGb int

@description('Subnet ID for VNet injection')
param kongSubnetId string

@description('Storage account name for config')
param storageAccountName string

@description('File share name')
param fileShareName string

@description('Azure OpenAI endpoint (private)')
param azureOpenAIEndpoint string

@description('Azure OpenAI API key')
@secure()
param azureOpenAIApiKey string

@description('User-assigned managed identity resource ID')
param userAssignedIdentityId string = ''

@description('Common resource suffix')
param commonResourceSuffix string = '-001'

// ============================================================================
// Variables
// ============================================================================
var containerGroupName = 'aci-kong-${locationSuffix}-${env}${commonResourceSuffix}'
var hasUserIdentity = !empty(userAssignedIdentityId)

// ============================================================================
// Reference existing storage account to get key securely
// ============================================================================
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

// ============================================================================
// Kong Container Group
// ============================================================================
resource kongContainerGroup 'Microsoft.ContainerInstance/containerGroups@2023-05-01' = {
  name: containerGroupName
  location: location
  tags: tags
  identity: hasUserIdentity ? {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  } : null
  properties: {
    osType: 'Linux'
    restartPolicy: 'Always'
    sku: 'Standard'
    subnetIds: [
      {
        id: kongSubnetId
        name: 'kong-subnet'
      }
    ]
    containers: [
      {
        name: 'kong-gateway'
        properties: {
          image: kongImage
          resources: {
            requests: {
              cpu: kongCpu
              memoryInGB: kongMemoryGb
            }
          }
          ports: [
            {
              port: 8000
              protocol: 'TCP'
            }
            {
              port: 8443
              protocol: 'TCP'
            }
            {
              port: 8001
              protocol: 'TCP'
            }
          ]
          environmentVariables: [
            {
              name: 'KONG_DATABASE'
              value: 'off'
            }
            {
              name: 'KONG_DECLARATIVE_CONFIG'
              value: '/kong-config/kong.yaml'
            }
            {
              name: 'KONG_PROXY_LISTEN'
              value: '0.0.0.0:8000, 0.0.0.0:8443 ssl'
            }
            {
              name: 'KONG_ADMIN_LISTEN'
              value: '0.0.0.0:8001'
            }
            {
              name: 'KONG_LOG_LEVEL'
              value: 'info'
            }
            {
              name: 'KONG_PROXY_ACCESS_LOG'
              value: '/dev/stdout'
            }
            {
              name: 'KONG_PROXY_ERROR_LOG'
              value: '/dev/stderr'
            }
            {
              name: 'KONG_ADMIN_ACCESS_LOG'
              value: '/dev/stdout'
            }
            {
              name: 'KONG_ADMIN_ERROR_LOG'
              value: '/dev/stderr'
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAIEndpoint
            }
            {
              name: 'AZURE_OPENAI_API_KEY'
              secureValue: azureOpenAIApiKey
            }
          ]
          volumeMounts: [
            {
              name: 'kong-config-volume'
              mountPath: '/kong-config'
              readOnly: true
            }
          ]
          livenessProbe: {
            httpGet: {
              port: 8001
              path: '/status'
              scheme: 'http'
            }
            initialDelaySeconds: 15
            periodSeconds: 10
            failureThreshold: 3
            timeoutSeconds: 5
          }
          readinessProbe: {
            httpGet: {
              port: 8001
              path: '/status'
              scheme: 'http'
            }
            initialDelaySeconds: 10
            periodSeconds: 5
            failureThreshold: 3
            timeoutSeconds: 5
          }
        }
      }
    ]
    volumes: [
      {
        name: 'kong-config-volume'
        azureFile: {
          shareName: fileShareName
          storageAccountName: storageAccountName
          storageAccountKey: storageAccount.listKeys().keys[0].value
          readOnly: true
        }
      }
    ]
    ipAddress: {
      type: 'Private'
      ports: [
        {
          port: 8000
          protocol: 'TCP'
        }
        {
          port: 8443
          protocol: 'TCP'
        }
        {
          port: 8001
          protocol: 'TCP'
        }
      ]
    }
  }
}

// ============================================================================
// Outputs
// ============================================================================
output kongPrivateIp string = kongContainerGroup.properties.ipAddress.ip
output containerGroupName string = kongContainerGroup.name
output containerGroupId string = kongContainerGroup.id
