// ============================================================================
// COSMOS DB DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Cosmos DB with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Cosmos DB account resource')
param cosmosDbAccountName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Cosmos DB account name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${cosmosDbAccountName}'

// Reference to existing Cosmos DB account
resource cosmosDbAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmosDbAccountName
}

// Define metrics and logs based on diagnostic level
var goldMetrics = [
  {
    category: 'Requests'
    enabled: true
  }
]

var silverMetrics = [
  {
    category: 'Requests'
    enabled: true
  }
]

var bronzeMetrics = [
  {
    category: 'Requests'
    enabled: true
  }
]

var goldLogs = [
  {
    category: 'DataPlaneRequests'
    enabled: true
  }
  {
    category: 'QueryRuntimeStatistics'
    enabled: true
  }
  {
    category: 'PartitionKeyStatistics'
    enabled: true
  }
  {
    category: 'PartitionKeyRUConsumption'
    enabled: true
  }
  {
    category: 'ControlPlaneRequests'
    enabled: true
  }
  {
    category: 'CassandraRequests'
    enabled: true
  }
  {
    category: 'GremlinRequests'
    enabled: true
  }
  {
    category: 'MongoRequests'
    enabled: true
  }
  {
    category: 'TableApiRequests'
    enabled: true
  }
]

var silverLogs = [
  {
    category: 'DataPlaneRequests'
    enabled: true
  }
  {
    category: 'QueryRuntimeStatistics'
    enabled: true
  }
  {
    category: 'PartitionKeyStatistics'
    enabled: true
  }
  {
    category: 'ControlPlaneRequests'
    enabled: true
  }
]

var bronzeLogs = [
  {
    category: 'DataPlaneRequests'
    enabled: true
  }
  {
    category: 'ControlPlaneRequests'
    enabled: true
  }
]

// Select metrics and logs based on diagnostic level
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics
var selectedLogs = diagnosticSettingLevel == 'gold' ? goldLogs : diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs

// Cosmos DB Diagnostic Settings
resource cosmosDbDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: cosmosDbAccount
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = cosmosDbDiagnostics.id
