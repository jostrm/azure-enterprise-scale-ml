@description('Opt in explicitly. Default deploys no workbook, telemetry sink, schedule, role assignment or ingestion resource.')
param enableAgentMonitoring bool = false

param location string = resourceGroup().location

@description('Existing authorized Log Analytics workspace ARM ID; workbook readers also need query access and private network reachability.')
@minLength(1)
param workspaceResourceId string

param workbookDisplayName string = 'AI Factory — Agent business value, cost and security'
param tags object = {}

var workspaceParts = split(workspaceResourceId, '/')
var validWorkspacePath = length(workspaceParts) == 9 ? (empty(workspaceParts[0]) && toLower(workspaceParts[1]) == 'subscriptions' && toLower(workspaceParts[3]) == 'resourcegroups' && toLower(workspaceParts[5]) == 'providers' && toLower(workspaceParts[6]) == 'microsoft.operationalinsights' && toLower(workspaceParts[7]) == 'workspaces') : false

// A control-plane read must resolve this exact existing workspace before the workbook write.
// Malformed paths deliberately produce an invalid empty resource name, never a guessed workspace.
resource sourceWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  scope: resourceGroup(validWorkspacePath ? workspaceParts[2] : subscription().subscriptionId, validWorkspacePath ? workspaceParts[4] : resourceGroup().name)
  name: validWorkspacePath ? workspaceParts[8] : ''
}
var resolvedWorkspaceId = enableAgentMonitoring ? sourceWorkspace.properties.customerId : ''

