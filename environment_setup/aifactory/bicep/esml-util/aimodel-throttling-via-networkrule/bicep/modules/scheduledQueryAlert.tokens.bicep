// =============================================================================
// scheduledQueryAlert.tokens.bicep
// Log Analytics scheduled query alert that sums Azure AI Foundry token usage
// over a rolling window and fires (-> Action Group -> throttle Logic App) when
// the total exceeds a token threshold (e.g. > 50,000,000 tokens / month).
//
// Prerequisite: the Cognitive Services accounts must send platform *Metrics*
// (AllMetrics) to the referenced Log Analytics workspace via a diagnostic
// setting, so token metrics land in the AzureMetrics table.
// =============================================================================

@description('Location for the alert rule (must match the workspace region).')
param location string = resourceGroup().location

@description('Alert rule name.')
param alertName string

@description('Resource id of the Log Analytics workspace holding the token metrics.')
param workspaceResourceId string

@description('Token count threshold. Alert fires when summed tokens exceed this over the window.')
param tokenThreshold int = 50000000

@description('Evaluation window in ISO8601 duration (how far back to sum). Default 30 days.')
param windowSize string = 'P30D'

@description('How often to evaluate, ISO8601 duration. Default 1 hour.')
param evaluationFrequency string = 'PT1H'

@description('Action Group resource id to notify.')
param actionGroupId string

@description('Tags.')
param tags object = {}

// Sums the token-related metrics emitted by Microsoft.CognitiveServices/accounts.
var kql = '''
AzureMetrics
| where ResourceProvider == "MICROSOFT.COGNITIVESERVICES"
| where MetricName in ("TokenTransaction", "ProcessedPromptTokens", "GeneratedTokens")
| summarize TotalTokens = sum(Total)
| where TotalTokens > 0
'''

resource alert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: alertName
  location: location
  tags: tags
  kind: 'LogAlert'
  properties: {
    displayName: alertName
    description: 'Fires when summed AI Foundry token usage exceeds the threshold, triggering network throttle.'
    severity: 2
    enabled: true
    scopes: [ workspaceResourceId ]
    evaluationFrequency: evaluationFrequency
    windowSize: windowSize
    criteria: {
      allOf: [
        {
          query: kql
          timeAggregation: 'Total'
          metricMeasureColumn: 'TotalTokens'
          operator: 'GreaterThan'
          threshold: tokenThreshold
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: false
    actions: {
      actionGroups: [ actionGroupId ]
    }
  }
}

output alertId string = alert.id
