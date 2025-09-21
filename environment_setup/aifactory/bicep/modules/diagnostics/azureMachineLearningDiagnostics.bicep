// ============================================================================
// AZURE MACHINE LEARNING DIAGNOSTIC SETTINGS MODULE
// ============================================================================
// This module creates diagnostic settings for Azure Machine Learning workspace with three tiers:
// - Gold: All metrics and logs (comprehensive monitoring)
// - Silver: Key metrics and logs (balanced monitoring)  
// - Bronze: Essential metrics only (basic monitoring)

@description('The name of the Azure Machine Learning workspace resource')
param machineLearningWorkspaceName string

@description('The resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Optional. Azure ML workspace name prefix for diagnostic setting')
param diagnosticSettingName string = 'diag-${machineLearningWorkspaceName}'

// Reference to existing Azure ML workspace
resource machineLearningWorkspace 'Microsoft.MachineLearningServices/workspaces@2024-04-01' existing = {
  name: machineLearningWorkspaceName
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
    category: 'AmlComputeClusterEvent'
    enabled: true
  }
  {
    category: 'AmlComputeClusterNodeEvent'
    enabled: true
  }
  {
    category: 'AmlComputeJobEvent'
    enabled: true
  }
  {
    category: 'AmlComputeCpuGpuUtilization'
    enabled: true
  }
  {
    category: 'AmlRunStatusChangedEvent'
    enabled: true
  }
  {
    category: 'ModelsChangeEvent'
    enabled: true
  }
  {
    category: 'ModelsReadEvent'
    enabled: true
  }
  {
    category: 'ModelsActionEvent'
    enabled: true
  }
  {
    category: 'DeploymentReadEvent'
    enabled: true
  }
  {
    category: 'DeploymentEventACI'
    enabled: true
  }
  {
    category: 'DeploymentEventAKS'
    enabled: true
  }
  {
    category: 'InferencingOperationAKS'
    enabled: true
  }
  {
    category: 'InferencingOperationACI'
    enabled: true
  }
  {
    category: 'DataLabelChangeEvent'
    enabled: true
  }
  {
    category: 'DataLabelReadEvent'
    enabled: true
  }
  {
    category: 'ComputeInstanceEvent'
    enabled: true
  }
  {
    category: 'DataStoreChangeEvent'
    enabled: true
  }
  {
    category: 'DataStoreReadEvent'
    enabled: true
  }
  {
    category: 'DataSetChangeEvent'
    enabled: true
  }
  {
    category: 'DataSetReadEvent'
    enabled: true
  }
  {
    category: 'PipelineChangeEvent'
    enabled: true
  }
  {
    category: 'PipelineReadEvent'
    enabled: true
  }
  {
    category: 'RunEvent'
    enabled: true
  }
  {
    category: 'RunReadEvent'
    enabled: true
  }
]

var silverLogs = [
  {
    category: 'AmlComputeClusterEvent'
    enabled: true
  }
  {
    category: 'AmlComputeJobEvent'
    enabled: true
  }
  {
    category: 'AmlRunStatusChangedEvent'
    enabled: true
  }
  {
    category: 'ModelsChangeEvent'
    enabled: true
  }
  {
    category: 'DeploymentEventAKS'
    enabled: true
  }
  {
    category: 'InferencingOperationAKS'
    enabled: true
  }
  {
    category: 'ComputeInstanceEvent'
    enabled: true
  }
  {
    category: 'RunEvent'
    enabled: true
  }
]

var bronzeLogs = [
  {
    category: 'AmlComputeClusterEvent'
    enabled: true
  }
  {
    category: 'AmlRunStatusChangedEvent'
    enabled: true
  }
  {
    category: 'RunEvent'
    enabled: true
  }
]

// Select metrics and logs based on diagnostic level
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics
var selectedLogs = diagnosticSettingLevel == 'gold' ? goldLogs : diagnosticSettingLevel == 'silver' ? silverLogs : bronzeLogs

// Azure Machine Learning Diagnostic Settings
resource machineLearningDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: diagnosticSettingName
  scope: machineLearningWorkspace
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: selectedLogs
  }
}

// Output diagnostic setting resource ID
output diagnosticSettingId string = machineLearningDiagnostics.id
