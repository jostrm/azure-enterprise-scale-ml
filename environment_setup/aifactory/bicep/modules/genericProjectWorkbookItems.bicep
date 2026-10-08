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
          size: 1
          chartType: 3
          metrics: profile.metrics
        })
      }
    ]
  }
}]
var nativeMetricDetails = [for profile in nativeMetricProfiles: {
  type: 10
  name: 'generic-native-${profile.key}-table'
  conditionalVisibility: { parameterName: 'GenericMetricProfile', comparison: 'isEqualTo', value: profile.key }
  content: union(nativeMetricSettings, {
    chartId: 'generic-native-${profile.key}-table'
    title: '${profile.label} · token usage by deployment / model version'
    chartType: 0
    gridFormatType: 2
    metrics: profile.metrics
  })
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
      json: '## Project ${projectNumber}${environmentLabel} · Usage\n30-day observed tokens (up to 100 series per metric, not billed cost) and current resources; missing means unavailable, not zero.'
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
    type: 3
    name: 'generic-inventory-summary'
    conditionalVisibility: usageVisibility
    content: union(inventorySettings, {
      title: 'Current project footprint · visible resources'
      size: 4
      query: '${scopedInventory}| summarize ResourceCount=count(), Types=make_set(type), Locations=make_set(location), Accounts=countif(type =~ \'microsoft.cognitiveservices/accounts\' and [\'kind\'] in~ (\'AIServices\', \'OpenAI\'))\n| extend Counters=pack_array(pack(\'Label\', \'Resources\', \'Value\', ResourceCount), pack(\'Label\', \'Service types\', \'Value\', array_length(Types)), pack(\'Label\', \'Locations\', \'Value\', array_length(Locations)), pack(\'Label\', \'Foundry / OpenAI accounts\', \'Value\', Accounts))\n| mv-expand Counter=Counters\n| project Label=tostring(Counter.Label), Value=toint(Counter.Value)'
      visualization: 'tiles'
      tileSettings: {
        titleContent: { columnMatch: 'Label', formatter: 1 }
        leftContent: {
          columnMatch: 'Value'
          formatter: 12
          numberFormat: { unit: 0, options: { style: 'decimal', useGrouping: true, maximumFractionDigits: 0 } }
        }
        showBorder: true
        size: 'auto'
      }
    })
  }
  {
    type: 12
    name: 'generic-native-tokens'
    customWidth: '50'
    conditionalVisibility: usageVisibility
    content: {
      version: 'NotebookGroup/1.0'
      groupType: 'editable'
      items: nativeMetricGroups
    }
  }
  {
    type: 3
    name: 'generic-inventory-map'
    customWidth: '50'
    conditionalVisibility: usageVisibility
    content: union(inventorySettings, {
      title: 'Azure regions · excludes global / unmapped'
      size: 1
      query: '${scopedInventory}| where isnotempty(location) and location !~ \'global\'\n| summarize Resources=count() by Location=location | order by Resources desc'
      visualization: 'map'
      // Native Azure-location lookup; global/unmapped locations remain in the breakdown and details.
      // Microsoft Application-Insights-Workbooks: CosmosDbOverview.workbook, mapSettings.
      mapSettings: {
        locInfo: 'AzureLoc'
        locInfoColumn: 'Location'
        sizeSettings: 'Resources'
        sizeAggregation: 'Sum'
        legendMetric: 'Resources'
        legendAggregation: 'Sum'
        itemColorSettings: {
          type: 'heatmap'
          nodeColorField: 'Resources'
          colorAggregation: 'Sum'
          heatmapPalette: 'greenRed'
        }
      }
    })
  }
  {
    type: 3
    name: 'generic-inventory-types'
    customWidth: '50'
    conditionalVisibility: usageVisibility
    content: union(inventorySettings, {
      title: 'Resources by service provider / location'
      size: 1
      query: '${scopedInventory}| extend Provider=replace_string(tostring(split(type, \'/\')[0]), \'microsoft.\', \'\')\n| summarize Resources=count() by Provider, Location=location | order by Resources desc'
      visualization: 'categoricalbar'
      chartSettings: { xAxis: 'Provider', yAxis: ['Resources'], group: 'Location', createOtherGroup: 0, showLegend: true, showMetrics: false }
    })
  }
  {
    type: 3
    name: 'generic-inventory-locations'
    customWidth: '50'
    conditionalVisibility: usageVisibility
    content: union(inventorySettings, {
      title: 'Location share · includes global / unmapped'
      size: 1
      query: '${scopedInventory}| summarize Resources=count() by Location=location | order by Resources desc'
      visualization: 'piechart'
      chartSettings: { xAxis: 'Location', yAxis: ['Resources'], createOtherGroup: 0, showLegend: true, showMetrics: false }
    })
  }
  {
    type: 12
    name: 'generic-native-details'
    conditionalVisibility: usageVisibility
    content: {
      version: 'NotebookGroup/1.0'
      groupType: 'editable'
      loadType: 'explicit'
      loadButtonText: 'Show token totals by deployment / model version'
      items: nativeMetricDetails
    }
  }
  {
    type: 12
    name: 'generic-inventory-details'
    conditionalVisibility: usageVisibility
    content: {
      version: 'NotebookGroup/1.0'
      groupType: 'editable'
      loadType: 'explicit'
      loadButtonText: 'Show current resource inventory'
      items: [
        {
          type: 3
          name: 'generic-inventory'
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
          customWidth: '50'
          content: union(httpMetricSettings, {
            chartId: 'generic-http-trend'
            title: 'HTTP requests · last 30 days'
            chartType: 2
          })
        }
        {
          type: 10
          name: 'generic-http-totals'
          customWidth: '50'
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
]

// ARMEndpoint/1.0 is a Workbook read/query data source; this module deploys no resources.
// https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-data-sources#azure-resource-manager
// Positional contracts must match returned columns; the optional inspector exposes schema/pagination.
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
var dailyServicesDataset = union(servicesDataset, { granularity: 'Daily' })
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
var dailyServicesColumns = [
  // Daily ServiceName column order verified against the API on 2026-10-08.
  { path: '$[0]', columnid: 'Cost' }
  dailyColumns[1]
  { path: '$[2]', columnid: 'ServiceName' }
  { path: '$[3]', columnid: 'Currency' }
]
var costProfiles = [
  {
    key: 'total'
    title: 'Actual cost · month to date'
    dataset: totalDataset
    columns: totalColumns
    schema: 'Cost:Number, Currency:String'
    currencyColumn: 1
  }
  {
    key: 'daily'
    title: 'Daily actual cost · month to date'
    dataset: dailyDataset
    columns: dailyColumns
    schema: 'Cost:Number, UsageDate:Number, Currency:String'
    currencyColumn: 2
  }
  {
    key: 'services'
    title: 'Actual cost by service · month to date'
    dataset: servicesDataset
    columns: servicesColumns
    schema: 'Cost:Number, ServiceName:String, Currency:String'
    currencyColumn: 2
  }
  {
    key: 'daily-services'
    title: 'Daily actual cost by service · month to date'
    dataset: dailyServicesDataset
    columns: dailyServicesColumns
    schema: 'Cost:Number, UsageDate:Number, ServiceName:String, Currency:String'
    currencyColumn: 3
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
// Service compositions use one returned currency; unfiltered totals/details retain every currency and credit.
var selectedCostQueries = [for profile in costProfiles: string(union(costEndpoint, {
  data: string({ type: 'ActualCost', timeframe: 'MonthToDate', dataset: profile.dataset })
  transformers: [
    {
      type: 'jsonpath'
      settings: {
        tablePath: '$.properties.rows[?(@[${profile.currencyColumn}] == "{GenericCostCurrency:escapejson}")]'
        columns: profile.columns
      }
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
      json: '## Project ${projectNumber}${environmentLabel} · Cost\n**ActualCost · month to date** from this project RG. Currency comes from billing; missing amounts remain unavailable. **USD display fallback when no currency is emitted.** Totals and daily trends retain every returned currency; service visuals use the selected currency. Negative credits remain signed amounts, never pie shares. No budget source is configured.'
    }
  }
  {
    type: 9
    name: 'generic-cost-currency'
    conditionalVisibility: costVisibility
    content: {
      version: 'KqlParameterItem/1.0'
      style: 'above'
      parameters: [
        {
          id: 'generic-cost-currency'
          name: 'GenericCostCurrency'
          label: 'Billing currency · service visuals only'
          type: 2
          isRequired: true
          multiSelect: false
          // Native "Any one" resolves one returned value, never a hardcoded currency or All.
          // https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-dropdowns#dropdown-special-selections
          defaultValue: 'value::1'
          queryType: 12
          typeSettings: { additionalResourceOptions: ['value::1'], showDefault: false }
          query: string(union(costEndpoint, {
            data: string({ type: 'ActualCost', timeframe: 'MonthToDate', dataset: totalDataset })
            transformers: [
              {
                type: 'jsonpath'
                settings: {
                  tablePath: '$.properties.rows'
                  columns: [
                    { path: '$[1]', columnid: 'value' }
                    { path: '$[1]', columnid: 'label' }
                  ]
                }
              }
            ]
          }))
        }
      ]
    }
  }
  {
    type: 3
    name: 'generic-cost-total'
    customWidth: '30'
    conditionalVisibility: costVisibility
    content: union(costSettings, {
      title: costProfiles[0].title
      query: costQueries[0]
      visualization: 'tiles'
      tileSettings: {
        titleContent: { columnMatch: 'Currency', formatter: 1 }
        leftContent: {
          columnMatch: 'Cost'
          formatter: 12
          numberFormat: {
            unit: 0
            options: { style: 'decimal', useGrouping: true, minimumFractionDigits: 2, maximumFractionDigits: 2 }
          }
        }
        showBorder: true
        size: 'auto'
      }
    })
  }
  {
    type: 3
    name: 'generic-cost-services'
    customWidth: '70'
    conditionalVisibility: costVisibility
    content: union(costSettings, {
      title: '${costProfiles[2].title} · {GenericCostCurrency}'
      query: selectedCostQueries[2]
      visualization: 'barchart'
      noDataMessage: 'Select a returned billing currency. No matching service cost is unavailable, not zero; all currencies remain in billing details.'
      chartSettings: { xAxis: 'ServiceName', yAxis: ['Cost'], createOtherGroup: 0, showLegend: false, showMetrics: false }
    })
  }
  {
    type: 3
    name: 'generic-cost-daily'
    customWidth: '50'
    conditionalVisibility: costVisibility
    content: union(costSettings, {
      title: '${costProfiles[1].title} · separate currency series'
      query: costQueries[1]
      size: 1
      visualization: 'timechart'
      chartSettings: { xAxis: 'UsageDate', yAxis: ['Cost'], group: 'Currency', createOtherGroup: 0, showLegend: true, showMetrics: false }
    })
  }
  {
    type: 3
    name: 'generic-cost-daily-services'
    customWidth: '50'
    conditionalVisibility: costVisibility
    content: union(costSettings, {
      title: '${costProfiles[3].title} · {GenericCostCurrency}'
      query: selectedCostQueries[3]
      size: 1
      visualization: 'areachart'
      noDataMessage: 'Select a returned billing currency. No matching daily service cost is unavailable, not zero; all currencies remain in billing details.'
      chartSettings: { xAxis: 'UsageDate', yAxis: ['Cost'], group: 'ServiceName', createOtherGroup: 0, showLegend: true, showMetrics: false }
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
    name: 'generic-cost-details'
    conditionalVisibility: costVisibility
    content: {
      version: 'NotebookGroup/1.0'
      groupType: 'editable'
      loadType: 'explicit'
      loadButtonText: 'Show billing rows · all currencies and credits'
      items: [
        {
          type: 3
          name: 'generic-cost-services-details'
          content: union(costSettings, {
            title: '${costProfiles[2].title} · all currencies'
            query: costQueries[2]
            visualization: 'table'
          })
        }
        {
          type: 3
          name: 'generic-cost-daily-services-details'
          content: union(costSettings, {
            title: '${costProfiles[3].title} · all currencies'
            query: costQueries[3]
            visualization: 'table'
          })
        }
      ]
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
