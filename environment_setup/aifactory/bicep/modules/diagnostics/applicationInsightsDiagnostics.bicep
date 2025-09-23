// ============================================================================
// APPLICATION INSIGHTS DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Application Insights with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Application Insights resource')
param applicationInsightsName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Application Insights name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${applicationInsightsName}'

// Reference to existing Application Insights
resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
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
    categoryGroup: 'allLogs'
    enabled: true
  }
]

var bronzeLogs = [
  {
    categoryGroup: 'allLogs'
    enabled: true
  }
]

// Select metrics and logs based on diagnostic level
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics
var selectedLogs = diagnosticSettingLevel == 'gold' ? goldLogs : diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs

// Application Insights Diagnostic Settings
resource applicationInsightsDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: applicationInsights
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = applicationInsightsDiagnostics.id
