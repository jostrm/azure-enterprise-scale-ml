targetScope = 'resourceGroup'

param location string
param appName string = 'aifactory-agent-project001-dev'
param environmentName string
param identityName string = 'mi-aifactory-agent-dev'
param image string
param storageAccount string
param storageContainer string
param bundleBlob string
param bundleSha256 string
param bootstrapCommand string
param minReplicas int = 1
param maxReplicas int = 2
param cpu string = '0.5'
param memory string = '1Gi'

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: environmentName
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

resource application 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: {
    'managed-by': 'enterprise-scale-ai-factory-agent'
    'bundle-sha256': bundleSha256
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Multiple'
      ingress: {
        external: true
        targetPort: 8080
        allowInsecure: false
        transport: 'http'
        traffic: [{
          latestRevision: true
          weight: 100
        }]
      }
    }
    template: {
      containers: [{
        name: 'agent'
        image: image
        command: ['/bin/sh', '-c']
        args: [bootstrapCommand]
        env: [
          { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
          { name: 'BUNDLE_ACCOUNT', value: storageAccount }
          { name: 'BUNDLE_CONTAINER', value: storageContainer }
          { name: 'BUNDLE_BLOB', value: bundleBlob }
          { name: 'BUNDLE_SHA256', value: bundleSha256 }
          { name: 'PYTHONUNBUFFERED', value: '1' }
          { name: 'PIP_DISABLE_PIP_VERSION_CHECK', value: '1' }
        ]
        resources: {
          cpu: json(cpu)
          memory: memory
        }
        probes: [
          {
            type: 'Startup'
            httpGet: { path: '/health/live', port: 8080, scheme: 'HTTP' }
            initialDelaySeconds: 10
            periodSeconds: 10
            failureThreshold: 60
          }
          {
            type: 'Liveness'
            httpGet: { path: '/health/live', port: 8080, scheme: 'HTTP' }
            periodSeconds: 30
            failureThreshold: 3
          }
        ]
      }]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output fqdn string = application.properties.configuration.ingress.fqdn
output appId string = application.id
