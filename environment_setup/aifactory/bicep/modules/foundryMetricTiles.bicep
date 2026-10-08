// Output-only dashboard component: native metrics, no telemetry or service deployment.
param enabled bool = false
param accountResourceId string
param projectResourceId string

var accountMetricDefaults = {
  resourceMetadata: { id: accountResourceId }
  namespace: 'microsoft.cognitiveservices/accounts'
  aggregationType: 1 // Azure Portal MonitorChartPart: Sum.
}
var projectMetricDefaults = {
  resourceMetadata: { id: projectResourceId }
  namespace: 'microsoft.cognitiveservices/accounts/projects'
  aggregationType: 1
}
var metricGroups = [
  {
    x: 0
    y: 14
    title: 'Account: requests & calls (Sum)'
    metrics: [
      union(accountMetricDefaults, { name: 'AzureOpenAIRequests', metricVisualization: { displayName: 'Azure OpenAI requests' } })
      union(accountMetricDefaults, { name: 'TotalCalls', metricVisualization: { displayName: 'Total calls (non-OpenAI)' } })
    ]
  }
  {
    x: 4
    y: 14
    title: 'Account: generated images (Sum)'
    metrics: [
      union(accountMetricDefaults, { name: 'GeneratedImages', metricVisualization: { displayName: 'Generated images' } })
    ]
  }
  {
    x: 8
    y: 14
    title: 'Account: content safety (Sum)'
    metrics: [
      union(accountMetricDefaults, { name: 'RAIHarmfulRequests', metricVisualization: { displayName: 'Harmful volume detected' } })
      union(accountMetricDefaults, { name: 'RAIRejectedRequests', metricVisualization: { displayName: 'Content-filter blocked volume' } })
    ]
  }
  {
    x: 0
    y: 17
    title: 'Account: quota / limits, non-OpenAI (Sum)'
    metrics: [
      union(accountMetricDefaults, { name: 'BlockedCalls', metricVisualization: { displayName: 'Blocked calls (rate/quota)' } })
      union(accountMetricDefaults, { name: 'Ratelimit', metricVisualization: { displayName: 'RateLimit (limit values, not requests)' } })
    ]
  }
  {
    x: 4
    y: 17
    title: 'Project: agent activity (Sum)'
    metrics: [
      union(projectMetricDefaults, { name: 'AgentToolCalls', metricVisualization: { displayName: 'Agent tool calls' } })
      union(projectMetricDefaults, { name: 'AgentResponses', metricVisualization: { displayName: 'Agent responses' } })
    ]
  }
  {
    x: 8
    y: 17
    title: 'Project: agent model estimated USD (Sum)'
    metrics: [
      union(projectMetricDefaults, { name: 'AgentModelEstimatedCost', metricVisualization: { displayName: 'Estimated USD, not billed cost' } })
    ]
  }
]
var metricParts = [for group in (enabled ? metricGroups : []): {
  position: { x: group.x, y: group.y, colSpan: 4, rowSpan: 3 }
  metadata: {
    inputs: [
      { name: 'options', isOptional: true }
      { name: 'sharedTimeRange', isOptional: true }
    ]
    type: 'Extension/HubsExtension/PartType/MonitorChartPart'
    settings: {
      content: {
        options: {
          chart: {
            metrics: group.metrics
            title: group.title
            titleKind: 2
            timeContext: { durationMs: 2592000000 }
            visualization: {
              chartType: 2
              legendVisualization: { isVisible: true, position: 2, hideSubtitle: false }
              axisVisualization: {
                x: { isVisible: true, axisType: 2 }
                y: { isVisible: true, axisType: 1 }
              }
            }
          }
        }
      }
    }
  }
}]

output parts array = metricParts
