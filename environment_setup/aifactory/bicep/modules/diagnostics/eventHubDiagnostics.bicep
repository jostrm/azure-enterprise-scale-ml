// ============================================================================
// EVENT HUB DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Azure Event Hub with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Event Hub Namespace resource')
param eventHubNamespaceName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Event Hub Namespace name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${eventHubNamespaceName}'

// Reference to existing Event Hub Namespace
resource eventHubNamespace 'Microsoft.EventHub/namespaces@2024-01-01' existing = {
  name: eventHubNamespaceName
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
    category: 'ArchiveLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'OperationalLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'AutoScaleLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'KafkaCoordinatorLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'KafkaUserErrorLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'EventHubVNetConnectionEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'CustomerManagedKeyUserLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
]

var silverLogs = [
  {
    category: 'OperationalLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'AutoScaleLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'KafkaUserErrorLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'EventHubVNetConnectionEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
]

var bronzeLogs = [
  {
    category: 'OperationalLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 7
    }
  }
  {
    category: 'EventHubVNetConnectionEvent'
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

// Event Hub Diagnostic Settings
resource eventHubDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: eventHubNamespace
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = eventHubDiagnostics.id
