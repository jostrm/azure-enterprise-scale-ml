@description('Existing project resource group. All inventory and billing queries stay within this scope.')
param projectResourceGroupId string
@description('Existing project Application Insights component; no instrumentation or diagnostics are created.')
param applicationInsightsResourceId string
param projectNumber string
param env string = ''

var environmentLabel = empty(env) ? '' : ' · ${toUpper(env)}'
var usageVisibility = { parameterName: 'Navigation', comparison: 'isEqualTo', value: 'usage' }
var costVisibility = { parameterName: 'Navigation', comparison: 'isEqualTo', value: 'cost' }
var inventoryQuery = '''
Resources
| where tolower(id) startswith '__PROJECT_PREFIX__'
'''
var scopedInventory = replace(inventoryQuery, '__PROJECT_PREFIX__', toLower('${projectResourceGroupId}/providers/'))
var inventorySettings = {
  version: 'KqlItem/1.0'
  queryType: 1
  resourceType: 'microsoft.resourcegraph/resources'
  crossComponentResources: [projectResourceGroupId]
  size: 0
  noDataMessage: 'No visible resources in this project resource group.'
}
var accountDiscovery = '''
Resources
| where type =~ 'microsoft.cognitiveservices/accounts'
| where ['kind'] in~ ('AIServices', 'OpenAI')
| where tolower(id) startswith '__ACCOUNT_PREFIX__'
| where array_length(split(id, '/')) == 9
'''
var scopedAccounts = replace(accountDiscovery, '__ACCOUNT_PREFIX__', toLower('${projectResourceGroupId}/providers/Microsoft.CognitiveServices/accounts/'))
var nativeMetricSettings = {
  version: 'MetricsItem/2.0'
  size: 0
  resourceType: 'microsoft.cognitiveservices/accounts'
  metricScope: 0
  resourceIds: ['{GenericMetricAccount}']
  resourceLimit: 1
  timeContext: { durationMs: 2592000000 }
}
var nativeMetricProfiles = loadJsonContent('./workbooks/my-project/tokens-metrics.json')
var nativeMetricGroups = [for profile in nativeMetricProfiles: {
  type: 12
  name: 'generic-native-${profile.key}'
  conditionalVisibility: { parameterName: 'GenericMetricProfile', comparison: 'isEqualTo', value: profile.key }
  content: {
    version: 'NotebookGroup/1.0'
    groupType: 'editable'
    items: [
      {
        type: 10
        name: 'generic-native-${profile.key}-trend'
        content: union(nativeMetricSettings, {
          chartId: 'generic-native-${profile.key}-trend'
          title: '${profile.label} · input / output tokens · last 30 days'
          chartType: 2
          metrics: profile.metrics
        })
      }
      {
        type: 10
        name: 'generic-native-${profile.key}-table'
        content: union(nativeMetricSettings, {
          chartId: 'generic-native-${profile.key}-table'
          title: '${profile.label} · token usage by deployment / model version'
          chartType: 0
          gridFormatType: 2
          metrics: profile.metrics
        })
      }
    ]
  }
}]

// Native categories and Count aggregation:
// https://learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-insights-components-metrics
// MetricsItem/2.0 IDs use namespace-category-name; Count=7, line=2, grid=0:
// https://github.com/microsoft/Application-Insights-Workbooks/blob/master/Workbooks/Azure%20Machine%20Learning/AI%20Studio/AtResource/AI-Studio-Insights.workbook
var httpMetricSettings = {
  version: 'MetricsItem/2.0'
  size: 0
  resourceType: 'microsoft.insights/components'
  metricScope: 0
  resourceIds: [applicationInsightsResourceId]
  resourceLimit: 1
  timeContext: { durationMs: 2592000000 }
  metrics: [
    {
      namespace: 'microsoft.insights/components'
      metric: 'microsoft.insights/components-Server-requests/count'
      aggregation: 7
      columnName: 'HTTP requests'
    }
    {
      namespace: 'microsoft.insights/components'
      metric: 'microsoft.insights/components-Failures-requests/failed'
      aggregation: 7
      columnName: 'Failed HTTP requests (subset)'
    }
  ]
}

