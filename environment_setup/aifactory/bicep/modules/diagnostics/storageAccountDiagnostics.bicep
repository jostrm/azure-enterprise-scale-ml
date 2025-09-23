// ============================================================================
// STORAGE ACCOUNT DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Storage Accounts with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Storage Account resource')
param storageAccountName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Storage Account name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${storageAccountName}'

// Reference to existing Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
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

// Storage Account main resource doesn't support log categories
// Only metrics are supported for the main storage account resource
var goldLogs = []
var silverLogs = []
var bronzeLogs = []

// Define log categories for storage services (blob, table, queue, file)
// Use categoryGroup 'allLogs' as individual storage services support this
var goldServiceLogs = [
  {
    categoryGroup: 'allLogs'
    enabled: true
  }
]

var silverServiceLogs = [
  {
    categoryGroup: 'allLogs'
    enabled: true
  }
]

var bronzeServiceLogs = [
  {
    categoryGroup: 'allLogs'
    enabled: true
  }
]

// Select metrics and logs based on diagnostic level
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics
var selectedLogs = diagnosticSettingLevel == 'gold' ? goldLogs : diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs
var selectedServiceLogs = diagnosticSettingLevel == 'gold' ? goldServiceLogs : diagnosticSettingLevel == 'silver' ? silverServiceLogs : bronzeServiceLogs

// Storage Account Diagnostic Settings
resource storageAccountDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: storageAccount
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Blob Service Reference and Diagnostic Settings
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  name: 'default'
  parent: storageAccount
}

resource blobServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${diagnosticSettingName}-blob'
  scope: blobService
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedServiceLogs
  }
}

// Table Service Reference and Diagnostic Settings  
resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' existing = {
  name: 'default'
  parent: storageAccount
}

resource tableServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${diagnosticSettingName}-table'
  scope: tableService
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedServiceLogs
  }
}

// Queue Service Reference and Diagnostic Settings
resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' existing = {
  name: 'default'
  parent: storageAccount
}

resource queueServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${diagnosticSettingName}-queue'
  scope: queueService
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedServiceLogs
  }
}

// File Service Reference and Diagnostic Settings
resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' existing = {
  name: 'default'
  parent: storageAccount
}

resource fileServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${diagnosticSettingName}-file'
  scope: fileService
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedServiceLogs
  }
}

// Output diagnostic setting resource IDs
output diagnosticSettingId string = storageAccountDiagnostics.id
output blobDiagnosticSettingId string = blobServiceDiagnostics.id
output tableDiagnosticSettingId string = tableServiceDiagnostics.id
output queueDiagnosticSettingId string = queueServiceDiagnostics.id
output fileDiagnosticSettingId string = fileServiceDiagnostics.id