var rows = loadTextContent('agentMonitoringRows.kql')
var filteredRows = '''
${rows}
| where TimeGenerated {TimeRange}
| where ("{AiFactory:escapejson}" == "All" or AiFactory == "{AiFactory:escapejson}")
  and ("{Scaleset:escapejson}" == "All" or Scaleset == "{Scaleset:escapejson}")
  and ("{Project:escapejson}" == "All" or Project == "{Project:escapejson}")
  and ("{Environment:escapejson}" == "All" or Environment == "{Environment:escapejson}")
  and ("{Agent:escapejson}" == "All" or Agent == "{Agent:escapejson}")
| summarize arg_max(TimeGenerated, *) by AiFactory, Scaleset, Project, Environment, Agent, ObservationId
| extend Subscription=tostring(observation.azure.subscriptionId), ResourceGroup=tostring(observation.azure.resourceGroup), ResourceId=tostring(observation.azure.resourceId)
| extend ResourceGroupScope=strcat("/subscriptions/", Subscription, "/resourceGroups/", ResourceGroup)
| extend ValidScope=Subscription matches regex "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$" and Subscription != "00000000-0000-0000-0000-000000000000" and ResourceGroup matches regex "^[A-Za-z0-9_().-]{1,90}$" and ResourceGroup !endswith "." and ResourceGroup !~ "All" and (isempty(ResourceId) or ResourceId startswith strcat(ResourceGroupScope, "/providers/"))
| extend CostAnalysisUrl=iff(MetadataValidated and ValidScope and isnotempty(trim(@"\s+", Project)) and tolower(trim(@"\s+", Project)) !in ("all", "unknown", "undefined", "null", "unavailable", "n/a"), strcat("https://portal.azure.com/#blade/Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/", url_encode_component(ResourceGroupScope)), ""), Tooltip=strcat("Go to Azure Cost analysis for project ", Project)
'''
var dimensions = ['AiFactory', 'Scaleset', 'Project', 'Environment', 'Agent']
var scopeParameters = [for dimension in dimensions: {
  id: dimension
  name: dimension
  type: 2
  isRequired: true
  value: 'All'
  query: 'union (datatable(value:string, label:string)["All", "All"]), (${rows}\n| where isnotempty(${dimension})\n| distinct value=${dimension}\n| extend label=value)'
  queryType: 0
  resourceType: 'microsoft.operationalinsights/workspaces'
}]
var valueQuery = '''
${filteredRows}
| where Kind == "outcome"
| extend Completed=todouble(observation.outcome.completed), Baseline=todouble(observation.outcome.baselineMinutes), Actual=todouble(observation.outcome.actualMinutes)
| extend Available=EvidencePresent and gettype(observation.outcome.qualityPassed) == "bool" and tobool(observation.outcome.qualityPassed) == true and gettype(observation.outcome.completed) in ("long", "real") and gettype(observation.outcome.baselineMinutes) in ("long", "real") and gettype(observation.outcome.actualMinutes) in ("long", "real") and Completed between (0.0 .. 9007199254740991.0) and Baseline between (0.0 .. 9007199254740991.0) and Actual between (0.0 .. 9007199254740991.0)
| extend MinutesSaved=iff(Available, (Baseline-Actual)*Completed, real(null))
| summarize MinutesSaved=sum(MinutesSaved), AvailableObservations=countif(Available), CollectedObservations=count(), Inputs=make_set(observation.outcome), Evidence=make_set(Evidence), Upstream=make_set(observation.provenance) by AiFactory, Scaleset, Project, Environment, Agent, DataSource, CostAnalysisUrl, Tooltip
| extend MinutesSaved=iff(AvailableObservations > 0, MinutesSaved, real(null)), Status=case(AvailableObservations == 0, "NO DATA: outcome/baseline/evidence required", AvailableObservations < CollectedObservations, "PARTIAL: only available outcomes included", "Available"), Calculation="sum((baselineMinutes - actualMinutes) * completed), evidence and quality gate required"
'''
var costQuery = '''
${filteredRows}
| where Kind == "cost"
| extend Basis=tostring(observation.cost.basis), Amount=todouble(observation.cost.amount), Currency=tostring(observation.cost.currency)
| extend Available=gettype(observation.cost.amount) in ("long", "real") and abs(Amount) <= 9007199254740991.0 and Currency matches regex "^[A-Z]{3}$" and ((Basis in ("actual", "amortized") and DataSource == "Cost Management" and EvidencePresent) or (Basis == "estimate" and gettype(observation.cost.formula) == "string" and isnotempty(trim(@"\s+", tostring(observation.cost.formula))) and array_length(bag_keys(observation.cost.inputs)) > 0))
| summarize Cost=sum(iff(Available, Amount, real(null))), AvailableObservations=countif(Available), CollectedObservations=count(), Evidence=make_set(Evidence), Inputs=make_set(observation.cost), Upstream=make_set(observation.provenance), Sources=make_set(DataSource) by AiFactory, Scaleset, Project, Environment, Agent, Basis, Currency, CostAnalysisUrl
| extend Cost=iff(AvailableObservations > 0, Cost, real(null)), Status=case(AvailableObservations == 0, "NO DATA: cost evidence/inputs required", AvailableObservations < CollectedObservations, "PARTIAL: only available costs included", "Available"), Tooltip=strcat("Go to Azure Cost analysis for project ", Project), Calculation="Sum collected amounts in one currency and one billing basis; never combine actual/amortized/estimate", DataSource=strcat_array(Sources, "; ")
'''
var securityQuery = '''
${filteredRows}
| where Kind == "security"
| extend Control=tostring(observation.security.control), Passed=tobool(observation.security.passed), Checks=todouble(observation.security.checks), Findings=todouble(observation.security.findings)
| extend Mode=iff(isnotempty(trim(@"\s+", Control)), "control", "aggregate")
| extend Available=EvidencePresent and ((Mode == "control" and gettype(observation.security.passed) == "bool") or (Mode == "aggregate" and gettype(observation.security.checks) in ("long", "real") and gettype(observation.security.findings) in ("long", "real") and Checks between (0.0 .. 9007199254740991.0) and Findings between (0.0 .. 9007199254740991.0)))
| summarize Passed=countif(Available and Passed), Failed=countif(Available and Passed == false), Checks=sum(iff(Available, Checks, real(null))), Findings=sum(iff(Available, Findings, real(null))), AvailableObservations=countif(Available), CollectedObservations=count(), Evidence=make_set(Evidence), Inputs=make_set(observation.security), Upstream=make_set(observation.provenance) by AiFactory, Scaleset, Project, Environment, Agent, Mode, Control, DataSource, CostAnalysisUrl, Tooltip
| extend Passed=iff(AvailableObservations > 0 and Mode == "control", Passed, long(null)), Failed=iff(AvailableObservations > 0 and Mode == "control", Failed, long(null)), Checks=iff(AvailableObservations > 0 and Mode == "aggregate", Checks, real(null)), Findings=iff(AvailableObservations > 0 and Mode == "aggregate", Findings, real(null)), Status=case(AvailableObservations == 0, "NO DATA: control evidence required", AvailableObservations < CollectedObservations, "PARTIAL: only observed controls included", "Available"), Calculation="Count supplied evidence-backed controls or sum explicit aggregate findings/checks; aggregate findings are not fabricated individual failed controls"
'''
var reportQueries = [
  { name: 'Legacy v1 — quality-qualified minutes saved (not realized cash)', query: valueQuery }
  { name: 'Legacy v1 — actual, amortized and estimates remain separate', query: costQuery }
  { name: 'Legacy v1 — recorded security controls, not inferred compliance', query: securityQuery }
  { name: 'Canonical v2 — Usage and adoption', query: '${canonicalQueries}\nCanonicalMetrics | where Section == "usage"' }
  { name: 'Canonical v2 — Foundry token observations (not billing)', query: '${canonicalQueries}\nCanonicalMetrics | where Section == "tokens"' }
  { name: 'Canonical v2 — Quality and reliability', query: '${canonicalQueries}\nCanonicalMetrics | where Section == "reliability"' }
  { name: 'Canonical v2 — Showback: distinct actual / amortized / estimated costs', query: '${canonicalQueries}\nCanonicalMetrics | where Section == "cost"' }
  { name: 'Canonical v2 — Modeled, qualified and verified realized value', query: '${canonicalQueries}\nCanonicalMetrics | where Section == "value"' }
  { name: 'Canonical v2 — Security and governance evidence', query: '${canonicalQueries}\nCanonicalMetrics | where Section == "security"' }
]
var canonicalQueries = replace(loadTextContent('agentMonitoringCanonical.kql'), '__FILTERED_ROWS__', filteredRows)
var workbook = {
  version: 'Notebook/1.0'
  items: [
    {
      type: 1
      name: 'provenance-and-prerequisites'
      content: {
        json: '# Agent value, usage, cost and trust\n\n**Data source:** existing Log Analytics workspace / Application Insights `AppEvents`, event `aifactory.agent.observation`. Native v1 and v2 are supported. V2 preserves canonical observation row grain across all six report families; legacy v1 sections retain their qualified-evidence semantics. Cost rows require **Cost Management** evidence; estimates require supplied formula/inputs. This workbook does not collect or fabricate billing.\n\n**All** means authorized collected scope in this workspace, not all tenant resources. Five selectors intersect **before** aggregation. Missing data is unavailable, not zero, healthy or compliant. V2 complete-row sums and ratios of sums do not sum latency averages or distinct user populations. KQL values outside the exact interoperable numeric range (2^53-1) are explicitly unavailable; original v2 exports retain them.\n\n**Value tiers:** modeled time-saving capacity is not qualified outcomes or cash. Qualified capacity requires explicit true plus completion/baseline/effort evidence; monetary qualification also requires rate evidence and one currency. Qualified labor capacity remains modeled. **Native verified finance metrics are unsupported**: supplied realized benefit and value/cost evidence are preserved, but require the canonical API finance validator for exact approval, currency, period, scope, complete cost coverage and nonoverlap. This workbook never promotes a supplied amount to verified benefit. Input/output tokens are usage, not value. Actual, amortized and estimated costs remain alternative bases.\n\nReader RBAC/private-network access still apply. Deployment adds no instrumentation, ingestion, diagnostic settings, roles, cost exports or schedules. Per-field sources, formulas and evidence are visible in result columns. Native v2 sections use only published live evidence, never embedded samples.'
      }
    }
    {
      type: 1
      name: 'existing-workspace-reference'
      content: {
        json: '**Resolved existing workspace:** ${resolvedWorkspaceId}\n\nThis deployment-time resource read confirms the configured workspace exists and is readable by the deployment identity. It does not confirm event collection, cost coverage, reader query access or data freshness.'
      }
    }
    {
      type: 9
      name: 'scope-and-time'
      content: {
        version: 'KqlParameterItem/1.0'
        parameters: concat([
          {
            id: 'time-range'
            name: 'TimeRange'
            type: 4
            value: { durationMs: 2592000000 }
            typeSettings: { selectableValues: [ { durationMs: 86400000 }, { durationMs: 604800000 }, { durationMs: 2592000000 } ] }
          }
        ], scopeParameters)
        style: 'pills'
        queryType: 0
        resourceType: 'microsoft.operationalinsights/workspaces'
      }
    }
    {
      type: 3
      name: 'collection-status'
      content: {
        version: 'KqlItem/1.0'
        title: 'Collection coverage — Data source: Log Analytics workspace'
        query: '${filteredRows}\n| summarize CollectedRows=count()\n| extend Status=iff(CollectedRows == 0, "NO DATA: instrument evidence-backed AppEvents and collect authorized Cost Management observations first", "Recorded observations only; inspect section evidence and missing inputs"), Calculation="count rows after all scope filters"'
        queryType: 0
        resourceType: 'microsoft.operationalinsights/workspaces'
        visualization: 'table'
      }
    }
  ]
  fallbackResourceIds: [workspaceResourceId]
  isLocked: false
}
var sections = [for report in reportQueries: {
  type: 3
  name: report.name
  content: {
    version: 'KqlItem/1.0'
    title: '${report.name} — Data source: Log Analytics / Application Insights; billing: Cost Management; estimates: Calculated'
    query: report.query
    queryType: 0
    resourceType: 'microsoft.operationalinsights/workspaces'
    visualization: 'table'
    noDataMessage: 'No evidence-backed observations for this selection. Missing values are unavailable, not zero.'
    gridSettings: {
      formatters: [
        {
          columnMatch: 'Project'
          formatter: 1
          formatOptions: {
            linkTarget: 'Url'
            linkColumn: 'CostAnalysisUrl'
          }
        }
        {
          columnMatch: 'CostAnalysisUrl'
          formatter: 5
        }
      ]
    }
  }
}]

resource agentWorkbook 'Microsoft.Insights/workbooks@2023-06-01' = if (enableAgentMonitoring) {
  name: guid(resourceGroup().id, workbookDisplayName)
  location: location
  kind: 'shared'
  tags: union(tags, { 'aifactory-purpose': 'agent-monitoring' })
  properties: {
    displayName: workbookDisplayName
    category: 'workbook'
    sourceId: workspaceResourceId
    serializedData: string(union(workbook, { items: concat(workbook.items, sections) }))
  }
}

output workbookResourceId string = enableAgentMonitoring ? agentWorkbook!.id : ''
output workbookUrl string = enableAgentMonitoring ? 'https://portal.azure.com/#@${tenant().tenantId}/resource${agentWorkbook!.id}' : ''
