targetScope = 'resourceGroup'

@description('Existing Linux runner VM in the selected resource group, with private access to the Dev project. No VM is created.')
param runnerVmName string

@description('Azure region of the existing runner VM. Change this if the VM is in a different region from its resource group.')
param runnerLocation string = resourceGroup().location

@description('Absolute path to the prepared consumer repository on that VM. Its accelerator submodule and project configuration are reused, not overwritten.')
param consumerRoot string

@description('Absolute path to the existing Python 3.12+ environment on the VM with the Agent Factory operator dependencies installed.')
param pythonExecutable string

@description('Client ID of the existing user-assigned managed identity attached to the VM and authorized to deploy Agent Chat. No identity or role assignment is created by this entry point.')
@minLength(36)
@maxLength(36)
param managedIdentityClientId string

@description('Subscription containing the Dev project; must match its variables.json. The selected resource group above contains the runner VM.')
param projectSubscriptionId string = subscription().subscriptionId

@description('Existing Dev project number, 001-999. This deploys the Foundry agent, knowledge index and private chat app with live voice, not Factory infrastructure or model deployments.')
@minLength(3)
@maxLength(3)
param projectNumber string = '001'

@description('Optional path to the project variables.json, relative to consumerRoot or absolute on the VM. Leave empty to resolve the unique matching project.')
param configurationPath string = ''

@description('Change this value to rerun a completed deployment. Do not run this entry and a project pipeline concurrently.')
param runId string = utcNow('yyyyMMddHHmmss')

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
    ]
  }
}

output runCommandResourceId string = deployChat.id
output results string = 'Read this Run Command instance view for the application URL or failure details. The chat URL requires private network access and the configured Entra sign-in.'