var usageItems = [
  {
    type: 1
    name: 'generic-usage-heading'
    conditionalVisibility: usageVisibility
    content: {
      json: '## Project ${projectNumber}${environmentLabel} · Usage\nNative model tokens and HTTP request counts over the **last 30 days**, plus current project inventory. Select the metric family supported by your account. Tokens are observed usage, not billed cost; up to 100 model/deployment series per metric. Missing series are unavailable, not measured zero.'
    }
  }
  {
    type: 9
    name: 'generic-native-selectors'
    conditionalVisibility: usageVisibility
    content: {
      version: 'KqlParameterItem/1.0'
      style: 'above'
      parameters: [
        {
          id: 'generic-account'
          name: 'GenericAccount'
          label: 'Foundry / OpenAI account in this project'
          version: 'KqlParameterItem/1.0'
          type: 2
          isRequired: true
          multiSelect: false
          value: ''
          queryType: 1
          resourceType: 'microsoft.resourcegraph/resources'
          crossComponentResources: [projectResourceGroupId]
          typeSettings: { additionalResourceOptions: [], showDefault: false }
          query: '${scopedAccounts}\n| summarize Accounts=make_list(pack(\'id\', id, \'name\', name, \'kind\', [\'kind\']))\n| extend Accounts=iff(array_length(Accounts) == 1, Accounts, array_concat(pack_array(pack(\'id\', \'\', \'name\', \'Select one discovered account\', \'kind\', \'\')), Accounts))\n| mv-expand Account=Accounts\n| project value=tostring(Account.id), label=iff(isempty(tostring(Account.id)), \'Select one discovered account\', strcat(tostring(Account.name), \' (\', tostring(Account[\'kind\']), \')\')), selected=array_length(Accounts) == 1 or isempty(tostring(Account.id))\n| order by label asc'
        }
        {
          id: 'generic-metric-account'
          name: 'GenericMetricAccount'
          version: 'KqlParameterItem/1.0'
          type: 1
          isHiddenWhenLocked: true
          isRequired: false
          value: ''
          queryType: 1
          resourceType: 'microsoft.resourcegraph/resources'
          crossComponentResources: [projectResourceGroupId]
          // JSON escaping inside a double-quoted KQL literal prevents selection injection.
          // Re-query the immutable RG scope; never bind Metrics to the raw dropdown.
          // https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-parameters#escape-json
          query: '${scopedAccounts}\n| where id =~ "{GenericAccount:escapejson}"\n| summarize Selected=make_list(id)\n| project value=iff(array_length(Selected) == 1, tostring(Selected[0]), \'\')'
        }
        {
          id: 'generic-metric-profile'
          name: 'GenericMetricProfile'
          label: 'Native metric family'
          type: 2
          isRequired: true
          value: 'foundry'
          jsonData: string([
            { value: 'foundry', label: 'Foundry / Models · InputTokens / OutputTokens' }
            { value: 'openai', label: 'Standard Azure OpenAI · ProcessedPromptTokens / GeneratedTokens' }
          ])
        }
      ]
    }
  }
  {
    type: 12
    name: 'generic-native-tokens'
    conditionalVisibility: usageVisibility
    content: {
      version: 'NotebookGroup/1.0'
      groupType: 'editable'
      items: nativeMetricGroups
    }
  }
  {
    type: 12
    name: 'generic-http-optional'
    conditionalVisibility: usageVisibility
    content: {
      version: 'NotebookGroup/1.0'
      groupType: 'editable'
      loadType: 'explicit'
      loadButtonText: 'Show optional Application Insights HTTP requests'
      items: [
        {
          type: 1
          name: 'generic-http-heading'
          content: {
            json: '### Application Insights · HTTP requests\nIndependent application instrumentation; failed requests are a subset of all HTTP requests. An empty HTTP series does not imply no model activity.'
          }
        }
        {
          type: 10
          name: 'generic-http-trend'
          content: union(httpMetricSettings, {
            chartId: 'generic-http-trend'
            title: 'HTTP requests · last 30 days'
            chartType: 2
          })
        }
        {
          type: 10
          name: 'generic-http-totals'
          content: union(httpMetricSettings, {
            chartId: 'generic-http-totals'
            title: 'HTTP requests · 30-day totals'
            chartType: 0
            gridFormatType: 2
          })
        }
      ]
    }
  }
  {
    type: 3
    name: 'generic-inventory-types'
    customWidth: '60'
    conditionalVisibility: usageVisibility
    content: union(inventorySettings, {
      title: 'Project resources by service type'
      query: '${scopedInventory}| summarize Resources=count() by Type=type | order by Resources desc'
      visualization: 'barchart'
      chartSettings: { xAxis: 'Type', yAxis: ['Resources'], showLegend: false }
    })
  }
  {
    type: 3
    name: 'generic-inventory-locations'
    customWidth: '40'
    conditionalVisibility: usageVisibility
    content: union(inventorySettings, {
      title: 'Project resources by location'
      query: '${scopedInventory}| summarize Resources=count() by Location=location | order by Resources desc'
      visualization: 'piechart'
      chartSettings: { xAxis: 'Location', yAxis: ['Resources'], showLegend: true }
    })
  }
  {
    type: 3
    name: 'generic-inventory'
    conditionalVisibility: usageVisibility
    content: union(inventorySettings, {
      title: 'Current project resource inventory'
      query: '${scopedInventory}| project Resource=name, Type=type, Kind=kind, Location=location, id | order by Type asc, Resource asc'
      visualization: 'table'
      gridSettings: {
        formatters: [
          { columnMatch: 'Resource', formatter: 7, formatOptions: { linkColumn: 'id', linkTarget: 'Resource' } }
          { columnMatch: 'id', formatter: 5 }
        ]
      }
    })
  }
]

