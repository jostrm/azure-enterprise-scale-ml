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
    category: 'ActivityRuns'
    enabled: true
  }
  {
    category: 'PipelineRuns'
    enabled: true
  }
  {
    category: 'TriggerRuns'
    enabled: true
  }
  {
    category: 'SandboxPipelineRuns'
    enabled: true
  }
  {
    category: 'SandboxActivityRuns'
    enabled: true
  }
  {
    category: 'SSISPackageEventMessages'
    enabled: true
  }
  {
    category: 'SSISPackageExecutableStatistics'
    enabled: true
  }
  {
    category: 'SSISPackageEventMessageContext'
    enabled: true
  }
  {
    category: 'SSISPackageExecutionComponentPhases'
    enabled: true
  }
  {
    category: 'SSISPackageExecutionDataStatistics'
    enabled: true
  }
  {
    category: 'SSISIntegrationRuntimeLogs'
    enabled: true
  }
]

var silverLogs = [
  {
    category: 'ActivityRuns'
    enabled: true
  }
  {
    category: 'PipelineRuns'
    enabled: true
  }
  {
    category: 'TriggerRuns'
    enabled: true
  }
  {
    category: 'SSISPackageEventMessages'
    enabled: true
  }
  {
    category: 'SSISIntegrationRuntimeLogs'
    enabled: true
  }
]

var bronzeLogs = [
  {
    category: 'ActivityRuns'
    enabled: true
  }
  {
    category: 'PipelineRuns'
    enabled: true
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
