// ============================================================================
// ELASTICSEARCH DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Elasticsearch with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Elasticsearch monitor resource')
param elasticName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Elasticsearch monitor name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${elasticName}'

// Reference to existing Elasticsearch monitor
resource elasticMonitor 'Microsoft.Elastic/monitors@2024-03-01' existing = {
  name: elasticName
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
    categoryGroup: 'audit'
    enabled: true
  }
]

var bronzeLogs = []

// Map diagnostic level to appropriate settings
var metricsConfig = diagnosticSettingLevel == 'gold' ? goldMetrics : (diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics)
var logsConfig = diagnosticSettingLevel == 'gold' ? goldLogs : (diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs)

// Diagnostic Setting
resource diagnosticSetting 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: elasticMonitor
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: metricsConfig
    logs: logsConfig
  }
}

output diagnosticSettingId string = diagnosticSetting.id
