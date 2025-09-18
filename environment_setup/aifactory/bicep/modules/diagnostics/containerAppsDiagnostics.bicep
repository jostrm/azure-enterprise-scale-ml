// ============================================================================
// CONTAINER APPS DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Azure Container Apps with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Container App resource')
param containerAppName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Container App name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${containerAppName}'

// Reference to existing Container App
resource containerApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: containerAppName
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
    category: 'ContainerAppConsoleLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'ContainerAppSystemLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
]

var silverLogs = [
  {
    category: 'ContainerAppConsoleLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'ContainerAppSystemLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
]

var bronzeLogs = [
  {
    category: 'ContainerAppSystemLogs'
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

// Container Apps Diagnostic Settings
resource containerAppDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: containerApp
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = containerAppDiagnostics.id
