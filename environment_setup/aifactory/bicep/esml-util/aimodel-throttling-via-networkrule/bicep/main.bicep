// =============================================================================
// main.bicep  (targetScope = subscription)
// Deploys the automated "throttle GenAI when over budget/tokens" chain:
//
//   Azure Monitor / Consumption
//        |  (cost budget alert  AND/OR  token scheduled-query alert)
//        v
//   Action Group
//        |  (logicAppReceiver)
//        v
//   Logic App (Consumption, managed identity)
//        |  reject private endpoints + disable public access
//        v
//   Azure AI Foundry / Cognitive Services accounts in scope  -> callers blocked
//
// Works on a whole SUBSCRIPTION or a single project RESOURCE GROUP.
// Turn the cap OFF (revert) with scripts/throttle-genai.ps1|sh -Action Unthrottle.
// =============================================================================
targetScope = 'subscription'

// ------------------------- Scope -------------------------
@description('Throttle scope: whole subscription, or a single AI Factory project resource group.')
@allowed([ 'Subscription', 'ResourceGroup' ])
param throttleScope string = 'ResourceGroup'

@description('The AI Factory project resource group to throttle & budget. Required when throttleScope=ResourceGroup and esmlAifactoryExists=false.')
param targetResourceGroup string = ''

@description('Resource group that HOSTS the Logic App + Action Group (management RG). Defaults to targetResourceGroup.')
param throttleResourceGroup string = ''

@description('Azure region for the Logic App and alert rule.')
param location string = deployment().location

// ------------------------- AI Factory naming (esml-aifactory-exists) -------------------------
@description('When true, the project/vnet resource-group names are DERIVED from the AI Factory naming convention using the parameters below - no need to pass targetResourceGroup. When false, pass names explicitly.')
param esmlAifactoryExists bool = false

@description('AI Factory environment (used for naming derivation).')
@allowed([ 'dev', 'test', 'prod' ])
param env string = 'dev'

@description('AI Factory: admin_aifactoryPrefixRG (e.g. "acme-1-").')
param aifactoryPrefixRG string = ''

@description('AI Factory: projectPrefix (often empty).')
param projectPrefix string = ''

@description('AI Factory: projectSuffix (often empty).')
param projectSuffix string = ''

@description('AI Factory: project_number_000 (e.g. "001").')
param projectNumber string = ''

@description('AI Factory: admin_locationSuffix (e.g. "swc", "weu").')
param locationSuffix string = ''

@description('AI Factory: admin_aifactorySuffixRG (e.g. "-001").')
param aifactorySuffixRG string = ''

// ------------------------- Naming -------------------------
@description('Prefix for created resources.')
param namePrefix string = 'esml-throttle'

@description('Name of the Logic App to create/use as the throttle executor. Defaults to "<namePrefix>-logic".')
param logicAppName string = ''

@description('Tags applied to created resources.')
param tags object = {}

// ------------------------- Observability pre-req -------------------------
@description('Optional but recommended. Log Analytics workspace resource id behind your Application Insights (pre-req) for Logic App run telemetry.')
param logAnalyticsWorkspaceResourceId string = ''

// ------------------------- Cost budget -------------------------
@description('Deploy the cost budget alert.')
param enableBudget bool = true

@description('Monthly budget amount in billing currency.')
param budgetAmount int = 5000

@description('ACTUAL spend % of amount that fires the throttle (e.g. 100).')
param actualThresholdPercent int = 100

@description('FORECASTED spend % of amount that fires the throttle (e.g. 90).')
param forecastThresholdPercent int = 90

@description('Budget start date, first of a month, yyyy-MM-dd.')
param budgetStartDate string

// ------------------------- Token alert -------------------------
@description('Deploy the token scheduled-query alert (requires a Log Analytics workspace with Foundry metrics).')
param enableTokenAlert bool = false

@description('Resource id of the Log Analytics workspace holding Foundry token metrics.')
param workspaceResourceId string = ''

@description('Resource group of the Log Analytics workspace (where the alert rule is created).')
param workspaceResourceGroup string = ''

@description('Token threshold over the window (e.g. 50000000 = 50M tokens/month).')
param tokenThreshold int = 50000000

// ------------------------- Notify -------------------------
@description('Optional emails to also notify when throttling fires.')
param notifyEmails array = []

