// ============================================================================
// SQL DATABASE DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Azure SQL Database with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the SQL Server resource')
param sqlServerName string

@description('The name of the SQL Database resource')
param sqlDatabaseName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. SQL Database name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${sqlDatabaseName}'

// Reference to existing SQL Database
resource sqlDatabase 'Microsoft.Sql/servers/databases@2023-08-01-preview' existing = {
  name: '${sqlServerName}/${sqlDatabaseName}'
}

// Define metrics and logs based on diagnostic level
var goldMetrics = [
  {
    category: 'Basic'
    enabled: true
  }
  {
    category: 'InstanceAndAppAdvanced'
    enabled: true
  }
  {
    category: 'WorkloadManagement'
    enabled: true
  }
]

var silverMetrics = [
  {
    category: 'Basic'
    enabled: true
  }
  {
    category: 'InstanceAndAppAdvanced'
    enabled: true
  }
]

var bronzeMetrics = [
  {
    category: 'Basic'
    enabled: true
  }
]

var goldLogs = [
  {
    category: 'SQLInsights'
    enabled: true
  }
  {
    category: 'AutomaticTuning'
    enabled: true
  }
  {
    category: 'QueryStoreRuntimeStatistics'
    enabled: true
  }
  {
    category: 'QueryStoreWaitStatistics'
    enabled: true
  }
  {
    category: 'Errors'
    enabled: true
  }
  {
    category: 'DatabaseWaitStatistics'
    enabled: true
  }
  {
    category: 'Timeouts'
    enabled: true
  }
  {
    category: 'Blocks'
    enabled: true
  }
  {
    category: 'Deadlocks'
    enabled: true
  }
]

var silverLogs = [
  {
    category: 'SQLInsights'
    enabled: true
  }
  {
    category: 'QueryStoreRuntimeStatistics'
    enabled: true
  }
  {
    category: 'Errors'
    enabled: true
  }
  {
    category: 'Timeouts'
    enabled: true
  }
  {
    category: 'Deadlocks'
    enabled: true
  }
]

var bronzeLogs = [
  {
    category: 'Errors'
    enabled: true
  }
  {
    category: 'Timeouts'
    enabled: true
  }
]

// Select metrics and logs based on diagnostic level
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics
var selectedLogs = diagnosticSettingLevel == 'gold' ? goldLogs : diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs

// SQL Database Diagnostic Settings
resource sqlDatabaseDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: sqlDatabase
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = sqlDatabaseDiagnostics.id
