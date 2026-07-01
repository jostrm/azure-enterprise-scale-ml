// Resource-group-scoped module: Automation Account (Managed Identity) + showback runbook + schedule.
// Invoked by ../deploy-automation.bicep (subscription-scoped) so the subscription-scope RBAC can
// target this account's principal.
targetScope = 'resourceGroup'

@description('Automation Account name.')
param automationAccountName string

@description('Location.')
param location string = resourceGroup().location

@description('Runbook name.')
param runbookName string

@description('Optional UAMI resource id (mi-*). When set, account runs as System + this UAMI.')
param userAssignedIdentityResourceId string = ''

@description('Schedule start time (ISO8601).')
param scheduleStart string

@description('Schedule frequency.')
@allowed(['Day', 'Week', 'Month'])
param scheduleFrequency string

@description('Schedule interval.')
param scheduleInterval int

resource aa 'Microsoft.Automation/automationAccounts@2023-11-01' = {
  name: automationAccountName
  location: location
  identity: empty(userAssignedIdentityResourceId)
    ? { type: 'SystemAssigned' }
    : { type: 'SystemAssigned, UserAssigned', userAssignedIdentities: { '${userAssignedIdentityResourceId}': {} } }
  properties: { sku: { name: 'Basic' } }
}

resource runbook 'Microsoft.Automation/automationAccounts/runbooks@2023-11-01' = {
  parent: aa
  name: runbookName
  location: location
  properties: { runbookType: 'PowerShell72', logProgress: true, logVerbose: false }
}

resource schedule 'Microsoft.Automation/automationAccounts/schedules@2023-11-01' = {
  parent: aa
  name: 'aif-showback-schedule'
  properties: {
    startTime: scheduleStart
    frequency: scheduleFrequency
    interval: scheduleInterval
    timeZone: 'UTC'
  }
}

output automationAccountId string = aa.id
output principalId string = aa.identity.principalId
