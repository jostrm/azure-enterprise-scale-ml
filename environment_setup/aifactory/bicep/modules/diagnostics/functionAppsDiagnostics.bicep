// ============================================================================
// FUNCTION APPS DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Function Apps and Logic Apps Standard with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics and logs (basic monitoring)

@description('The name of the Function App resource')
param functionAppName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'gold'

@description('Collect WorkflowRuntime for Logic Apps Standard when a lower-cost diagnostic tier is selected. Not for Consumption Logic Apps.')
param isLogicAppStandard bool = false

@description('Optional. Function App name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${functionAppName}'

// Reference to existing Function App
resource functionApp 'Microsoft.Web/sites@2023-12-01' existing = {
  name: functionAppName
}

// Define metrics and logs based on diagnostic level
var goldMetrics = [
  {
    category: 'AllMetrics'
    enabled: true
  }
]

var silverMetrics = [
  {
    category: 'AllMetrics'
    enabled: true
  }
]

var bronzeMetrics = [
  {
    category: 'AllMetrics'
    enabled: true
  }
]

var goldLogs = [
  {
    categoryGroup: 'allLogs'
    enabled: true
  }
]

var silverLogs = [
  {
    category: 'FunctionAppLogs'
    enabled: true
  }
  {
    category: 'AppServiceAuditLogs'
    enabled: true
  }
  ...(isLogicAppStandard ? [
    {
      category: 'WorkflowRuntime'
      enabled: true
    }
  ] : [])
]

var bronzeLogs = [
  {
    category: isLogicAppStandard ? 'WorkflowRuntime' : 'FunctionAppLogs'
    enabled: true
  }
]

// Select metrics and logs based on diagnostic level
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics
var selectedLogs = diagnosticSettingLevel == 'gold' ? goldLogs : diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs

// Function Apps Diagnostic Settings
resource functionAppDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: functionApp
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = functionAppDiagnostics.id
