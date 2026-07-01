// Deploys an Azure Automation Account (System-Assigned MI) hosting the Foundry token report runbook,
// a daily schedule, and least-privilege RBAC (Reader on project+common RG, Log Analytics Reader).
// Runbook content is uploaded out-of-band (publishContentLink or az automation runbook replace-content).
targetScope = 'resourceGroup'

@description('Automation Account name')
param automationAccountName string = 'aa-foundry-report-${uniqueString(resourceGroup().id)}'
@description('Location')
param location string = resourceGroup().location
@description('Runbook name')
param runbookName string = 'Update-FoundryTokenReport'
@description('Common RG (Log Analytics) name for RBAC')
param commonResourceGroupName string
@description('Resource id of the project UAMI (mi-prj*). When set, the Automation Account runs as this identity, which already has RBAC on project resources.')
param projectUamiResourceId string = ''
@description('Daily run hour UTC start time (ISO8601)')
param scheduleStart string = dateTimeAdd(utcNow(), 'PT1H')

resource aa 'Microsoft.Automation/automationAccounts@2023-11-01' = {
  name: automationAccountName
  location: location
  identity: empty(projectUamiResourceId)
    ? { type: 'SystemAssigned' }
    : { type: 'SystemAssigned, UserAssigned', userAssignedIdentities: { '${projectUamiResourceId}': {} } }
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
  name: 'daily-foundry-report'
  properties: { startTime: scheduleStart, frequency: 'Day', interval: 1, timeZone: 'UTC' }
}

// Reader on this (project) RG
resource readerHere 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, aa.id, 'Reader')
  properties: {
    principalId: aa.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')
  }
}

output automationAccountId string = aa.id
output principalId string = aa.identity.principalId
output commonRgForRbac string = commonResourceGroupName // grant Log Analytics Reader here separately
output usingProjectUami bool = !empty(projectUamiResourceId)