// ------------------------- Computed -------------------------
// When esmlAifactoryExists, derive the project RG from the AI Factory convention:
//   {prefixRG}{projectPrefix}project{projectNumber}-{locationSuffix}-{env}{suffixRG}{projectSuffix}
var derivedProjectRG = '${aifactoryPrefixRG}${projectPrefix}project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'
var resolvedTargetRg = !empty(targetResourceGroup) ? targetResourceGroup : (esmlAifactoryExists ? derivedProjectRG : '')

var hostRg = empty(throttleResourceGroup) ? resolvedTargetRg : throttleResourceGroup
var isSubScope = throttleScope == 'Subscription'
var scopeResourceId = isSubScope
  ? subscription().id
  : '${subscription().id}/resourceGroups/${resolvedTargetRg}'

var logicAppNameResolved = empty(logicAppName) ? '${namePrefix}-logic' : logicAppName
var actionGroupName = '${namePrefix}-ag'
var budgetName     = '${namePrefix}-budget'
var tokenAlertName = '${namePrefix}-token-alert'

// ------------------------- Logic App (throttle executor) -------------------------
module logicApp 'modules/logicApp.throttle.bicep' = {
  name: 'deploy-throttle-logicapp'
  scope: resourceGroup(hostRg)
  params: {
    location: location
    logicAppName: logicAppNameResolved
    scopeResourceId: scopeResourceId
    logAnalyticsWorkspaceResourceId: logAnalyticsWorkspaceResourceId
    tags: tags
  }
}

// ------------------------- RBAC for the Logic App MI -------------------------
module raSub 'modules/roleAssignment.subscription.bicep' = if (isSubScope) {
  name: 'deploy-throttle-rbac-sub'
  params: {
    principalId: logicApp.outputs.principalId
  }
}

module raRg 'modules/roleAssignment.resourcegroup.bicep' = if (!isSubScope) {
  name: 'deploy-throttle-rbac-rg'
  scope: resourceGroup(resolvedTargetRg)
  params: {
    principalId: logicApp.outputs.principalId
  }
}

// ------------------------- Action Group -------------------------
module actionGroup 'modules/actionGroup.bicep' = {
  name: 'deploy-throttle-actiongroup'
  scope: resourceGroup(hostRg)
  params: {
    actionGroupName: actionGroupName
    logicAppName: logicApp.outputs.logicAppName
    emailReceivers: notifyEmails
    tags: tags
  }
}

// ------------------------- Cost budget -------------------------
module budgetSub 'modules/budget.subscription.bicep' = if (enableBudget && isSubScope) {
  name: 'deploy-throttle-budget-sub'
  params: {
    budgetName: budgetName
    amount: budgetAmount
    actualThresholdPercent: actualThresholdPercent
    forecastThresholdPercent: forecastThresholdPercent
    actionGroupId: actionGroup.outputs.actionGroupId
    startDate: budgetStartDate
  }
}

module budgetRg 'modules/budget.resourcegroup.bicep' = if (enableBudget && !isSubScope) {
  name: 'deploy-throttle-budget-rg'
  scope: resourceGroup(resolvedTargetRg)
  params: {
    budgetName: budgetName
    amount: budgetAmount
    actualThresholdPercent: actualThresholdPercent
    forecastThresholdPercent: forecastThresholdPercent
    actionGroupId: actionGroup.outputs.actionGroupId
    startDate: budgetStartDate
  }
}

// ------------------------- Token scheduled-query alert -------------------------
module tokenAlert 'modules/scheduledQueryAlert.tokens.bicep' = if (enableTokenAlert) {
  name: 'deploy-throttle-token-alert'
  scope: resourceGroup(empty(workspaceResourceGroup) ? hostRg : workspaceResourceGroup)
  params: {
    location: location
    alertName: tokenAlertName
    workspaceResourceId: workspaceResourceId
    tokenThreshold: tokenThreshold
    actionGroupId: actionGroup.outputs.actionGroupId
    tags: tags
  }
}

// ------------------------- Outputs -------------------------
output logicAppName string = logicApp.outputs.logicAppName
output logicAppPrincipalId string = logicApp.outputs.principalId
output actionGroupId string = actionGroup.outputs.actionGroupId
output throttleScopeResourceId string = scopeResourceId
