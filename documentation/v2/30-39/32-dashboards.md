# AI Factory monitoring: value, cost and trust

Use one monitoring story across four delivery layers: **Azure built-ins**,
**AI Factory native assets**, **MAUI Monitoring**, and **Tkinter Dashboards /
CLI / API**. These layers complement each other; a desktop chart is not a
replacement for the native billing or telemetry source.

This guide covers the reusable **purple** module, the **orange** consumer
repository, and the two desktop clients. Capability and source review:
**17 September 2026**. Local artifacts and sample captures are not evidence
that a resource has been deployed in Azure.

## 1. Azure-native dashboards and FinOps capabilities

| Native surface | Usage, tokens, cost and security coverage | Important boundary |
|---|---|---|
| [Azure Monitor Metrics / Azure OpenAI](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/monitor-openai) | Requests, input/output tokens, latency, errors and PTU utilization | Platform measurements are not an invoice. Dimensions are predefined; arbitrary factory/project tags are not automatically metric dimensions. |
| [Azure Monitor Workbooks](https://learn.microsoft.com/en-us/azure/azure-monitor/visualize/workbooks-data-sources) | Parameterized views over Metrics, Logs/Application Insights, Resource Graph and ARM APIs | A workbook can be deployed with Bicep, but it does not create missing telemetry or attribution. |
| [Application Insights usage](https://learn.microsoft.com/en-us/azure/azure-monitor/app/usage) | Users, sessions, events, funnels, retention and custom business events | Requires instrumentation. Business actions and organizational dimensions must be supplied by the application. |
| [Cost Management Cost analysis](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/customize-cost-analysis-views) | Billing-derived actual/amortized cost, forecast, resource/service/tag breakdown and saved views | A saved cost view is not a workbook. Customizable views do not group by multiple attributes simultaneously. |
| [Budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets) and [exports](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-improved-exports) | Actual/forecast budget alerts and recurring cost datasets, including FOCUS exports | Budget evaluation is daily and does not stop spending. Exports are reporting inputs, not agent outcome evidence. |
| [Foundry agent Monitor](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard) | Application Insights-backed agent tokens, latency, run success, evaluations and configured red-team results | Documentation marks agent metrics, recurring evaluations, red-team scans and dashboard alerts as preview. These are portal experiences, not the same asset as a custom workbook. |
| [Foundry tracing](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup) | Run/tool/model trace details for supported agents | Current documentation distinguishes GA tracing for prompt/hosted agents from preview workflow/external-agent tracing. Custom application code still needs instrumentation. |
| [Foundry Control Plane](https://learn.microsoft.com/en-us/azure/foundry/control-plane/overview) | Permission-aware agent inventory and operational views; token-based estimated agent cost | Operate experiences are documented as portal-only. A token-cost estimate is not reconciled Azure billing or complete workload cost. |
| [Defender for Cloud AI threat protection](https://learn.microsoft.com/en-us/azure/defender-for-cloud/ai-threat-protection) and [AI posture](https://learn.microsoft.com/en-us/azure/defender-for-cloud/ai-security-posture) | Threat alerts, posture recommendations, inventory and attack-path evidence | Threat protection is GA and currently scans text. Agent discovery/posture is preview and documentation requires Agent 365 from July 2026; account/project posture is a separate scope. |
| [FinOps toolkit Optimization workbook](https://learn.microsoft.com/en-us/cloud-computing/finops/toolkit/workbooks/optimization) | Advisor, idle resources, usage/rate optimization and potential savings | Deployable workbook; recommended savings are opportunities, not proof of realized business value. |

### Usage, price and billed cost are different things

Keep three columns separate: **measured usage**, **estimated price-based cost**,
and **billing-derived cost**.

For a token estimate, the rate must match the model/version, deployment type,
input/output/cached token meters, currency and applicable agreement. Do not
embed invented prices or assume a public PAYGO rate is the customer's rate.
[Azure OpenAI pricing](https://azure.microsoft.com/en-us/pricing/details/azure-openai/)
is a rate reference; the customer's billing data remains the reconciliation
source.

[Provisioned throughput](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/provisioned-throughput-billing)
is billed as deployed capacity over time, including idle capacity. Multiplying
PTU token counts by PAYGO token prices does not reproduce its actual charge.

[Cost Management data](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/understand-cost-mgt-data)
typically arrives in 8-24 hours for EA/MCA and can take up to 72 hours for PAYGO
subscription offers. This billing-account distinction is separate from the
model's token-priced versus provisioned deployment. Open-period costs can
change before invoicing.

Actual cost reflects accrued usage/purchases; amortized cost spreads eligible
reservation/savings-plan purchases and attributes benefits to consuming
resources. Declare the selected basis, rather than mixing it between reports.

### Native support for factory, scaleset and project filtering

Cost analysis can filter supported billing tags and resource scopes. Apply the
factory/scaleset/project taxonomy to resource tags and maintain the mapping
between the project and its resource groups. Tags do not automatically become
historical or propagate from resource groups to all cost records.
[Cost Management tag inheritance](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/enable-tag-inheritance)
is an explicit setting affecting usage records, not a resource-tag deployment.

For Logs, Application Insights and custom Workbooks, carry the same dimensions
as telemetry properties and filter them before aggregation. For Azure Monitor
platform metrics, first select the matching resource set and then use the
supported metric dimensions. Shared Foundry/model resources need an explicit
application-level attribution rule.

AI Factory cannot add universal filter controls to Microsoft's own portals.
Its clients should explain what scope is transferred to the native destination
and which additional filters the user must select there.

### Native business-value support today

Application Insights funnels/custom events support adoption and instrumented
business outcomes. Foundry evaluates agent task completion and customer
satisfaction through [built-in evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/built-in-evaluators),
currently marked preview for those evaluators. A model's judgment of completion
or satisfaction is not an accepted business transaction or an actual CSAT
survey response.

Azure supplies much of the usage, operational, quality and security evidence.
Verified outcome definitions, baseline labor, monetary valuation, allocation
and realized benefit remain customer instrumentation and governance work.
The value model below makes that additional evidence explicit.

## 2. AI Factory Azure-native assets

### 2a. Bicep dashboards and telemetry

The module inventory contains three portal-dashboard declarations. These are
not three Foundry agent-ROI dashboards.

| Asset | Purpose and source | Scope / caveat |
|---|---|---|
| [`aifactory-dash-01.bicep`](../../../environment_setup/aifactory/bicep/modules/aifactory-dash-01.bicep) | Factory/shared landing-zone navigation and resource-group cost/inventory tiles | Configured factory/scaleset/environment resources; tiles can reference resources not yet deployed |
| [`projectDash01.bicep`](../../../environment_setup/aifactory/bicep/modules/projectDash01.bicep) | Project resource dashboard and native resource/cost navigation | Actual project resource IDs determine scope; a generated dashboard name does not prove deployment |
| [`appinsightsDashboard.bicep`](../../../environment_setup/aifactory/bicep/modules/appinsightsDashboard.bicep) | Application Insights operational dashboard | Application instrumentation is required; not a cost or realized-value collector |
| [`monitoring/agentMonitoringWorkbook.bicep`](../../../environment_setup/aifactory/bicep/modules/monitoring/agentMonitoringWorkbook.bicep) | New opt-in value, cost and security workbook over evidence-backed observations | Existing workspace; five All-default scope selectors plus time; no collection, ingestion or RBAC deployment |

The diagnostics inventory contains **33 diagnostic-setting declarations across
24 files**, including **18 dedicated diagnostics modules**. Counts are source
declarations, not a promise that all are instantiated by every workload.
Examples include Foundry/Cognitive Services, Azure ML, Search, Container Apps,
Storage, Key Vault, Cosmos DB and databases.

Foundry diagnostic configuration includes the supported request/response,
trace and Azure OpenAI request-usage categories. Diagnostic settings are
**telemetry plumbing**, not standalone dashboards. Their existence does not
establish agent business-outcome instrumentation, complete cost attribution or
query permissions.

Four older exported dashboard JSON files remain under
[`environment_setup/aifactory/azure_dashboards`](../../../environment_setup/aifactory/azure_dashboards).
Treat these as legacy portal artifacts, distinct from the current Bicep
declarations and the new workbook.

### 2b. On-demand dashboards and reports

The reusable automation folder is
[`environment_setup/aifactory/bicep/copy_to_local_settings/automation`](../../../environment_setup/aifactory/bicep/copy_to_local_settings/automation).
Consumers copy these templates before supplying their own reviewed
configuration.

| Report / entry point | What it provides | Source and boundary |
|---|---|---|
| `coreteam\finops\runbooks\Update-FoundryTokenReport.ps1` | Foundry token usage and configured price-based reporting | Collected token telemetry; any pricing/cache/discount/PTU inputs are assumptions, not verified billing |
| `coreteam\finops\runbooks\showback\Update-ShowbackReport.ps1` | Project and cost-center showback, with native project cost links | Cost Management; All is limited to the configured naming/scope and authorized collected projects |
| `projectteam\foundry-usage\foundry_usage_report.py` | Foundry deployment usage and report artifacts | Operational usage evidence; optional runtime dependencies are separate from desktop sample viewing |
| `report_compute.py` / `report-local.ps1` | Reviewed local/runbook/Logic App report execution contract | Existing three collector types; concrete project/environment execution required |
| `native_monitoring.py` | New offline value/cost/security report, aligned JSON/CSV and prepared AppEvents | Already-collected, explicitly sample or live observations; not a new Azure collector |
| `coreteam\finops\runbooks\Update-AgentMonitoringReport.ps1` | New PowerShell wrapper for the observation report | Same importer; does not authenticate, upload, ingest or create a job/schedule |
| `run-native-monitoring-sample.ps1` | Safe consumer demonstration of Project 001 filtering | Local sample only; no Azure calls or live resource URLs |

The existing execution protocol supports `local`, `runbook` and `logicapp`
compute where configured. Selecting cloud compute does not make a sample run
live. Publishing a runbook, wiring a Logic App or enabling a schedule is a
separate reviewed operation.

The older collector's **All filter** and its **execution target** are different
things. An All execution target is rejected as unavailable before building
resource IDs or calling Azure. Use imported observations for a genuinely
multi-factory/scaleset view rather than silently running an arbitrary project.

### New workbook and on-demand evidence contract

The new native workflow is deliberately opt-in:

1. Collect approved observations with explicit source and scope.
2. Generate local reports or prepare AppEvents using the reusable automation.
3. Review privacy, RBAC, retention and network reachability.
4. Publish observations through an approved telemetry pipeline and deploy the
   workbook separately when ready.

`enableAgentMonitoring` defaults to `false`. Enabling the standalone workbook
requires `workspaceResourceId` for an existing Log Analytics workspace. The
module adds no telemetry sink, role assignment, collection schedule or
instrumentation automatically.

The workbook queries `AppEvents`, event `aifactory.agent.observation`. Its
sections show collection coverage, evidence-backed minutes saved, separately
grouped actual/amortized/estimated cost, and recorded security evidence.
The native source is Logs/Application Insights; imported cost observations
retain their Cost Management source. Currency and cost basis are never
combined silently.

| Contract | Role |
|---|---|
| `aifactory.monitoring-observations.v1` | Shared flat observation input accepted by the canonical backend and native importer |
| `aifactory.agent-observations/v1` | Native observation/event input; scope includes AI Factory, scaleset, project, environment and agent |
| `aifactory.native-monitoring-report/v1` | Native report output, including `inputSchema` and imported-observation provenance |
| `aifactory.monitoring-report.v1` | Desktop/API canonical report envelope; not the native report output |
| `aifactory.aggregate-report.v1` | Existing monitoring execution bridge; additive `dataSource` and `lineage` preserve compatibility |

The native bridge maps flat `factory` to `scope.aiFactory` and `agent_id` to
`scope.agent`. Live imports require an explicit reviewed authorization manifest;
ARM syntax checking is not proof of resource existence. Native value requires
explicit `outcome_quality_passed=true`, not an inference from completion or
evaluation counts. Token estimates require formula/input provenance. Aggregate
security counts remain aggregate observations, not fabricated individual
control failures.

From the **copied automation directory**, run a local sample:

```powershell
python -I -B .\native_monitoring.py `
  --input .\samples\monitoring-observations.sample.json `
  --source sample --aiFactory factory-a --scaleset 001 --project 001

pwsh -NoProfile -File .\run-native-monitoring-sample.ps1
```

Optional `--output`, `--csv` and `--events` produce local artifacts.
**`--events` only prepares event payloads; it does not ingest them.** The native
workbook was not deployed or rendered against newly published telemetry in
this implementation pass.

For supported native observations, `--observations-output` produces the flat
canonical input used by the desktop/API:

```powershell
python -I -B .\native_monitoring.py `
  --input .\samples\agent-observations.sample.json `
  --aiFactory factory-a --scaleset 001 --project 001 `
  --observations-output .\project001-observations.json
```

The PowerShell wrapper exposes `-CanonicalObservationsPath`. The exporter
combines only complementary measurements at the **same full scope and
timestamp**; overlapping fields, currencies or validated-resource scopes are
rejected. It exports only native-represented metrics and does not invent labor
rates, request counts or security findings. Keep the original canonical file
when those additional inputs matter.

Token estimates require explicit native `cost.estimateType = "tokens"` before
mapping to `token_estimated_cost`. The canonical-to-native importer supplies
that designation for an explicitly named canonical token estimate. A generic
infrastructure estimate is never silently renamed a token cost. Formula,
input, evidence and source requirements still apply.

Sample exports retain their sample markers and cannot be imported as live
evidence. Native event/report envelopes are not themselves accepted as
canonical API requests: export the supported flat observation envelope first.
Validated-resource metadata is preserved only when explicitly supplied and
consistent; syntactically valid IDs alone do not authorize live links.

## 3. MAUI Monitoring

MAUI is a visual consumer of the canonical Tkinter backend, not a second
calculation engine. Its existing Monitoring surfaces are retained:

| View | What it shows | Evidence boundary |
|---|---|---|
| Overview | Monitoring summary and navigation | Source-specific operational context |
| Current AI Factory | Factory analytics; sample sections include capacity, model lifecycle, project inventory, agent/ML health | Configuration, cached/discovered evidence or explicitly labeled samples |
| Models & quota | Model quota/allocation, token popularity and quota risk | Model/region/pool scope; quota is not actual billed consumption |
| ML | Model and agent monitoring across Dev/Stage/Prod | Subject/environment-specific monitoring, not automatic business-value realization |
| Automation reports | Existing Foundry tokens, showback and deployment-usage workflow | Reviewed legacy execution; a leaking aggregate is blocked rather than relabeled |
| Value & insights | New canonical value, cost, usage, quality and security reports, plus native-source catalog | Same filtered canonical observations and metrics used by API/CLI |

**Value & insights** provides the common AI Factory / Scaleset / Project
selectors, default All, and all six canonical report types listed below. The
client rejects an unexpected returned scope or out-of-scope rows before showing
metrics, charts, tables or exporting the report. Changing scope, source or
identity invalidates stale work.

Native project labels are keyboard-accessible controls with Cost analysis
tooltips. Links must be HTTPS Azure Portal destinations whose decoded scope
matches the validated observation metadata. Sample links are disabled.
Report/chart source text and calculated-metric formula/input/upstream lineage
remain visible.

Live unified reporting uses an explicitly selected
`aifactory.monitoring-observations.v1` JSON input, with a 5 MB / 10,000-row
limit. The client does not authenticate a new collector or query Azure
implicitly. Source claims in imported evidence are not independently attested
by the UI. A native nested event/report document is not directly interchangeable
with the flat observation input.

### MAUI / Tkinter differences

| Capability | MAUI | Tkinter |
|---|---|---|
| Unified six-report calculation | Canonical API consumer | Canonical Python implementation used directly by the UI |
| Consistent All-default organizational filtering | Value & insights | Automation reports |
| Existing operational layout | Current AI Factory, Models & quota, ML and other Monitor tabs | Separate Capacity, Lifecycle, Models & Quota and Agents tabs |
| Existing automation workflow | Dedicated legacy Automation reports surface | Canonical and existing report choices in the same Automation reports area |
| Sample data | Explicit dummy/sample mode; unified samples come from canonical API | Explicit isolated in-memory demo/sample mode |
| Live evidence | Explicit flat-observation JSON import, submitted to canonical API | Explicit observation/report import and existing reviewed collectors |
| Source details | Source/provenance panels and native catalog | Sources & provenance subtab and report details |
| Filtered export | Canonical JSON copied through the UI | JSON/CSV actions; CLI/API also export |
| Native nested observation input | Not accepted directly | Native purple importer provides a separate canonical-to-native bridge |
| Legacy lineage | Preserved through a single-response metadata bridge and raw JSON export; missing legacy metadata is labeled unavailable | Preserved through normalization, scoped projections and JSON/CSV exports |

These are **not identical screen layouts**. Legacy operational panels retain
their native model/environment/factory scopes and disclose their limitations;
the unified report filters do not silently rewrite those panels' meaning.
The recommended navigation below is the converged information architecture,
not a claim that every historical panel has already been rewritten.

## 4. Tkinter Dashboards and canonical reports

The existing `PREREQUISITES.md` is the entry point for runtime setup; reading
sample dashboards remains independent of Azure login or optional cloud-report
packages. The current dashboard window preserves these operational views:

| View | Contents | Source |
|---|---|---|
| Overview | Project/environment/scaleset inventory | Local configuration and deployment evidence |
| Capacity issues | Capacity checks and issue drill-down | `preflight-status.json` |
| Lifecycle & services | Cumulative stalled Dev/Stage, lifecycle observations, configured services | Local configuration and persisted observations |
| Models & Quota | Quota pools, token popularity and quota risk | Persisted quota snapshots and token telemetry |
| Automation reports | Report, run history, execution preview, Sources & provenance | Report-specific collection or isolated samples |
| Agents | Agent inventory and discovery coverage | Configured/discovered inventory |
| AI Factory - Common RG | Native common-resource-group navigation | Existing configured Azure resource-group scope |

Automation reports now use six canonical report IDs:

| ID | Report | Category |
|---|---|---|
| `agent-value` | Agent business value, cost & security | Value/adoption |
| `showback` | Project and cost-center showback | Usage/cost |
| `foundry-tokens` | Foundry tokens | Usage/cost |
| `foundry-usage` | Deployment usage | Usage/cost |
| `quality-reliability` | Quality & reliability | Quality/reliability |
| `security-governance` | Security & governance | Security/governance |

The source catalog and report payloads carry source labels, formula/input
provenance, effective filters and native source-link metadata. Default factory,
scaleset, project and environment are All. Imported observations are a supplied
evidence path, not a claim that the client just queried every Azure service.

Each imported row must be a **disjoint additive observation grain**. Repeating
a project billing total on each agent/model row would double count it. A live
report's period comes from its supplied observation timestamps/periods; the
`days` option governs sample generation rather than silently trimming arbitrary
live evidence.

For a source-launched sample window, run from the Tkinter repository:

```powershell
python -m src.monitor_launcher `
  --factory "C:\path\to\existing\consumer\aifactory" `
  --demo --view automation-reports --report showback `
  --factory-scope "Demo AI Factory" --scaleset demo-east `
  --project 001 --environment dev
```

`--demo` is explicit and non-persistent. The native **Sources & provenance**
subtab explains the collection boundaries; report details and filtered JSON/CSV
retain metric inputs and upstream references.

### Canonical CLI

The CLI calls the same report/filter implementation as the API. Run from the
Tkinter repository:

```powershell
python -m src.monitoring_reports --catalog

python -m src.monitoring_reports --report showback --source sample `
  --factory "Demo AI Factory" --scaleset demo-east `
  --project 001 --environment dev --days 7

python -m src.monitoring_reports --report showback --source sample `
  --factory "Demo AI Factory" --scaleset demo-east `
  --project 001 --environment dev --days 7 --format csv
```

Omitting filters selects All. `--source live --input <observations.json>` uses
explicitly supplied observations, not automatic Azure discovery. JSON is the
default output; CSV retains scope, provenance and calculated-metric metadata.

For the seven-day sample, the concrete scope above contains **one compound
project identity and seven Project 001 rows**; All contains six compound
project identities across four displayed project numbers. A repeated `001` in
another factory/scaleset is a different project, not a duplicate to discard.

### Canonical API

The existing authenticated host exposes these additive endpoints under its
`X-API-Key` protection:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/monitoring/catalog` | Report IDs, categories, defaults, source catalog and collection rules |
| `POST /api/v1/monitoring/report` | Build a canonical report from sample or explicitly supplied observations |
| `POST /api/v1/monitoring/export` | Export the same filtered report rather than an unrelated unfiltered dataset |

Example sample request:

```json
{
  "report_id": "showback",
  "source": "sample",
  "days": 7,
  "filters": {
    "factory": "Demo AI Factory",
    "scaleset": "demo-east",
    "project": "001",
    "environment": "dev"
  }
}
```

Use the configured local host address and an API key supplied through the
existing supported configuration; do not put credentials in examples,
screenshots, report files or source control.

Responses identify `aifactory.monitoring-report.v1` and include `filters`,
`filter_options`, `metrics`, `charts`, `tables`, `rows`, `data_source`,
`provenance`, `coverage`, `warnings` and `collection_notice`.

Metric values are numeric or null, not preformatted success-shaped strings.
Metric metadata includes `data_source`, `formula`, `inputs`, `upstream` and
status. Chart `links` align with chart labels; row `native_link` records contain
the URL, tooltip, scope, source and access notice. Samples have no fake live
resource links.

The older `/api/v1/automation-reports` prepare/start/jobs/latest workflow remains
separate. Its singular `foundry-token` ID is preserved for compatibility;
the canonical report ID is `foundry-tokens`. Where a legacy result is projected,
`job.report.monitoring` carries the canonical representation. Do not substitute
the native importer output schema for either API response schema.

## Recommended information architecture

Organize by the question a user wants to answer, not by the technology that
produced the report. Keep the delivery layer and data source visible inside
each view.

| Section | User question | Primary evidence |
|---|---|---|
| Overview | What needs attention in this scope? | Coverage, freshness and links into the sections below |
| Value and adoption | Is the agent producing useful business outcomes? | Completed and accepted outcomes, adoption, baseline comparison, realization evidence |
| Usage and cost | What is being consumed, billed and allocated? | Resource metrics, model tokens, Cost Management actual/amortized cost, showback |
| Quality and reliability | Does it work well enough to trust? | Evaluations, errors, latency, successful task outcomes and tracing |
| Security and governance | Is the workload operated within its controls? | Defender findings, policy/configuration evidence, identities and safety signals |
| Native dashboards and reports | Where can I inspect the underlying evidence? | Native Azure views, deployed workbooks and on-demand report artifacts |

**MAUI and Tkinter should use the same section names, report identifiers,
scope controls and source contract.** Preserve existing operational views
such as capacity, lifecycle and quota; group or link them into this navigation
rather than removing useful capabilities.

Within a view, show the scope bar first, the data-mode/freshness banner next,
then headline metrics, charts, detail rows and native source links. Put setup,
execution previews and report-run history behind secondary actions. Sampling
must never look like an authenticated live query.

## A single scope contract

The common filter order is:

**AI Factory: All -> Scaleset: All -> Project: All**, followed by the applicable
environment, time range and report-specific dimensions.

| Rule | Required behavior |
|---|---|
| Default | The three organizational selectors start at **All**, not an arbitrary project |
| Meaning of All | Every matching row in the known, collected and authorized scope; not a claim of tenant-wide discovery |
| Combination | Selected dimensions are intersected, not applied independently to different visuals |
| Identity | Keep project numbers such as `001` as strings; identify a project by factory + scaleset + project, not number alone |
| Aggregation | Filter source rows first, then recalculate every KPI, chart, table and export from those rows |
| Cascading choices | A parent change refreshes valid child choices; incompatible selections must be reset visibly or rejected |
| Stale data | A new selection cannot leave old results looking like the new scope; refresh or explicitly mark them stale |
| Missing dimensions | A row without a factory/scaleset/project value does not match a concrete value in that dimension |
| No results | Show a scoped empty result, not the unfiltered report and not a synthetic successful zero |
| Limited sources | If a source cannot honor a dimension, explain that limitation instead of silently ignoring the filter |
| Execution scope | A project-specific runner must not receive the literal string `All` as a project/resource identifier |
| Consistency | Sample data, live/provided evidence, CLI/API responses and exports use the same semantics |

The motivating defect was project showback displaying **Project 001** in its
selector and heading while charting Projects 001-004 and reporting four
projects. Correct behavior changes the data and totals, not merely the heading.

## Source provenance and native drill-through

Every report and chart needs a visible **Data source**. Where possible, include
the resource name/ID, query or metric family, period, collection time, currency
and attribution basis.

| Source label | What it means |
|---|---|
| Azure Cost Management | Billing-derived actual or amortized costs; name the basis explicitly |
| Azure Monitor Metrics | Platform measurements such as requests, tokens or utilization; not an invoice |
| Log Analytics workspace | Query results from an identified workspace and tables |
| Application Insights | Application/agent traces, requests, dependencies and custom events from an identified component |
| Calculated | A derived metric; expose the formula, inputs, input sources and assumptions |
| Sample | Fictional, local demonstration records; not a live source and not a billing claim |
| Unavailable | The evidence was not collected, is unsupported, is missing or cannot be accessed |

Real-data project labels, including a showback chart's X-axis labels, should be
actionable. The expected hover text is **"Go to Azure Cost analysis for project
001"**. Link to the actual project resource-group or validated billing scope;
include a keyboard-accessible source-link alternative where chart labels are
drawn rather than native controls.

Do not infer a deployed dashboard from a naming convention. A generated
`dash-prj001-...` name may not exist. A real resource-group Cost analysis link
does not depend on a separately deployed project dashboard. Preserve compound
project identity so that two factories' `001` projects cannot open the same
incorrect source.

Sample labels must not pretend to open real project resources. A generic
documentation link may be provided, but distinguish it from **Open live source**.
If a metric has several upstream sources, show those sources rather than
presenting "Calculated" as its entire provenance.

For programmatic cost links, follow the documented
[Cost analysis share/deep-link format](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/save-share-views#to-share-a-view).
Encode the full ARM scope once, select the correct cloud/tenant and preserve
RBAC. A URL does not grant permission or prove that billing data was retrieved.
Prefer a real resource-group scope over an unverified dashboard name.

## Business-value realization: a practical model

Use three separate levels of evidence:

| Level | What can be claimed | What cannot be inferred |
|---|---|---|
| Technical activity | Requests, tokens, sessions, latency, errors and tool calls | Business value merely because activity increased |
| Business outcomes | Accepted resolutions, approved documents, completed transactions or other explicitly instrumented outcomes | That every technically successful call produced an accepted outcome |
| Realized value | Auditable cost avoidance, realized revenue, released capacity or another approved outcome valuation | That modeled time saved automatically became payroll savings or cash benefit |

For a time-saving scenario, a defensible model is:

```text
eligible completed outcomes = outcomes accepted under the agreed business definition
modeled minutes saved = eligible outcomes x (baseline minutes - assisted minutes)
modeled capacity value = modeled hours saved x approved fully loaded hourly rate
net modeled value = modeled value - attributable operating cost
cost per accepted outcome = attributable operating cost / eligible completed outcomes
ROI = net value / attributable operating cost
```

These are definitions for the value model, not evidence that the inputs exist.
Do not divide by zero; report undefined ratios as unavailable. Do not silently
mix currencies, periods, gross/net revenue, billed/amortized cost or estimated
token prices. Show negative value where the supported model produces it.

Keep **modeled** and **realized** value separate. Realization should carry a
business owner, outcome definition, measurement period, approved baseline and
valuation evidence. Tag estimates explicitly and explain exclusions such as
shared infrastructure, platform staffing, review labor, data services and
observability ingestion.

The same agent view should show quality and security beside value and cost,
not compress them into a misleading single green score. No Defender findings
collected is not evidence of no security risk. A content-safety signal is not
equivalent to the workload's complete security posture.

### Minimum evidence to instrument

Capture non-sensitive dimensions for factory, scaleset, project, environment,
agent identity/version, operation correlation and measurement period. Business
events should state the outcome type, acceptance/completion evidence, baseline
and assisted effort, valuation basis, currency and source. Correlate to traces
without storing prompts, completions, customer data or personal identifiers
by default.

Use explicit cost allocation evidence when consumption is shared. Keep
unattributed cost visible instead of distributing it silently. Version the
contract so existing clients and automation can evolve compatibly.

## Implementation sequence

| Phase | Deliverable | Completion criterion |
|---|---|---|
| 1. Inventory | Azure-native, Bicep, on-demand and desktop capability matrix | Distinguish dashboard, workbook, report, link and collector |
| 2. Canonical contract | Shared scope, source, value and drill-through semantics | CLI/API, samples and clients agree on the same filtered evidence |
| 3. Native assets | Opt-in workbook/query assets and on-demand workflow in purple | No unexpected deployment or billable resource creation |
| 4. Desktop integration | Consistent MAUI/Tkinter entry points and controls | Existing reports remain usable; sample/live modes are unmistakable |
| 5. Consumer integration | Local orange/Spider consumption of purple changes | No submodule-pointer or customer-settings overwrite |
| 6. Evidence and rollout | Maximized screenshots, guide and explanatory presentation | Filters, data sources and deployment limitations are visible |

Production rollout is separate from local implementation: review telemetry
privacy, RBAC, tag propagation, cost-allocation rules, ingestion/retention costs
and the business baseline with the relevant owners before enabling collection.

## Native capture observations

The read-only Spider capture pass opened the existing shared factory dashboard,
Project 001 resource-group Cost analysis, the Foundry account's processed
inference-token metric, Application Insights, and the new Foundry Operate /
Compliance experiences.

These observations matter when designing honest status and source links:

- The existing shared dashboard had working cost tiles but missing stage/prod
  resource tiles. A project-dashboard link pointed to a dashboard that was not
  deployed. The resource-group Cost analysis destination did work.
- Azure Monitor displayed token activity while the Foundry Operate overview
  displayed no agent data. These are different sources and scopes; neither
  result should be substituted for the other.
- Application Insights showed zero or absent signals in its selected window.
  This is not evidence of agent health, accepted outcomes or realized value.
- Foundry Assets returned HTTP 403. No permissions were changed and no alternate
  access path was used to turn that failed source into an apparently healthy
  empty report.
- Foundry policy and security-posture views showed no policies/recommendations
  for their selected scopes. An empty view does not establish control coverage
  or security compliance.

Screenshots are point-in-time evidence, not live dashboards. Review account and
resource identifiers before distributing the presentation outside its intended
audience.

## Delivered implementation and capture boundaries

The six canonical report families now have shared scope-first filtering,
All-default organizational selectors, explicit missing-data handling, retained
source/formula/input provenance and filtered exports. MAUI uses compact metric
cards with expandable lineage rather than allowing long source details to push
the overview below the fold. Both clients retain readable compound project
identities on their charts.

Real project chart labels and keyboard-accessible links use the documented
Cost analysis route. The capture pass also imported one manually recorded
Project 001 portal observation into each client: **USD 73.49 actual cost**.
Those screenshots explicitly represent a portal snapshot, not a new automatic
billing collection. The direct Cost Management query attempt was rate-limited;
no fabricated successful API collection replaced it.

The original canonical sample-provider interoperability case was exercised
against the actual native importer: **8.25 actual / 7.84 amortized**, with
**130 modeled minutes saved** and **one recorded security finding**.
The sample provider label remains **Sample fixture**, and no sample live links
are generated. Explicit sample markers cannot be promoted to live. Live native
actual/amortized observations still require Cost Management evidence.

The shared flat observation file can feed both the primary report engine and
the canonical-to-native adapter. A bounded native-to-canonical exporter also
supports the represented metrics, subject to exact-grain and explicit
classification rules; it is not an arbitrary event conversion or lossless
round trip for every canonical field. Native qualified value requires
explicit quality approval; primary modeled time savings from supplied numeric
inputs are not themselves a quality certification.

The review material includes maximized MAUI/Tkinter report and operational
views, All-versus-Project-001 examples, expanded provenance, imported real-source
examples, and selected actual Azure/Foundry portal views. Full-resolution PNGs
are supplied with the explanatory PowerPoint; wide charts/tables can require
horizontal scrolling beyond the captured viewport.

**Not performed:** Azure deployment, telemetry ingestion, schedule creation,
permission changes or live rendering of the new workbook. Its grid uses the
verified text-link renderer and a visible tooltip-description column; a
custom workbook hover renderer is not claimed. Existing native portal
dashboards remain deployment-specific and do not inherit the desktop filters.
Production value realization still needs approved instrumentation, allocation,
baseline and outcome evidence.

The delivery contains **89 full-resolution screenshots** (8 Azure-native,
56 MAUI and 25 Tkinter) and the **98-slide**
`AI-Factory-Monitoring-FinOps-Value.pptx`, with a `capture-index.json` describing
each view, mode, scope and source. The requested output folder uses the name
`screebshots`. Office applied a sensitivity label to the final PowerPoint;
that protection was preserved. Open it with an authorized Office account and
review the audience before sharing.
