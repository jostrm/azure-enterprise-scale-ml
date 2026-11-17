targetScope = 'resourceGroup'

param runnerVmName string
param runnerLocation string
param vmIdentity object
param consumerRoot string
param pythonExecutable string
param managedIdentityClientId string
param projectSubscriptionId string
param projectNumber string
param configurationPath string
param runId string

resource runner 'Microsoft.Compute/virtualMachines@2024-11-01' existing = {
  name: runnerVmName
}

resource deployChat 'Microsoft.Compute/virtualMachines/runCommands@2024-11-01' = {
  parent: runner
  name: 'esaf-agent-chat-${projectNumber}'
  location: runnerLocation
  properties: {
    asyncExecution: false
    treatFailureAsDeploymentFailure: true
    timeoutInSeconds: 14400
    source: {
      script: loadTextContent('run.sh')
    }
    parameters: [
      { name: 'AIF_CONSUMER_ROOT', value: consumerRoot }
      { name: 'AIF_PROJECT_NUMBER', value: projectNumber }
      { name: 'AIF_PYTHON', value: pythonExecutable }
      { name: 'AIF_IDENTITY_CLIENT_ID', value: managedIdentityClientId }
      { name: 'AIF_SUBSCRIPTION_ID', value: projectSubscriptionId }
      { name: 'AIF_TENANT_ID', value: subscription().tenantId }
      { name: 'AIF_CONFIGURATION_PATH', value: configurationPath }
      { name: 'AIF_RUN_ID', value: runId }
      { name: 'AIF_VM_IDENTITY', value: string(vmIdentity) }
    ]
  }
}

output runCommandResourceId string = deployChat.id
