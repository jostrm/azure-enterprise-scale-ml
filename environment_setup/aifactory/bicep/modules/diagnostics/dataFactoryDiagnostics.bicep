// ============================================================================
// DATA FACTORY DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Azure Data Factory with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Data Factory resource')
param dataFactoryName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Data Factory name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${dataFactoryName}'

// Reference to existing Data Factory
resource dataFactory 'Microsoft.DataFactory/factories@2018-06-01' existing = {
  name: dataFactoryName
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
    category: 'ActivityRuns'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'PipelineRuns'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'TriggerRuns'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'SandboxPipelineRuns'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'SandboxActivityRuns'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'SSISPackageEventMessages'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'SSISPackageExecutableStatistics'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'SSISPackageEventMessageContext'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'SSISPackageExecutionComponentPhases'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'SSISPackageExecutionDataStatistics'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'SSISIntegrationRuntimeLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
]

var silverLogs = [
  {
    category: 'ActivityRuns'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'PipelineRuns'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'TriggerRuns'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'SSISPackageEventMessages'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'SSISIntegrationRuntimeLogs'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
]

var bronzeLogs = [
  {
    category: 'ActivityRuns'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 7
    }
  }
  {
    category: 'PipelineRuns'
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

// Data Factory Diagnostic Settings
resource dataFactoryDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: dataFactory
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = dataFactoryDiagnostics.id
