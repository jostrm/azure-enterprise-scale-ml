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
    category: 'AmlComputeClusterEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'AmlComputeClusterNodeEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'AmlComputeJobEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'AmlComputeCpuGpuUtilization'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'AmlRunStatusChangedEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'ModelsChangeEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'ModelsReadEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'ModelsActionEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'DeploymentReadEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'DeploymentEventACI'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'DeploymentEventAKS'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'InferencingOperationAKS'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'InferencingOperationACI'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'DataLabelChangeEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'DataLabelReadEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'ComputeInstanceEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'DataStoreChangeEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'DataStoreReadEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'DataSetChangeEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'DataSetReadEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'PipelineChangeEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'PipelineReadEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'RunEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
  {
    category: 'RunReadEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 90
    }
  }
]

var silverLogs = [
  {
    category: 'AmlComputeClusterEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'AmlComputeJobEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'AmlRunStatusChangedEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'ModelsChangeEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'DeploymentEventAKS'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'InferencingOperationAKS'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'ComputeInstanceEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
  {
    category: 'RunEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 30
    }
  }
]

var bronzeLogs = [
  {
    category: 'AmlComputeClusterEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 7
    }
  }
  {
    category: 'AmlRunStatusChangedEvent'
    enabled: true
    retentionPolicy: {
      enabled: true
      days: 7
    }
  }
  {
    category: 'RunEvent'
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
