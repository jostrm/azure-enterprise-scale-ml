@description('Creates only a saved workbook. Existing telemetry, permissions and instrumentation must already be available.')
param location string
param projectNumber string
param env string
param telemetryEnvironment string
param applicationInsightsResourceId string
param logAnalyticsResourceId string
param projectResourceGroupId string
@description('Opaque canonical telemetry identity. Empty requires an explicit selection from scoped observations.')
param factoryId string = ''
param scaleSetId string = ''
@description('IANA time zone, not a fixed UTC offset.')
param timeZone string = 'Europe/Berlin'
@description('Explicit reviewed completeness for questions/devices/feedback/cart/bookings/cases/stateBaseline/metering/billing. Omitted channels remain unavailable.')
param coverage object = {}
@minValue(30)
@maxValue(90)
@description('Bounded state history ending at the selected exclusive end. Completeness additionally requires a reviewed full baseline inside this bound.')
param stateHistoryDays int = 90
param tags object = {}

var workbookName = guid(resourceGroup().id, 'aifactory.my-project.v1', projectNumber, env)
var workbookId = resourceId('Microsoft.Insights/workbooks', workbookName)
var workbookUrl = 'https://portal.azure.com/#@${tenant().tenantId}/resource${workbookId}'
var tokenLinkParameters = { Navigation: 'tokens' }
var tokensUrl = 'https://portal.azure.com/#@${tenant().tenantId}/blade/AppInsightsExtension/WorkbookViewerBlade/ComponentId/${uriComponent(applicationInsightsResourceId)}/ConfigurationId/${uriComponent(workbookId)}/Type/workbook/NotebookParams/${uriComponent(string(tokenLinkParameters))}'
var insightsUrl = 'https://portal.azure.com/#@${tenant().tenantId}/resource${applicationInsightsResourceId}/logs'
var workspaceUrl = 'https://portal.azure.com/#@${tenant().tenantId}/resource${logAnalyticsResourceId}/logs'
var costUrl = 'https://portal.azure.com/@${tenant().tenantId}/#blade/Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/${uriComponent(projectResourceGroupId)}'
var fixedContext = replace(replace(replace(replace(
  loadTextContent('./workbooks/my-project/context.kql'),
  '__COMPONENT__', base64(applicationInsightsResourceId)),
  '__PROJECT__', base64(projectNumber)),
  '__ENVIRONMENT__', base64(telemetryEnvironment)),
  '__HISTORY_DAYS__', string(stateHistoryDays))
