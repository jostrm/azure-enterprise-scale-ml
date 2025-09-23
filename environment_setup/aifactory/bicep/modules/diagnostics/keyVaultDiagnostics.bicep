// ============================================================================
// KEY VAULT DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Key Vault with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Key Vault resource')
param keyVaultName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Key Vault name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${keyVaultName}'

// Reference to existing Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
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
    category: 'AuditEvent'
    enabled: true
  }
]

var bronzeLogs = [
  {
    category: 'AuditEvent'
    enabled: true
  }
]

// Select metrics and logs based on diagnostic level
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics
var selectedLogs = diagnosticSettingLevel == 'gold' ? goldLogs : diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs

// Key Vault Diagnostic Settings
resource keyVaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: keyVault
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = keyVaultDiagnostics.id
