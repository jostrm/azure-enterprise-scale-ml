// Deploys an Azure Automation Account (Managed Identity) hosting the AI Factory FinOps SHOWBACK
// runbook, a schedule, and SUBSCRIPTION-scope least-privilege RBAC.
//
// Unlike the single-project Foundry token report, showback reads cost across ALL project resource
// groups, so it needs 'Cost Management Reader' + 'Reader' at SUBSCRIPTION scope. Therefore this
// template is subscription-scoped: it deploys the Automation Account into the core-team management
// resource group (via module) and grants the two roles at subscription scope.
//
// Runbook content is uploaded out-of-band (az automation runbook replace-content + publish).
targetScope = 'subscription'

@description('Existing core-team / management resource group that will host the Automation Account.')
param automationResourceGroupName string

@description('Location for the Automation Account.')
param location string

@description('Automation Account name.')
param automationAccountName string = 'aa-aif-showback'

@description('Runbook name.')
param runbookName string = 'Update-ShowbackReport'

@description('Resource id of a project/core-team UAMI (mi-*). When set, the Automation Account also runs as this identity.')
param userAssignedIdentityResourceId string = ''

@description('Schedule start time (ISO8601). Default: +1h from deployment.')
param scheduleStart string = dateTimeAdd(utcNow(), 'PT1H')

@description('Schedule frequency. Showback is typically monthly; Day keeps daily visibility.')
@allowed(['Day', 'Week', 'Month'])
param scheduleFrequency string = 'Day'

@description('Schedule interval (e.g. 1 = every day/week/month).')
param scheduleInterval int = 1

// Built-in role definition IDs
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'              // Reader
var costMgmtReaderRoleId = '72fafb9e-0641-4937-9268-a91bfd8191a3'      // Cost Management Reader

module aa 'modules/automationAccount.bicep' = {
  name: 'aif-showback-aa'
  scope: resourceGroup(automationResourceGroupName)
  params: {
    automationAccountName: automationAccountName
    location: location
    runbookName: runbookName
    userAssignedIdentityResourceId: userAssignedIdentityResourceId
    scheduleStart: scheduleStart
    scheduleFrequency: scheduleFrequency
    scheduleInterval: scheduleInterval
  }
}

// Reader at subscription scope (enumerate project RGs + tags)
resource readerSub 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, automationAccountName, readerRoleId)
  properties: {
    principalId: aa.outputs.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
  }
}

// Cost Management Reader at subscription scope (Cost Management query + forecast APIs)
resource costReaderSub 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, automationAccountName, costMgmtReaderRoleId)
  properties: {
    principalId: aa.outputs.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', costMgmtReaderRoleId)
  }
}

output automationAccountId string = aa.outputs.automationAccountId
output principalId string = aa.outputs.principalId
output usingUserAssignedIdentity bool = !empty(userAssignedIdentityResourceId)
