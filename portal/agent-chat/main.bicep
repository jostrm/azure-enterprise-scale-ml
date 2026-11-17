targetScope = 'resourceGroup'

@description('Existing Linux runner VM in the selected resource group, with private access to the Dev project. No VM is created.')
param runnerVmName string

@description('Optional VM region override. Leave empty to read the actual region from the selected VM.')
param runnerLocation string = ''

@description('Factory project folder on VM (not your PC): the prepared repository containing azurefactory/ or aifactory/ and the accelerator submodule. Empty uses /opt/esaf/consumer. No repository is downloaded.')
param consumerRoot string = ''

@description('Prepared Python on VM: the existing Python 3.12+ interpreter with operator dependencies installed. Empty uses <Factory project folder>/.venv-agent-operator/bin/python. Nothing is installed automatically.')
param pythonExecutable string = ''

@description('Optional identity override. Empty selects the VM sole user-assigned identity, or its system identity when no user-assigned identity exists. For multiple identities enter an attached client ID; system explicitly selects the system identity. Existing project permissions are still required.')
@maxLength(36)
param managedIdentityClientId string = ''

@description('Optional project subscription override. Empty reads dev_sub_id from the selected project variables.json; an override must match that configuration and the current tenant.')
param projectSubscriptionId string = ''

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

// A child deployment accepts the VM's runtime location; a resource location must be known at its deployment start.
module deployChat './run-command.bicep' = {
  name: 'esaf-agent-chat-${projectNumber}-${uniqueString(deployment().name)}'
  params: {
    runnerVmName: runnerVmName
    runnerLocation: empty(runnerLocation) ? runner.location : runnerLocation
    vmIdentity: runner.?identity ?? {}
    consumerRoot: consumerRoot
    pythonExecutable: pythonExecutable
    managedIdentityClientId: managedIdentityClientId
    projectSubscriptionId: projectSubscriptionId
    projectNumber: projectNumber
    configurationPath: configurationPath
    runId: runId
  }
}

output runCommandResourceId string = deployChat.outputs.runCommandResourceId
output results string = 'Read this Run Command instance view for resolved inputs, the application URL or failure details. The chat URL requires private network access and the configured Entra sign-in.'