var usageQuery = '${fixedContext}\n${loadTextContent('./workbooks/my-project/usage.kql')}\n'
var costQuery = '${fixedContext}\n${loadTextContent('./workbooks/my-project/cost.kql')}\n'
var tokenContext = replace(loadTextContent('./workbooks/my-project/tokens-context.kql'), '__PROJECT_RG__', base64(projectResourceGroupId))
var tokenQuery = '${tokenContext}\n${loadTextContent('./workbooks/my-project/tokens.kql')}\n'
var tokenReportQuery = '${tokenQuery}${loadTextContent('./workbooks/my-project/tokens-report.kql')}\n'
var tokenAccountDiscovery = '''
Resources
| where type =~ 'microsoft.cognitiveservices/accounts'
| where ['kind'] in~ ('AIServices', 'OpenAI')
| where tolower(id) startswith '__ACCOUNT_PREFIX__'
| where array_length(split(id, '/')) == 9
'''
var tokenAccounts = replace(tokenAccountDiscovery, '__ACCOUNT_PREFIX__', toLower('${projectResourceGroupId}/providers/Microsoft.CognitiveServices/accounts/'))
var tokenArgSettings = {
  version: 'KqlParameterItem/1.0'
  queryType: 1
  resourceType: 'microsoft.resourcegraph/resources'
  crossComponentResources: [projectResourceGroupId]
  typeSettings: { additionalResourceOptions: [], showDefault: false }
}
var discoveryQuery = '''
AppEvents
| where tolower(_ResourceId) == tolower(base64_decode_tostring('__COMPONENT__'))
| where Name in ('aifactory.chat', 'aifactory.chat.meter')
| where TimeGenerated >= ago(90d) and TimeGenerated <= now()
| where tostring(Properties['project']) == base64_decode_tostring('__PROJECT__')
    and tostring(Properties.environment) == base64_decode_tostring('__ENVIRONMENT__')
| extend factory=tostring(Properties.factory), scaleset=tostring(Properties.scaleset), store=tostring(Properties.store)
| where isnotempty(factory) and isnotempty(scaleset)
    and factory == trim(@'\s+', factory) and scaleset == trim(@'\s+', scaleset)
    and tolower(factory) !in ('all', 'unknown', 'unavailable', 'n/a', 'none', 'null', '*')
    and tolower(scaleset) !in ('all', 'unknown', 'unavailable', 'n/a', 'none', 'null', '*')
'''
var discovery = replace(replace(replace(discoveryQuery, '__COMPONENT__', base64(applicationInsightsResourceId)), '__PROJECT__', base64(projectNumber)), '__ENVIRONMENT__', base64(telemetryEnvironment))
var querySettings = {
  version: 'KqlItem/1.0'
  queryType: 0
  resourceType: 'microsoft.operationalinsights/workspaces'
  crossComponentResources: [logAnalyticsResourceId]
  // No workbook timespan binding: the KQL owns inclusive local dates and baseline history.
  timeContext: { durationMs: 0 }
  size: 0
  visualization: 'table'
  noDataMessage: 'No matching observations. Missing scope, instrumentation or coverage is unavailable, not a known zero.'
}
var dropdownQuerySettings = {
  version: 'KqlParameterItem/1.0'
  type: 2
  isRequired: true
  queryType: 0
  resourceType: 'microsoft.operationalinsights/workspaces'
  crossComponentResources: [logAnalyticsResourceId]
  timeContext: { durationMs: 0 }
  typeSettings: {
    additionalResourceOptions: []
    showDefault: false
  }
}
var coverageDefaults = union({
  questions: false
  devices: false
  feedback: false
  cart: false
  bookings: false
  cases: false
  stateBaseline: false
  metering: false
  billing: false
}, coverage)
var coverageFields = [
  { key: 'questions', name: 'QuestionsComplete', label: 'Questions complete' }
  { key: 'devices', name: 'DevicesComplete', label: 'Pseudonymous devices complete' }
  { key: 'feedback', name: 'FeedbackComplete', label: 'Feedback complete' }
  { key: 'cart', name: 'CartComplete', label: 'Cart complete' }
  { key: 'bookings', name: 'BookingsComplete', label: 'Bookings complete' }
  { key: 'cases', name: 'CasesComplete', label: 'Cases complete' }
  { key: 'stateBaseline', name: 'StateBaselineComplete', label: 'Full state baseline reviewed' }
  { key: 'metering', name: 'MeteringComplete', label: 'Estimated metering complete' }
  { key: 'billing', name: 'BillingComplete', label: 'Actual/allocated evidence complete' }
]
var coverageParameters = [for field in coverageFields: {
  id: field.key
  version: 'KqlParameterItem/1.0'
  name: field.name
  label: field.label
  description: 'Explicit reviewed completeness for the selected scope/store/period. Never infer true from an empty result or from the presence of events.'
  type: 2
  isRequired: true
  value: coverageDefaults[field.key] ? 'true' : 'false'
  // ARM copy expansion re-evaluates a leading "["; whitespace is valid JSON and prevents that.
  jsonData: concat(' ', string([{ value: 'false', label: 'False — unreviewed / unavailable' }, { value: 'true', label: 'True — reviewed complete' }]))
}]
var usageVisibility = { parameterName: 'Navigation', comparison: 'isEqualTo', value: 'usage' }
var costVisibility = { parameterName: 'Navigation', comparison: 'isEqualTo', value: 'cost' }
var tokenVisibility = { parameterName: 'Navigation', comparison: 'isEqualTo', value: 'tokens' }
// First-party working examples (not schema alone):
// Workbooks/Azure Machine Learning/AI Studio/AtResource/AI-Studio-Insights.workbook
// Workbooks/EventHub/AtScale/Insights.workbook, in microsoft/Application-Insights-Workbooks.
// MetricsItem/2.0: aggregation 1=Total, chartType 0=grid / 2=line, gridFormatType 2=dimensions.
var tokenMetricSettings = {
  version: 'MetricsItem/2.0'
  size: 0
  resourceType: 'microsoft.cognitiveservices/accounts'
  metricScope: 0
  resourceParameter: 'TokenMetricAccount'
  resourceIds: ['{TokenMetricAccount}']
  resourceLimit: 1
  timeContextFromParameter: 'TokenTimeRange'
  timeContext: { durationMs: 604800000 }
  gridSettings: { rowLimit: 10000 }
}
var tokenMetricProfiles = loadJsonContent('./workbooks/my-project/tokens-metrics.json')
var tokenMetricTables = [for profile in tokenMetricProfiles: {
  type: 10
  name: 'tokens-native-${profile.key}-table'
  conditionalVisibility: { parameterName: 'TokenMetricView', comparison: 'isEqualTo', value: profile.key }
  content: union(tokenMetricSettings, {
    chartId: 'tokens-native-${profile.key}-table'
    title: '${profile.label} — native Total by deployment / model version'
    chartType: 0
    gridFormatType: 2
    metrics: profile.metrics
  })
}]
var tokenMetricTrends = [for profile in tokenMetricProfiles: {
  type: 10
  name: 'tokens-native-${profile.key}-trend'
  conditionalVisibility: { parameterName: 'TokenMetricView', comparison: 'isEqualTo', value: profile.key }
  content: union(tokenMetricSettings, {
    chartId: 'tokens-native-${profile.key}-trend'
    title: '${profile.label} — native time series (service time grain)'
    chartType: 2
    metrics: profile.metrics
  })
}]
var tokenCachedMetric = {
  namespace: 'microsoft.cognitiveservices/accounts'
  metric: 'microsoft.cognitiveservices/accounts-Models  Usage-cacheReadInputTokens'
  aggregation: 1
  splitBy: ['ModelDeploymentName', 'ModelName', 'ModelVersion']
  splitByLimit: 100
  columnName: 'Cached input tokens (subset; missing series is unavailable)'
}
var tileSettings = {
  titleContent: { columnMatch: 'Metric', formatter: 1 }
  leftContent: { columnMatch: 'DisplayValue', formatter: 1 }
  subtitleContent: { columnMatch: 'Unit', formatter: 1 }
  secondaryContent: { columnMatch: 'Availability', formatter: 1 }
  showBorder: true
  size: 'auto'
}
var commonCharts = [
  {
    name: 'conversations-questions-daily'
    title: 'Conversations and questions per local day'
    projection: 'Daily | project Day, Conversations, Questions'
    columns: ['Conversations', 'Questions']
  }
  {
    name: 'feedback-daily'
    title: 'Customer feedback per local day (latest in-window vote)'
    projection: 'Daily | project Day, Up, Down'
    columns: ['Up', 'Down']
  }
  {
    name: 'questions-per-conversation-daily'
    title: 'Questions per conversation per local day'
    projection: 'Daily | project Day, QuestionsPerConversation'
    columns: ['QuestionsPerConversation']
  }
]
var chartItems = [for chart in commonCharts: {
  type: 3
  name: chart.name
  conditionalVisibility: usageVisibility
  content: union(querySettings, {
    title: chart.title
    query: '${usageQuery}${chart.projection}'
    visualization: 'timechart'
    chartSettings: { xAxis: 'Day', yAxis: chart.columns, showLegend: true }
  })
}]
var sourceQuery = '''
union
 (print Source='Project Application Insights — aifactory.chat / aifactory.chat.meter', Url=base64_decode_tostring('__INSIGHTS_URL__')),
 (print Source='Existing shared Log Analytics workspace — queries enforce exact component and dimensions', Url=base64_decode_tostring('__WORKSPACE_URL__')),
 (print Source='Native Azure Cost Management — project RG (independent native date/basis/currency controls)', Url=base64_decode_tostring('__COST_URL__'))
'''
var workbook = {
  version: 'Notebook/1.0'
  '$schema': 'https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json'
  fallbackResourceIds: [logAnalyticsResourceId]
  items: concat([
    {
      type: 1
      name: 'my-project-heading'
      content: {
        json: '# My Project ${projectNumber} · ${toUpper(env)}\n\n**Fixed telemetry project:** `${projectNumber}` · **environment:** `${telemetryEnvironment}`. This saved Azure-native workbook uses existing telemetry; it creates no workspace, collector, ingestion pipeline, diagnostic setting or role assignment. Native model calls are not user questions; no model metrics are substituted for business events.\n\n**Usage & Cost:** select the canonical factory and scale set, not an RG-derived label. Selectors discover this component/project/environment in the last 90 days; no missing selection broadens to All. **Store All** is allowed only within this exact project scope.\n\n**Model tokens:** independent native Foundry / Azure OpenAI account metrics and request-usage logs, scoped to this exact project RG. Factory, scale set, store, business dates and coverage declarations do not gate tokens. Select View = Model tokens below.'
      }
    }
    {
      type: 9
      name: 'navigation-and-filters'
      content: {
        version: 'KqlParameterItem/1.0'
        style: 'above'
        parameters: [
          {
            id: 'navigation'
            name: 'Navigation'
            label: 'View'
            type: 2
            isRequired: true
            isGlobal: true
            value: 'usage'
            jsonData: string([{ value: 'usage', label: 'Usage & outcomes' }, { value: 'cost', label: 'Cost' }, { value: 'tokens', label: 'Model tokens' }])
          }
          {
            id: 'template'
            name: 'Template'
            type: 2
            isRequired: true
            value: 'retail-chat'
            jsonData: string([{ value: 'retail-chat', label: 'Retail' }, { value: 'booking-chat', label: 'Booking' }, { value: 'support-chat', label: 'Support' }])
          }
          union(dropdownQuerySettings, {
            id: 'time-zone'
            name: 'TimeZone'
            label: 'Time zone (IANA / DST aware)'
            value: timeZone
            query: 'print Zones=datetime_list_timezones() | mv-expand Zones | project value=tostring(Zones), label=tostring(Zones) | order by label asc'
          })
          {
            id: 'date-preset'
            name: 'DatePreset'
            label: 'Inclusive local dates'
            type: 2
            isRequired: true
            value: '7'
            jsonData: string([{ value: '1', label: 'Today (1 day)' }, { value: '7', label: 'Last 7 days' }, { value: '30', label: 'Last 30 days' }, { value: 'custom', label: 'Custom (maximum 30 dates)' }])
          }
          {
            id: 'from-date'
            name: 'FromDate'
            label: 'Custom from (YYYY-MM-DD, inclusive)'
            description: 'Used only for Custom. Local calendar date in the selected IANA time zone.'
            type: 1
            value: ''
          }
          {
            id: 'to-date'
            name: 'ToDate'
            label: 'Custom to (YYYY-MM-DD, inclusive)'
            description: 'Used only for Custom. At most 30 inclusive dates; invalid/reversed ranges produce no metrics.'
            type: 1
            value: ''
          }
          union(dropdownQuerySettings, {
            id: 'factory'
            name: 'Factory'
            label: 'Canonical factory (required)'
            value: factoryId
            query: '${discovery}\n| distinct factory\n| project value=factory, label=factory, selected=(factory == base64_decode_tostring(\'${base64(factoryId)}\'))\n| union (print value=base64_decode_tostring(\'${base64(factoryId)}\') | where isnotempty(value) | project value, label=value, selected=true)\n| union (print value=\'\', label=\'Select canonical factory (required)\', selected=isempty(base64_decode_tostring(\'${base64(factoryId)}\')))\n| distinct value, label, selected'
          })
          union(dropdownQuerySettings, {
            id: 'scale-set'
            name: 'ScaleSet'
            label: 'Canonical scale set (required)'
            value: scaleSetId
            query: '${discovery}\n| where factory == base64_decode_tostring(\'{Factory:base64}\')\n| distinct scaleset\n| project value=scaleset, label=scaleset, selected=(scaleset == base64_decode_tostring(\'${base64(scaleSetId)}\'))\n| union (print value=base64_decode_tostring(\'${base64(scaleSetId)}\') | where isnotempty(value) | project value, label=value, selected=true)\n| union (print value=\'\', label=\'Select canonical scale set (required)\', selected=isempty(base64_decode_tostring(\'${base64(scaleSetId)}\')))\n| distinct value, label, selected'
          })
          union(dropdownQuerySettings, {
            id: 'store'
            name: 'Store'
            value: 'All'
            query: '${discovery}\n| where factory == base64_decode_tostring(\'{Factory:base64}\') and scaleset == base64_decode_tostring(\'{ScaleSet:base64}\')\n| where isnotempty(store) and tolower(store) !in (\'all\', \'unknown\', \'unavailable\', \'n/a\', \'none\', \'null\', \'*\')\n| distinct store\n| project value=store, label=store\n| union (print value=\'All\', label=\'All stores in this exact scope\')'
          })
        ]
      }
    }
    {
      type: 1
      name: 'coverage-explanation'
      content: {
        json: '### Coverage is an explicit declaration, not data health\n\nAll channels default to **false / unavailable**. Change them only after reviewing instrumentation completeness for this **exact scope, store and date range**; re-review after changing filters. Absence of telemetry never establishes completeness. Sampled events, invalid evidence and conflicting duplicate identities invalidate results. Query/service failures remain errors, not zero. No prompts, chat text, device values, phone values or raw IP fields are projected to results.\n\n**State history:** at most ${stateHistoryDays} local dates before selected end. Bookings/cases require both the channel declaration and a reviewed full baseline in this bound; entities created earlier must have a baseline snapshot in this window. Otherwise status totals are unavailable.'
      }
    }
    {
      type: 1
      name: 'native-rg-cost-navigation'
      content: {
        json: '### Azure resource-group Cost Analysis — actual & forecast\n\n[Open Azure Cost Analysis for Project ${projectNumber}](${costUrl} "Actual Azure cost and Azure forecast for this exact resource group")\n\n**Scope:** `${projectResourceGroupId}`. **Data source:** Azure Cost Management, not Log Analytics or app-meter estimates. The project portal dashboard includes the native accumulated ActualCost chart with Azure forecast enabled for this month. Cost Analysis has its own period, basis and currency controls; workbook store/session filters and coverage declarations do not affect RG billing. Forecast is a prediction, never a billed actual, and may be unavailable when Azure has insufficient history.'
      }
    }
    {
      type: 9
      name: 'reviewed-coverage'
      content: {
        version: 'KqlParameterItem/1.0'
        style: 'above'
        parameters: coverageParameters
      }
    }
    {
      type: 3
      name: 'source-links'
      content: union(querySettings, {
        title: 'Data sources — exact native ARM scopes'
        query: replace(replace(replace(sourceQuery, '__INSIGHTS_URL__', base64(insightsUrl)), '__WORKSPACE_URL__', base64(workspaceUrl)), '__COST_URL__', base64(costUrl))
        gridSettings: {
          formatters: [{
            columnMatch: 'Source'
            formatter: 1
            formatOptions: { linkColumn: 'Url', linkTarget: 'Url' }
          }]
        }
      })
    }
    {
      type: 3
      name: 'usage-validation'
      conditionalVisibility: usageVisibility
      content: union(querySettings, {
        title: 'Usage source / validation (not a health indicator)'
        query: '${usageQuery}print ScopeSelected=ScopeReady, ValidLocalDates=WindowValid, FromLocal=FirstLocalDate, ThroughLocal=LastLocalDate, TimeZone=Zone, ExclusiveEndUtc=EndUtc, BaselineFromUtc=HistoryStartUtc, ConflictingEventIdentities=EventConflicts, ConflictingQuestions=QuestionConflicts, ConflictingVotes=VoteConflicts, ConflictingStates=StateConflicts, InvalidOrSampledEvents=InvalidEvents, ResultsValid=UsageValid, ObservedQuestions=iff(UsageValid, QuestionCount, long(null)), ObservedQuestionsWithDeviceId=iff(UsageValid, QuestionsWithDevice, long(null)), ObservedDeviceIdCoveragePercent=iff(UsageValid, 100.0 * Ratio(toreal(QuestionsWithDevice), toreal(QuestionCount)), real(null))'
      })
    }
    {
      type: 3
      name: 'common-cards'
      conditionalVisibility: usageVisibility
      content: union(querySettings, {
        title: 'Usage & answer quality — identical across all templates'
        query: '${usageQuery}Metrics | where Section == \'common\' | extend DisplayValue=iff(isnull(Value), \'Unavailable / undefined\', tostring(round(Value, 2)))'
        visualization: 'tiles'
        tileSettings: tileSettings
      })
    }
    {
      type: 3
      name: 'domain-cards'
      conditionalVisibility: usageVisibility
      content: union(querySettings, {
        title: '{Template:label} outcomes'
        query: '${usageQuery}Metrics | where Section == base64_decode_tostring(\'{Template:base64}\') | extend DisplayValue=iff(isnull(Value), \'Unavailable / undefined\', tostring(round(Value, 2)))'
        visualization: 'tiles'
        tileSettings: tileSettings
      })
    }
  ], chartItems, [
    {
      type: 3
      name: 'metric-formulas'
      conditionalVisibility: usageVisibility
      content: union(querySettings, {
        title: 'Visible definitions, formulas and availability'
        query: '${usageQuery}Metrics | where Section == \'common\' or Section == base64_decode_tostring(\'{Template:base64}\') | project Metric, Value, Unit, Availability, Formula, Source'
      })
    }
    {
      type: 1
      name: 'cost-notice'
      conditionalVisibility: costVisibility
      content: {
        json: '## Cost — observed meter evidence, not a real-time invoice\n\nOnly **AppEvents `aifactory.chat.meter`** is read. No automatic Azure billing collector is installed. Actual/allocated amounts are imported or ingested reviewed evidence, not live invoice data. For native billed project cost, use **Azure Cost Management** above (its own dates/basis/currency controls; not a store/session view).\n\n**Never add actual + allocated + estimated**, or different currencies. Estimated = quantity × supplied unit_price ÷ price_unit_quantity; no prices are hardcoded. Actual/allocated = supplied evidenced amount. Allocated requires allocation_method and billing_reference. Session/IP attribution for either requires attribution_reference. Fixed/PTU/reservation costs are separate other-service charges, never token estimates. Tables preserve rate and evidence references; they do not execute links in evidence.\n\nMissing session/network keys stay **Unattributed**. IP groups are upstream pseudonymous `ipkey_` hashes, **not people** (NAT/shared networks/VPNs/rotation). Only validated `session_` and `ipkey_` keys are shown. Cost per observed session uses attributed cost / exact known (store, session_key) identities, not all chat conversations. Charges lacking store cannot match a selected store and prevent a completeness claim. Observed incomplete costs are labeled partial; absent days are null unless reviewed complete. No currency is invented for empty results.'
      }
    }
    {
      type: 3
      name: 'cost-validation'
      conditionalVisibility: costVisibility
      content: union(querySettings, {
        title: 'Meter evidence validation and coverage'
        query: '${costQuery}Bases | project Basis=basis, Complete, ScopeSelected=ScopeReady, ValidLocalDates=WindowValid, ConflictingEventIdentities=CostConflicts, InvalidOrSampledOrUnsafeCharges=InvalidCosts, ResultsValid=CostValid, MissingStorePreventsCompleteness=(Store != \'All\' and not(Complete)), Source=\'AppEvents / aifactory.chat.meter\''
      })
    }
    {
      type: 3
      name: 'cost-summary'
      conditionalVisibility: costVisibility
      content: union(querySettings, {
        title: 'Separate actual / allocated / estimated amounts, by currency'
        query: '${costQuery}CostSummary'
      })
    }
    {
      type: 9
      name: 'chart-currency'
      conditionalVisibility: costVisibility
      content: {
        version: 'KqlParameterItem/1.0'
        style: 'above'
        parameters: [union(dropdownQuerySettings, {
          id: 'chart-currency'
          name: 'ChartCurrency'
          label: 'Chart currency (required; tables retain separate currencies)'
          value: ''
          query: '${costQuery}Pairs | distinct currency | project value=currency, label=currency | union (print value=\'\', label=\'Select one observed currency\', selected=true)'
        })]
      }
    }
    {
      type: 3
      name: 'cost-daily'
      conditionalVisibility: costVisibility
      content: union(querySettings, {
        title: 'Cost per local day — {ChartCurrency:label}, bases never combined'
        query: '${costQuery}DailyCosts | where Currency == base64_decode_tostring(\'{ChartCurrency:base64}\') | project Day, Series=Basis, Cost'
        visualization: 'timechart'
        chartSettings: { xAxis: 'Day', yAxis: ['Cost'], group: 'Series', showLegend: true }
      })
    }
    {
      type: 3
      name: 'cost-service-daily'
      conditionalVisibility: costVisibility
      content: union(querySettings, {
        title: 'Cost per local day by service — {ChartCurrency:label}'
        query: '${costQuery}DailyServiceCosts | where Currency == base64_decode_tostring(\'{ChartCurrency:base64}\') | project Day, Series=strcat(Basis, \' / \', Service), Cost'
        visualization: 'timechart'
        chartSettings: { xAxis: 'Day', yAxis: ['Cost'], group: 'Series', showLegend: true }
      })
    }
    {
      type: 3
      name: 'session-daily'
      conditionalVisibility: costVisibility
      content: union(querySettings, {
        title: 'Cost per day per chat session — missing attribution retained'
        query: '${costQuery}CostRows | summarize Cost=sum(cost) by Day, Store=StoreLabel, Session, Basis=basis, Currency=currency | order by Day asc, Basis asc, Currency asc'
      })
    }
    {
      type: 3
      name: 'network-daily'
      conditionalVisibility: costVisibility
      content: union(querySettings, {
        title: 'Cost per day per pseudonymous IP group — not people'
        query: '${costQuery}CostRows | summarize Cost=sum(cost) by Day, Store=StoreLabel, IPGroup, Basis=basis, Currency=currency | order by Day asc, Basis asc, Currency asc'
      })
    }
    {
      type: 3
      name: 'meter-details'
      conditionalVisibility: costVisibility
      content: union(querySettings, {
        title: 'Meter breakdown — distinct units, rate and evidence references'
        query: '${costQuery}CostRows | summarize Quantity=sum(quantity), Cost=sum(cost), Observations=count() by Day, Store=StoreLabel, Session, IPGroup, service, meter, unit, basis, currency, charge_type, unit_price, price_unit_quantity, rate_reference, evidence_reference, allocation_method, billing_reference, attribution_reference | order by Day asc, basis asc, currency asc'
      })
    }
    {
      type: 1
      name: 'tokens-notice'
      conditionalVisibility: tokenVisibility
      content: {
        json: '## Native model tokens — two separate sources, never added together\n\n**Azure Monitor Metrics** below reads the selected real account directly, without diagnostic exports or business instrumentation. Default **Foundry / Models** uses `InputTokens` and `OutputTokens`, split by `ModelDeploymentName`, `ModelName`, `ModelVersion`. **Standard Azure OpenAI** explicitly uses `ProcessedPromptTokens` / `GeneratedTokens` instead; these do not support a `ModelName` dimension. Select the schema supported by the account — aliases are alternatives, never summed or queried with unsupported dimensions. Tables show up to 100 series per metric, not a guaranteed exhaustive account total. Native trends use the service time grain.\n\n**Cached tokens:** `cacheReadInputTokens` has model-dependent availability (documented for Anthropic); a missing/empty series for an OpenAI model is **Unavailable, not zero**. Its registration in metric definitions does not prove it emitted data. The separate cached table cannot hide input/output if cache is absent. OpenAI request logs may instead emit `prompt_tokens_details.cached_tokens` or `input_tokens_details.cached_tokens`. No cache-hit-rate × input estimate is used. **Input includes its cached subset; never add input + cached.** Values are observed usage, not billable cost or an invoice.\n\n**Request-usage detail** reads only `AzureDiagnostics`, category `AzureOpenAIRequestUsage`, in the configured existing workspace. It never unions Metrics, AppEvents, dependencies or RequestResponse. Per-model/deployment log selectors affect only those log tables, not the native metric tables. Missing dimensions stay `[not emitted]`; no model is guessed from a deployment name. Logged rows need not cover all service traffic. No prompt, completion, request/response body, identity or raw IP is projected.\n\n**Dedicated token time range:** defaults to 7 days; choose at most 31 days. This same window binds native Metrics and request logs. Daily log buckets use the IANA time zone above; partial first/last days remain partial. Business date controls do not affect this report. Invalid account/window selections fail closed; missing sources remain unavailable; service/permission failures remain errors.\n\n[Supported metric names and dimensions](https://learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-cognitiveservices-accounts-metrics) · [Supported diagnostic categories](https://learn.microsoft.com/azure/azure-monitor/reference/supported-logs/microsoft-cognitiveservices-accounts-logs) · [OpenAI cached-token semantics](https://learn.microsoft.com/azure/foundry/openai/how-to/prompt-caching)'
      }
    }
    {
      type: 9
      name: 'tokens-account-and-time'
      conditionalVisibility: tokenVisibility
      content: {
        version: 'KqlParameterItem/1.0'
        style: 'above'
        parameters: [
          union(tokenArgSettings, {
            id: 'token-account-inventory'
            name: 'TokenAccountInventory'
            type: 1
            isHiddenWhenLocked: true
            query: '${tokenAccounts}\n| project id, name, [\'kind\']\n| summarize value=make_list(pack(\'id\', id, \'name\', name, \'kind\', [\'kind\']))'
          })
          union(tokenArgSettings, {
            id: 'token-account'
            name: 'TokenAccount'
            label: 'Native Foundry / OpenAI account in this project RG'
            description: 'A single discovered AIServices/OpenAI account is selected automatically. Choose explicitly when this project has multiple accounts. No All/subscription-wide fallback.'
            type: 5
            isRequired: true
            multiSelect: false
            value: ''
            query: '${tokenAccounts}\n| summarize Accounts=make_list(pack(\'id\', id, \'name\', name))\n| mv-expand Account=Accounts\n| project value=tostring(Account.id), label=tostring(Account.id), selected=array_length(Accounts) == 1\n| order by label asc'
          })
          {
            id: 'token-time-range'
            name: 'TokenTimeRange'
            label: 'Token time range (Metrics + request logs; maximum 31 days)'
            type: 4
            isRequired: true
            value: { durationMs: 604800000 }
            typeSettings: {
              selectableValues: [{ durationMs: 86400000 }, { durationMs: 604800000 }, { durationMs: 2592000000 }]
              allowCustom: true
            }
          }
          {
            id: 'token-metric-profile'
            name: 'TokenMetricProfile'
            label: 'Native metric schema (choose supported family, not both)'
            type: 2
            isRequired: true
            value: 'foundry'
            jsonData: string([{ value: 'foundry', label: 'Foundry / Models — InputTokens, OutputTokens' }, { value: 'openai', label: 'Standard Azure OpenAI — ProcessedPromptTokens, GeneratedTokens' }])
          }
          union(tokenArgSettings, {
            id: 'token-metric-account'
            name: 'TokenMetricAccount'
            type: 5
            isRequired: true
            multiSelect: false
            isHiddenWhenLocked: true
            query: '${tokenAccounts}\n| where id =~ "{TokenAccount:escapejson}"\n| project value=id, label=id, selected=true'
          })
          union(dropdownQuerySettings, {
            id: 'token-metric-view'
            name: 'TokenMetricView'
            type: 1
            isHiddenWhenLocked: true
            query: '${tokenContext}\nlet Profile=base64_decode_tostring(\'{TokenMetricProfile:base64}\');\nprint value=iff(base64_decode_tostring(\'{Navigation:base64}\') == \'tokens\' and AccountSelected and WindowValid and Profile in (\'foundry\', \'openai\'), Profile, \'unavailable\')'
          })
        ]
      }
    }
    {
      type: 3
      name: 'tokens-source-coverage'
      conditionalVisibility: tokenVisibility
      content: union(querySettings, {
        title: 'Token source inputs, scope and availability'
        query: '${tokenContext}\nprint AccountSelected, ValidTimeRange=WindowValid, FromUtc=StartUtc, ExclusiveEndUtc=EndUtc, DailyTimeZone=Zone, ProjectResourceGroup, AccountId=iff(AccountSelected, SelectedAccount, \'\'), MetricSchema=base64_decode_tostring(\'{TokenMetricProfile:base64}\'), NativeSource=\'Azure Monitor Metrics / Microsoft.CognitiveServices/accounts / Total\', NativeCoverage=\'Observed series only; max 100 series per metric; absent series is unavailable\', RequestLogSource=TokenSource, Workspace=base64_decode_tostring(\'${base64(logAnalyticsResourceId)}\'), Status=case(not(AccountSelected), \'Unavailable — select a discovered account in this exact RG\', not(WindowValid), \'Unavailable — invalid time zone or time range (maximum 31 days)\', \'Read sources separately below; no cache series/field is NOT zero\'), AccountUrl=iff(AccountSelected, strcat(\'https://portal.azure.com/#resource\', SelectedAccount), \'\'), MetricsUrl=iff(AccountSelected, strcat(\'https://portal.azure.com/#resource\', SelectedAccount, \'/metrics\'), \'\')'
        gridSettings: {
          formatters: [
            { columnMatch: 'AccountId', formatter: 1, formatOptions: { linkColumn: 'AccountUrl', linkTarget: 'Url' } }
            { columnMatch: 'MetricsUrl', formatter: 7, formatOptions: { linkTarget: 'Url' } }
          ]
        }
      })
    }
  ], tokenMetricTables, tokenMetricTrends, [
    {
      type: 10
      name: 'tokens-native-cached-table'
      conditionalVisibility: { parameterName: 'TokenMetricView', comparison: 'isEqualTo', value: 'foundry' }
      content: union(tokenMetricSettings, {
        chartId: 'tokens-native-cached-table'
        title: 'Native cached input by deployment / model / version — absent series = UNAVAILABLE, not zero'
        chartType: 0
        gridFormatType: 2
        metrics: [tokenCachedMetric]
      })
    }
    {
      type: 1
      name: 'tokens-standard-cache-notice'
      conditionalVisibility: { parameterName: 'TokenMetricView', comparison: 'isEqualTo', value: 'openai' }
      content: { json: '**Standard Azure OpenAI:** no cached-token count or ModelName dimension is inferred from these native metrics. See request-log fields below if emitted; otherwise cached tokens and model name are **Unavailable**. Cache match/rate metrics are not token counts.' }
    }
    {
      type: 9
      name: 'tokens-log-drilldown'
      conditionalVisibility: tokenVisibility
      content: {
        version: 'KqlParameterItem/1.0'
        style: 'above'
        parameters: [
          union(dropdownQuerySettings, {
            id: 'token-deployment'
            name: 'TokenDeployment'
            label: 'Deployment (request logs only)'
            value: '*'
            query: '${tokenQuery}TokenRecords | distinct Deployment | project value=Deployment, label=Deployment | union (print value=\'*\', label=\'All observed deployments in selected account\')'
          })
          union(dropdownQuerySettings, {
            id: 'token-model'
            name: 'TokenModel'
            label: 'Model / version (request logs only)'
            value: '*'
            query: '${tokenQuery}TokenRecords | where base64_decode_tostring(\'{TokenDeployment:base64}\') == \'*\' or Deployment == base64_decode_tostring(\'{TokenDeployment:base64}\') | distinct ModelKey, ModelName, ModelVersion | project value=ModelKey, label=strcat(ModelName, \' / \', ModelVersion) | union (print value=\'*\', label=\'All observed models / versions\')'
          })
        ]
      }
    }
    {
      type: 1
      name: 'tokens-log-schema-and-freshness'
      conditionalVisibility: tokenVisibility
      content: {
        json: '**Request-log source mapping:** flat `properties_s.promptTokens` → input, `properties_s.generatedTokens` → output, `properties_s.cachedTokens` → cached input subset; dimensions are `modelDeploymentName`, `modelName`, `modelVersion`. Token fields support numeric scalars and nonempty numeric arrays: every element must be finite, nonnegative and integral before `array_sum` is used. Missing values, empty arrays, null/invalid elements, overflow and conflicting identities never become zero. These service fields do not require nested request/response/usage objects. Known alternate field shapes are fallbacks, never extra usage. A missing cached field remains null; an explicitly emitted zero (scalar or array) is a measured zero.\n\n**Separate source freshness:** `FirstObservedUtc` / `LastObservedUtc` are timestamps of matching request-log observations, not proof of ingestion completeness. `LastObservationAge` is age at query time; `GapToWindowEnd` is time from the last matching observation to the selected end. Native Metrics may have newer observations than request logs. Do not label older logs as current or infer zero tokens for the gap; do not use Metrics to fill or sum into log totals. Missing request identities retain observed rows and explicitly mark deduplication as unverified. No diagnostic routing or permissions are changed.'
      }
    }
    {
      type: 3
      name: 'tokens-log-validation'
      conditionalVisibility: tokenVisibility
      content: union(querySettings, {
        title: 'Request-log coverage (not native Metrics coverage)'
        query: '${tokenReportQuery}SelectedTokenRecords | summarize ObservedRows=count(), MissingRequestIdentity=countif(not(HasRequestId)), MissingInputField=countif(isnull(InputTokens)), MissingOutputField=countif(isnull(OutputTokens)), MissingCachedField=countif(isnull(CachedTokens)), InvalidValues=countif(InvalidValues), ConflictingRows=countif(Conflict), FirstObservedUtc=min(FirstObservedUtc), LastObservedUtc=max(LastObservedUtc) | extend Source=TokenSource, LastObservationAge=now() - LastObservedUtc, GapToWindowEnd=EndUtc - LastObservedUtc, Status=case(not(AccountSelected), \'Unavailable — no valid scoped account\', not(WindowValid), \'Unavailable — invalid time range / zone\', ObservedRows == 0, \'Unavailable — no matching request-usage logs; native Metrics above is independent\', \'Observed request logs only; missing fields/series are not measured zero\')'
      })
    }
    {
      type: 3
      name: 'tokens-log-model-totals'
      conditionalVisibility: tokenVisibility
      content: union(querySettings, {
        title: 'Request logs — input / output / cached by deployment AND model / version'
        noDataMessage: 'Unavailable — no matching AzureOpenAIRequestUsage rows. Native Metrics above is independent.'
        query: '${tokenReportQuery}TokenTotals | order by Account asc, Deployment asc, ModelName asc, ModelVersion asc'
        gridSettings: {
          formatters: [
            { columnMatch: 'Account', formatter: 1, formatOptions: { linkColumn: 'AccountUrl', linkTarget: 'Url' } }
            { columnMatch: 'Deployment', formatter: 1, formatOptions: { linkColumn: 'DeploymentUrl', linkTarget: 'Url' } }
          ]
        }
      })
    }
    {
      type: 3
      name: 'tokens-log-daily'
      conditionalVisibility: tokenVisibility
      content: union(querySettings, {
        title: 'Request logs — token totals per local day (cached is a subset)'
        query: '${tokenReportQuery}union (TokenDaily | project Day, Series=strcat(Deployment, \' / \', ModelName, \' / \', ModelVersion, \' / input\'), Tokens=InputTokens), (TokenDaily | project Day, Series=strcat(Deployment, \' / \', ModelName, \' / \', ModelVersion, \' / output\'), Tokens=OutputTokens), (TokenDaily | project Day, Series=strcat(Deployment, \' / \', ModelName, \' / \', ModelVersion, \' / cached subset\'), Tokens=CachedTokens) | order by Day asc'
        visualization: 'timechart'
        chartSettings: { xAxis: 'Day', yAxis: ['Tokens'], group: 'Series', showLegend: true }
      })
    }
    {
      type: 3
      name: 'tokens-log-daily-details'
      conditionalVisibility: tokenVisibility
      content: union(querySettings, {
        title: 'Request logs — daily token and emitted-field coverage detail'
        query: '${tokenReportQuery}TokenDaily | extend Source=TokenSource | order by Day asc, Deployment asc, ModelName asc, ModelVersion asc'
      })
    }
  ])
}

resource myProjectWorkbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: workbookName
  location: location
  kind: 'shared'
  tags: tags
  properties: {
    displayName: 'My Project ${projectNumber} - ${toUpper(env)} - Usage, Cost and Model Tokens'
    category: 'workbook'
    sourceId: applicationInsightsResourceId
    version: '1.0'
    serializedData: string(workbook)
  }
}

output id string = myProjectWorkbook.id
output name string = myProjectWorkbook.name
output url string = workbookUrl
output tokensUrl string = tokensUrl
output sourceIds object = {
  applicationInsights: applicationInsightsResourceId
  logAnalytics: logAnalyticsResourceId
}