// ARMEndpoint/1.0 is a Workbook read/query data source; this module deploys no resources.
// https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-data-sources#azure-resource-manager
// Fixed response contracts (including column order) verified against this API on 2026-10-08.
// https://learn.microsoft.com/rest/api/cost-management/query/usage?view=rest-cost-management-2025-03-01
var costEndpoint = {
  version: 'ARMEndpoint/1.0'
  method: 'POST'
  path: '${projectResourceGroupId}/providers/Microsoft.CostManagement/query'
  headers: []
  urlParams: [{ key: 'api-version', value: '2025-03-01' }]
  batchDisabled: false
}
var costAggregation = { totalCost: { name: 'Cost', function: 'Sum' } }
var totalDataset = { granularity: 'None', aggregation: costAggregation }
var dailyDataset = { granularity: 'Daily', aggregation: costAggregation }
var servicesDataset = {
  granularity: 'None'
  aggregation: costAggregation
  grouping: [{ type: 'Dimension', name: 'ServiceName' }]
}
var totalColumns = [
  { path: '$[0]', columnid: 'Cost' }
  { path: '$[1]', columnid: 'Currency' }
]
var dailyColumns = [
  { path: '$[0]', columnid: 'Cost' }
  {
    path: '$[1]'
    columnid: 'UsageDate'
    // https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-jsonpath#use-regular-expressions-to-convert-values
    columnType: 'datetime'
    substringRegexMatch: '([0-9]{4})([0-9]{2})([0-9]{2})'
    substringReplace: '$1-$2-$3'
  }
  { path: '$[2]', columnid: 'Currency' }
]
var servicesColumns = [
  { path: '$[0]', columnid: 'Cost' }
  { path: '$[1]', columnid: 'ServiceName' }
  { path: '$[2]', columnid: 'Currency' }
]
var costProfiles = [
  {
    key: 'total'
    title: 'Actual cost · month to date'
    dataset: totalDataset
    columns: totalColumns
    schema: 'Cost:Number, Currency:String'
  }
  {
    key: 'daily'
    title: 'Daily actual cost · month to date'
    dataset: dailyDataset
    columns: dailyColumns
    schema: 'Cost:Number, UsageDate:Number, Currency:String'
  }
  {
    key: 'services'
    title: 'Actual cost by service · month to date'
    dataset: servicesDataset
    columns: servicesColumns
    schema: 'Cost:Number, ServiceName:String, Currency:String'
  }
]
var costQueries = [for profile in costProfiles: string(union(costEndpoint, {
  data: string({ type: 'ActualCost', timeframe: 'MonthToDate', dataset: profile.dataset })
  transformers: [
    {
      type: 'jsonpath'
      settings: { tablePath: '$.properties.rows', columns: profile.columns }
    }
  ]
}))]
var costSettings = {
  version: 'KqlItem/1.0'
  queryType: 12
  size: 0
  noDataMessage: 'No billing rows returned for this project and month. Cost is unavailable, not zero.'
}
var costSchemaItems = [for profile in costProfiles: {
  type: 3
  name: 'generic-cost-schema-${profile.key}'
  content: union(costSettings, {
    title: '${profile.title} · expected columns: ${profile.schema}'
    visualization: 'table'
    query: string(union(costEndpoint, {
      data: string({ type: 'ActualCost', timeframe: 'MonthToDate', dataset: profile.dataset })
      transformers: [
        {
          type: 'jsonpath'
          settings: {
            tablePath: '$.properties'
            columns: [
              { path: '$.columns', columnid: 'ReturnedSchema' }
              { path: '$.nextLink', columnid: 'NextPage' }
            ]
          }
        }
      ]
    }))
  })
}]
var costItems = [
  {
    type: 1
    name: 'generic-cost-heading'
    conditionalVisibility: costVisibility
    content: {
      json: '## Project ${projectNumber}${environmentLabel} · Cost\n**ActualCost · month to date** from this project RG. Currency comes from billing; missing amounts remain unavailable. **USD display fallback when no currency is emitted.**'
    }
  }
  {
    type: 3
    name: 'generic-cost-total'
    conditionalVisibility: costVisibility
    content: union(costSettings, {
      title: costProfiles[0].title
      query: costQueries[0]
      visualization: 'tiles'
      tileSettings: {
        titleContent: { columnMatch: 'Currency', formatter: 1 }
        leftContent: { columnMatch: 'Cost', formatter: 1 }
        showBorder: true
        size: 'auto'
      }
    })
  }
  {
    type: 3
    name: 'generic-cost-daily'
    customWidth: '60'
    conditionalVisibility: costVisibility
    content: union(costSettings, {
      title: costProfiles[1].title
      query: costQueries[1]
      visualization: 'timechart'
      chartSettings: { xAxis: 'UsageDate', yAxis: ['Cost'], group: 'Currency', showLegend: true, showMetrics: false }
    })
  }
  {
    type: 3
    name: 'generic-cost-services'
    customWidth: '40'
    conditionalVisibility: costVisibility
    content: union(costSettings, {
      title: costProfiles[2].title
      query: costQueries[2]
      visualization: 'barchart'
      chartSettings: { xAxis: 'ServiceName', yAxis: ['Cost'], group: 'Currency', showLegend: true, showMetrics: false }
    })
  }
  {
    type: 1
    name: 'generic-cost-response-note'
    conditionalVisibility: costVisibility
    content: {
      json: 'Returned rows only. Inspect responses if values look wrong: unexpected order/type is unsupported; a nonempty **NextPage** means a partial response. No currency conversion.'
    }
  }
  {
    type: 12
    name: 'generic-cost-response-inspection'
    conditionalVisibility: costVisibility
    content: {
      version: 'NotebookGroup/1.0'
      groupType: 'editable'
      loadType: 'explicit'
      loadButtonText: 'Inspect billing response schema / pagination'
      items: costSchemaItems
    }
  }
]

output items array = concat(usageItems, costItems)
