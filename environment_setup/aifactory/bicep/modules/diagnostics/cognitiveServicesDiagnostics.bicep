// ============================================================================
// COGNITIVE SERVICES DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Cognitive Services with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Cognitive Services resource')
param cognitiveServiceName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Cognitive Service name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${cognitiveServiceName}'

// Reference to existing Cognitive Service
resource cognitiveService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: cognitiveServiceName
}

// Define metrics and logs based on diagnostic level
var goldMetrics = [
  {
    category: 'AllMetrics'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
]

var silverMetrics = [
  {
    category: 'AllMetrics'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
]

var bronzeMetrics = [
  {
    category: 'AllMetrics'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 7
    }
  }
]

var goldLogs = [
  {
    category: 'Audit'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'RequestResponse'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'Trace'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
]

var silverLogs = [
  {
    category: 'Audit'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'RequestResponse'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
]

var bronzeLogs = [
  {
    category: 'Audit'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 7
    }
  }
]

// Select metrics and logs based on diagnostic level
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics
var selectedLogs = diagnosticSettingLevel == 'gold' ? goldLogs : diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs

// Cognitive Services Diagnostic Settings
resource cognitiveServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: cognitiveService
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = cognitiveServiceDiagnostics.id
