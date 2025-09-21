// ============================================================================
// LOG ANALYTICS WORKSPACE DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Log Analytics Workspace with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Log Analytics Workspace resource')
param logAnalyticsWorkspaceName string

@description('The resource ID of the Log Analytics workspace for diagnostics (can be different workspace)')
param targetLogAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Log Analytics Workspace name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${logAnalyticsWorkspaceName}'

// Reference to existing Log Analytics Workspace
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
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
    category: 'Audit'
    enabled: true
  }
]

var silverLogs = [
  {
    category: 'Audit'
    enabled: true
  }
]

var bronzeLogs = [
  {
    category: 'Audit'
    enabled: true
  }
]

// Select metrics and logs based on diagnostic level
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics
var selectedLogs = diagnosticSettingLevel == 'gold' ? goldLogs : diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs

// Log Analytics Workspace Diagnostic Settings
resource logAnalyticsWorkspaceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: logAnalyticsWorkspace
  properties: {
    workspaceId: targetLogAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = logAnalyticsWorkspaceDiagnostics.id
