# AI Factory monitoring: value, cost and trust

Use one monitoring story across four delivery layers: **Azure built-ins**,
**AI Factory native assets**, **MAUI Monitoring**, and **Tkinter Dashboards /
CLI / API**. These layers complement each other; a desktop chart is not a
replacement for the native billing or telemetry source.

This guide covers the reusable **purple** module, the **orange** consumer
repository, and the two desktop clients. Native capability/source review:
**22 September 2026**; My Project and Cost extension: **18 September 2026**;
read-only native Portal/Foundry capture: **21 September 2026**.
Local artifacts and sample captures are not evidence
that a resource has been deployed in Azure.

## Start here: one monitoring story, four delivery groups

Organize the experience along two axes. **Value, cost, quality and security**
describe the question; **delivery group** describes where the answer runs.
Do not make users choose a technology before they can ask a business question.

| Delivery group | What exists | Best use |
|---|---|---|
| **Azure built-in & Foundry** | Cost analysis, budgets/exports, Monitor Metrics/Logs, Application Insights, Foundry monitoring/tracing/evaluations, Defender and optimization experiences | Inspect Microsoft's native financial, operational and security evidence |
| **AI Factory native** | Shared factory and project Portal dashboards, Application Insights dashboard, My Project workbook and opt-in agent evidence workbook | Repeatable saved Azure views deployed from the purple Bicep modules |
| **On-demand reports** | Foundry tokens, project/cost-center showback, deployment usage and the offline agent observation report | Generate reviewed report artifacts from existing telemetry or supplied evidence |
| **Custom dashboards** | The same six canonical reports in MAUI/Tkinter/CLI/API; project-scoped Retail, Booking, Support and Cost views; existing operational panels | Compare useful outcomes, cost and security together without creating a second billing source |

The common entry is a **Monitoring hub**, with the four delivery
groups, source readiness, scope limitations and direct actions into the
existing views. The question-oriented report navigation is **Value and
adoption / Usage and cost / Quality and reliability / Security and governance**.
Keep operational inventory, capacity, lifecycle and quota accessible rather
than removing them to make the layouts look identical.

Use **AI Factory -> Scaleset -> Project -> Environment**, initially All, for
portfolio reports. My Project deliberately requires one concrete placement and
adds local dates, store and time zone. Native Azure pages retain their own
controls; an application filter is not automatically an Azure Portal filter.

| Read next | Contents |
|---|---|
| [1. Azure-native capabilities](#1-azure-native-dashboards-and-finops-capabilities) | What Azure and Foundry already provide, pricing boundaries and availability |
| [2a. Bicep assets](#2a-bicep-dashboards-and-telemetry) | Saved dashboards/workbooks and diagnostic prerequisites |
| [2b. On-demand reports](#2b-on-demand-dashboards-and-reports) | Collectors, offline reducers and reviewed execution |
| [3. MAUI Monitoring](#3-maui-monitoring) | Custom views and client/backend responsibilities |
| [4. Tkinter Dashboards](#4-tkinter-dashboards-and-canonical-reports) | Custom views, canonical reports, CLI and API |
| [My Project](#my-project-chat-dashboard-templates) | Retail, Booking, Support, feedback, usage and attributed cost |
| [Business-value realization](#business-value-realization-a-practical-model) | Evidence model, financial qualifications and instrumentation |
| [Implementation sequence](#implementation-sequence) | Cross-repository delivery and rollout boundaries |

### Quick answer: can an agent's business value be shown beside cost and security?

**Yes, with explicit business evidence.** Native Foundry already supplies
technical activity, tracing and evaluation signals. Application Insights
funnels and HEART workbooks can display instrumented conversion and task
success. Neither knows automatically that an accepted business outcome saved
money or generated revenue.

Show four neighboring evidence panels: **accepted outcomes**, **modeled or
verified benefit**, **attributable cost**, and **quality/security coverage**.
Keep modeled time savings separate from finance-approved realized benefit.
Keep input/output/cached-token usage separate from token-price estimates and
billing-derived charges. Missing findings mean unknown security coverage, not
"secure". An approved valuation and matched cost period/currency are
prerequisites for a defensible financial return.

## My Project: chat dashboard templates

**My Project** is a separate project-focused dashboard, not a renamed
whole-factory report. Select a concrete **AI Factory / Scaleset / Project
number / Environment**. There is no All-project choice in this view. The
compound identity prevents Project `001` in one factory from including another
factory's Project `001`.

Select the business template in a dropdown. **Retail chat** is the default.

| Shared across every template | Retail chat | Booking chat | Support chat |
|---|---|---|---|
| From/To, last day/7 days/30 days, Apply/Reset, Store/location and time zone | Cart opens | Planned bookings | Active cases |
| Conversations, questions, pseudonymous unique devices and questions/conversation | Products added | Historic/completed bookings | Solved cases |
| Thumbs up/down, satisfaction, rated/unhappy conversations, single-question rate | Carts sent to phone | Status as of selected end | In-progress cases |
| Conversations and questions per day; feedback per day; questions/conversation per day | Add-to-cart and sent-to-phone rates | Same common chat charts | Same common chat charts |

The template changes only the business-outcome section. Identical evidence,
project, date and store filters must produce identical shared usage/feedback
metrics across all three templates.

### Filters and calculation definitions

Dates are **inclusive local calendar dates**, limited to 30 days. The default
period is seven days. The selected IANA time zone controls day boundaries,
including daylight-saving changes; UTC query boundaries are derived from it.
Store/location defaults to All within the selected project.

| Metric | Definition and important qualification |
|---|---|
| Conversations | Distinct `(store, conversation_id)` with at least one user question in the selected window |
| Questions | Unique submitted question observations; retry events must reuse stable question identity |
| Unique devices | Distinct application-supplied pseudonymous device IDs; not people and not fingerprinted identities |
| Questions/conversation | Questions divided by active conversations in the same scope/window, not an average of daily ratios |
| Three-or-more question rate | Active conversations with at least three in-window questions / all active conversations |
| Thumbs up/down | Submitted user ratings, not a model's predicted satisfaction |
| Satisfaction rate | Positive ratings / all ratings; unavailable when there are no ratings, not 0% |
| Rated conversations | Active conversations with feedback / active conversations |
| Unhappy conversations | Active conversations with at least one negative rating |
| Single-question rate | Active conversations with one in-window question / active conversations; does not establish abandonment |
| Cart opens / sent-to-phone | Explicit application events; a send event contains no phone number |
| Products added | Sum of explicit positive integer product quantities |
| Add-to-cart rate | Active conversations adding products / active conversations |
| Sent-to-phone rate | Active cart-open conversation cohort that sent a cart / active cart-open cohort |
| Planned bookings | Latest recorded booking status is planned or confirmed |
| Historic bookings | Latest recorded booking status is completed; canceled is excluded |
| Active cases | Latest recorded case status is open or in progress |
| Solved / in-progress cases | Latest recorded status is solved / in progress; in progress is a subset of active, not an extra disjoint total |

Bookings/cases are **state**, not counts of status-change events. Supplied
history or snapshots must establish the state before the selected period and
include changes through its exclusive end boundary. Missing baseline coverage
means unavailable state totals, not a falsely empty inventory.

Common charts use the same filtered events and definitions as the cards.
Every selected date is represented. A channel with explicitly complete,
empty telemetry can show zero counts; a missing channel shows unavailable.
Undefined ratios remain null. Summing daily distinct conversations/devices
does not reproduce period-wide distinct counts.

### What Foundry and OpenAI can actually supply

| Evidence | Azure source | What must be instrumented by the application |
|---|---|---|
| Model requests and input/output tokens | Azure Monitor metrics on Foundry / Azure OpenAI accounts | Project/store attribution when the account is shared |
| Agent/model traces and operational behavior | Foundry connected Application Insights / OpenTelemetry | A stable application conversation/question mapping when spans include retries, tools or multiple model calls |
| Real user questions, conversations and devices | Application Insights custom events | Stable pseudonymous IDs and a question-submitted event |
| Thumbs up/down | Application Insights custom events | Explicit user feedback linked to the question/conversation |
| Cart activity, bookings and support cases | Application Insights custom events or approved operational exports | Business events and authoritative state updates |

One model request is **not** necessarily one user question. Foundry evaluation
scores are **not** actual thumbs-up/down feedback. OpenAI does not know that a
shopping cart was opened, a booking completed or a case solved unless the
application records that outcome.

Authoritative references:
[Foundry tracing](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup),
[Application Insights custom events](https://learn.microsoft.com/en-us/azure/azure-monitor/app/usage#usage-analysis-with-custom-events),
[Foundry/OpenAI platform metrics](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-cognitiveservices-accounts-metrics).

### Application event contract

The versioned evidence envelope is `aifactory.my-project-events.v1`.
For Azure collection, emit an Application Insights custom event named
**`aifactory.chat`**. Its properties carry the scope and event fields:

```javascript
appInsights.trackEvent({ name: "aifactory.chat" }, {
  event_id: eventId,
  factory: "my-factory",
  scaleset: "001",
  project: "001",
  environment: "dev",
  store: "store-a",
  kind: "question",
  conversation_id: conversationId,
  question_id: questionId,
  device_id: approvedPseudonymousDeviceId
});
```

This is an instrumentation example, not code that the dashboard deploys into
the chatbot automatically. Reuse a stable event/question ID when retrying
delivery. Use `kind: "feedback"` with `rating: "up" | "down"` for actual user
feedback. Domain event kinds are `cart_open`, `cart_add` (positive integer
`quantity`), `cart_send`, `booking_status` and `case_status` (opaque `entity_id`
and explicit status).

Do **not** include question text, prompts/completions, user names, email
addresses, phone numbers or cart contents. Device identity must follow the
application's consent/privacy policy; do not introduce device fingerprinting.
Report/export outputs contain aggregates, not raw device or conversation IDs.
Exact distinct/funnel reporting requires unsampled business events. Sampled
events cannot be repaired by multiplying distinct counts by `ItemCount`.

### API and CLI

The existing authenticated Python API exposes:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/my-project/templates` | Template choices, shared sections, sample scope choices and supported limits |
| `POST /api/v1/my-project/report` | The project-scoped canonical report |
| `POST /api/v1/my-project/export` | The same filtered aggregate projection, without raw identifiers |

All use the existing `X-API-Key` protection. Example request:

```json
{
  "template": "retail-chat",
  "source": "sample",
  "scope": {
    "factory": "Demo AI Factory",
    "scaleset": "demo-east",
    "project": "001",
    "environment": "dev"
  },
  "from_date": "2026-09-11",
  "to_date": "2026-09-17",
  "time_zone": "Europe/Berlin",
  "store": "All"
}
```

The report contract is `aifactory.my-project-report.v1`. MAUI and Tkinter
render its sections, metrics and daily series; they do not calculate their
own competing conversation, feedback or funnel totals.

From the Python/Tkinter repository:

```powershell
python -m src.my_project_dashboard --templates
python -m src.my_project_dashboard --template retail-chat --source sample `
  --factory "Demo AI Factory" --scaleset demo-east --project 001 --environment dev `
  --from-date 2026-09-11 --to-date 2026-09-17 --time-zone Europe/Berlin --store All
```

Use `booking-chat` or `support-chat` for the other templates. Imported evidence
and explicit Azure collection are separate modes; neither falls back to
fictional samples when access, telemetry or instrumentation is missing.

### Read-only Azure collection

The Azure binding explicitly identifies the selected scope, tenant,
subscription, Application Insights component and optional Foundry/OpenAI
accounts. The collector resolves the component's actual linked Log Analytics
workspace, checks the selected CLI tenant/subscription, and queries only
`aifactory.chat` events for that exact component and project scope.

Coverage flags declare which application channels are instrumented. They are
operator assertions, not facts inferred from an empty query. Booking/case
coverage also requires a reviewed `state_history_start` with sufficient
retained baseline data. Event retrieval is bounded; overflow, access failure
or sampled-event counts are reported explicitly rather than silently
truncated into plausible totals.

Native account token/request totals are collected only when the binding
explicitly declares the accounts project-exclusive. These supplementary
operational metrics cannot honor a store filter; a concrete store selection
must not show broader account totals as if they were store-attributed.
They remain distinct from the shared user-question and business-event cards.

No resources, roles, diagnostics, instrumentation or schedules are created by
opening this dashboard. Production telemetry requires the application's
existing approved ingestion path, query RBAC and network access.

### My Project Cost tab

The **Cost** tab shares the exact project, dates, time zone and store selection
with Usage & outcomes. It is reusable across Retail, Booking and Support chat.
It shows:

- Cost per day, with **actual**, **allocated** and **estimated** series kept
  separate for every currency.
- Cost per day per **chat session**.
- Cost per day per **IP group**, using pseudonymous network keys rather than
  raw IP addresses.
- Meter details for **tokens**, **speech** and **other pay-as-you-go** services,
  including quantity, unit, applicable rate and calculation/source evidence.
- Explicit **unattributed** costs when session, network or store allocation is
  not available.

These billing bases are alternatives, not additive revenue/cost categories.
Do not add an estimated token charge to the corresponding actual Azure bill,
or add an allocation back onto the project cost it allocates.

| Cost evidence | Supported interpretation |
|---|---|
| Native Cost Management actual cost | Billing-derived daily project-resource-group charge; no session/IP attribution is implied |
| Application meter quantity + reviewed rate | Price-based estimate: `quantity / price_unit_quantity * unit_price` |
| Explicit allocated charge | A share of billed cost with a recorded allocation method and billing reference |
| Missing session/IP keys | Unattributed amount, not spread equally across observed sessions |

Input/output/cached tokens can have different meters and rates. Speech
recognition duration and speech synthesis characters are different units.
Other usage such as searches, storage operations or compute should keep its
own meter/unit. PTU capacity, reservations and fixed infrastructure must not
be disguised as PAYGO token charges. Rates require an explicit reference to
the reviewed model/service, deployment/region, currency and price period;
the dashboard does not invent prices.

**IP attribution is not person attribution.** NAT, shared networks and VPNs
can place multiple users/sessions in one IP group. The application should
produce `network_key = "ipkey_" + HMAC_SHA256(rotating_secret, normalized_ip)`
at its trusted edge. Do not send the raw IP or HMAC secret to the dashboard.
Use a retention/rotation policy approved for the application. Session keys
are likewise opaque, prefixed `session_`; neither should contain names,
addresses or chat text.

The cost evidence contract is `aifactory.my-project-costs.v1`. Application
Insights cost events are named **`aifactory.chat.meter`**, separate from
`aifactory.chat` usage/outcome events. Meter events include the same scope
properties plus pseudonymous session/network keys, service, meter, quantity,
unit, currency and basis. Estimated rows supply `unit_price`,
`price_unit_quantity` and `rate_reference`; actual rows supply `amount` and
`evidence_reference`; allocated rows additionally supply `allocation_method`
and `billing_reference`.

API: **`POST /api/v1/my-project/cost`**, using the same scope/date/store request
shape and explicit source mode. Cost evidence is a separate input from the
chat-event evidence; do not rename one contract to the other.

```powershell
python -m src.my_project_costs --source sample `
  --factory "Demo AI Factory" --scaleset demo-east --project 001 --environment dev `
  --from-date 2026-09-11 --to-date 2026-09-17 --time-zone Europe/Berlin --store All
```

For read-only Azure cost collection, add `cost_coverage` (`metering` and
`billing`) to the reviewed Azure binding. Optional native billing additionally
requires `billing_scope` for the exact project resource group and
`billing_scope_project_exclusive: true`. Azure Cost Management daily buckets
are UTC: select **UTC** to include those billed daily totals. A local-time
metering chart is not silently relabeled as UTC billing.

Native billing rows have no session/IP/store keys and remain unattributed.
A specific store selection cannot include broader resource-group billing
as if Azure supplied store attribution. If billing is rate-limited, denied or
incomplete, its coverage stays unavailable; the UI does not substitute
estimates or initialize a fictitious zero. Current-period charges may change
before invoicing.

## 1. Azure-native dashboards and FinOps capabilities

| Native surface | Usage, tokens, cost and security coverage | Important boundary |
|---|---|---|
| [Azure Monitor Metrics / Foundry models](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/monitor-models) | Requests, input/output tokens, latency, errors, supported cache counters and PTU utilization | Platform measurements are not an invoice. Metrics depend on deployment type; organizational tags are not automatically metric dimensions. |
| [Azure Monitor Workbooks](https://learn.microsoft.com/en-us/azure/azure-monitor/visualize/workbooks-data-sources) | Parameterized views over Metrics, Logs/Application Insights, Resource Graph and ARM APIs | A workbook can be deployed with Bicep, but it does not create missing telemetry or attribution. |
| [Application Insights usage](https://learn.microsoft.com/en-us/azure/azure-monitor/app/usage) | Users, sessions, events, funnels, retention and custom business events | Requires instrumentation. Business actions and organizational dimensions must be supplied by the application. |
| [Cost Management Cost analysis](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/customize-cost-analysis-views) | Billing-derived actual/amortized cost, forecast, resource/service/tag breakdown and saved views | A saved cost view is not a workbook. Customizable views do not group by multiple attributes simultaneously. |
| [Budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets) and [exports](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-improved-exports) | Actual/forecast budget alerts and recurring cost datasets, including FOCUS exports | Budget evaluation is daily and does not stop spending. Exports are reporting inputs, not agent outcome evidence. |
| [Foundry agent Monitor](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard) | Application Insights-backed agent tokens, latency, run success, evaluations and configured red-team results | Documentation marks agent metrics, recurring evaluations, red-team scans and dashboard alerts as preview. These are portal experiences, not the same asset as a custom workbook. |
| [Foundry tracing](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup) | Run/tool/model trace details for supported agents | Current documentation distinguishes GA tracing for prompt/hosted agents from preview workflow/external-agent tracing. Custom application code still needs instrumentation. |
| [Foundry Control Plane](https://learn.microsoft.com/en-us/azure/foundry/control-plane/overview) | Permission-aware agent inventory and operational views; token-based estimated agent cost | Operate experiences are documented as portal-only. A token-cost estimate is not reconciled Azure billing or complete workload cost. |
| [Foundry cost management](https://learn.microsoft.com/en-us/azure/foundry/concepts/manage-costs) | Model/agent operational estimates and links to Cost Management; preview project billing attribution for Models sold by Azure | Estimates exclude negotiated discounts and provisioned throughput; coverage varies by agent/provider. Marketplace and shared-service attribution must not be assumed. |
| [Defender for Cloud AI threat protection](https://learn.microsoft.com/en-us/azure/defender-for-cloud/ai-threat-protection) and [AI posture](https://learn.microsoft.com/en-us/azure/defender-for-cloud/ai-security-posture) | Threat alerts, posture recommendations, inventory and attack-path evidence | Threat protection is GA and currently scans text. Agent discovery/posture is preview and documentation requires Agent 365 from July 2026; account/project posture is a separate scope. |
| [FinOps toolkit Optimization workbook](https://learn.microsoft.com/en-us/cloud-computing/finops/toolkit/workbooks/optimization) | Advisor, idle resources, usage/rate optimization and potential savings | Deployable workbook; recommended savings are opportunities, not proof of realized business value. |
| [FinOps hubs](https://learn.microsoft.com/en-us/cloud-computing/finops/toolkit/hubs/finops-hubs-overview) | FOCUS export ingestion, normalization and cross-account analytics with optional ADX/Fabric and Power BI | Deployable toolkit infrastructure, not a free managed dashboard; infrastructure and applicable BI licensing have costs. |
| [AKS cost analysis](https://learn.microsoft.com/en-us/azure/aks/cost-analysis) | Cluster/namespace compute, storage, network and idle/system/unallocated cost | Standard/Premium AKS and supported billing agreements; not a task-level business-value collector. |
| [Azure ML endpoint monitoring](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-monitor-online-endpoints?view=azureml-api-2) | Endpoint requests/latency/status and deployment CPU/GPU/memory/disk | Model quality needs additional monitoring/ground truth; infrastructure health does not establish accepted business outcomes. |

**Availability as reviewed on 20 September 2026:** the new Foundry portal is
GA, but Build Monitoring and Operate Overview/Assets/Compliance remain
Preview. Application Insights' Agents view is also Preview. Tracing is GA
for prompt/hosted agents and Preview for workflow/external agents. Use the
[feature-readiness table](https://learn.microsoft.com/en-us/azure/foundry/concepts/general-availability)
instead of describing every experience as GA because its parent portal is GA.
Agent-specific security requires the appropriate
[Agent 365 licensing from 1 July 2026](https://learn.microsoft.com/en-us/defender-xdr/security-for-ai/transition-agent-security-to-agent-365);
Defender for AI Services model protection is a different coverage boundary.

These are public product capabilities, not assertions that a selected tenant
has the required plan, region, permissions, diagnostic settings or telemetry.
Budget alerts are not spending caps. Advisor recommendations are potential
savings, not realized savings. Application Insights ingestion/retention,
evaluation runs and optional reporting infrastructure can themselves add cost.

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

### Project resource groups, shortcuts and Cost analysis

The project Portal dashboard retains the **resource-group resource list on the
left** and **native Cost analysis on the right**, both scoped to the selected
project resource group. Direct shortcuts below open **AI Foundry, Storage,
Key Vault, AI Search and Application Insights**. Application Insights uses the
same explicit resource-ID override as the companion workbook, when supplied.
The Cost analysis tile shows this month's **ActualCost** and Azure's forecast;
the direct Cost analysis link, Budgets and Cost Alerts remain available.

The factory landing dashboard keeps its common/project resource groups and
their separate Cost analysis tiles. Each project now supports the same five
shortcut types, showing only resources returned by existing inventory discovery
(fewer shortcuts when a type is absent). The Bicep project shortcuts retain
their configured naming bindings; they do not themselves provision the target
services. Workbook and business-value reports supplement this resource/cost
layout rather than replacing it. These are local source changes; existing Azure
dashboards require a separately authorized dashboard deployment to update.

### Native My Project generated with the project dashboard

`modules\projectDash01.bicep` now deploys a companion
**My Project - Usage and Cost** Azure Monitor workbook and adds an entry tile
below the existing project resource/service inventory. The existing resource
links and native Cost Management link remain in place.

The workbook provides **Usage & outcomes / Cost** navigation and
**Retail / Booking / Support** templates. Shared usage, customer-feedback and
three daily charts do not depend on the business template. The Cart section
is replaced by booking or case state cards. Cost includes separate
actual/allocated/estimated amounts, a single-currency chart selector,
per-day/session and per-day/pseudonymous-IP-group tables, and meter/rate details.

The workbook is a native Azure resource; it does **not** call the locally
hosted MAUI/Tkinter API. Its KQL reads the same `aifactory.chat` and
`aifactory.chat.meter` Application Insights events. The API hosts retain one
canonical Python implementation. Native query definitions mirror the common
cohort, date, feedback, currency and attribution rules, with the limitations
below made explicit rather than claiming automatic billing or telemetry setup.

| Parameter on `projectDash01.bicep` and phase 10 | Default / behavior |
|---|---|
| `enableMyProjectDashboard` | `true`; creates the saved workbook and dashboard entry. `false` omits them from this deployment, not deletion of an existing workbook. |
| `myProjectApplicationInsightsResourceId` | Empty uses the project's naming-convention Application Insights ID; override with the real component ID when appropriate. |
| `myProjectLogAnalyticsResourceId` | Empty uses the existing common workspace naming-convention ID. |
| `myProjectFactoryId`, `myProjectScaleSetId` | Empty requires explicit selection from this component's scoped event dimensions. Supply the canonical opaque IDs from the selected register, not an invented RG-derived label. |
| `myProjectTelemetryEnvironment` | `test` deployment maps to `stage`; otherwise the deployed environment. Override only to match the instrumented dimension. |
| `myProjectTimeZone` | `Europe/Berlin`; IANA time zones and DST-aware local-midnight conversion. |
| `myProjectCoverage` | `{}`: all channels are unavailable until explicitly reviewed. |
| `myProjectStateHistoryDays` | `90`, bounded 30-90; complete booking/case baseline must exist within that history. |

Coverage keys are `questions`, `devices`, `feedback`, `cart`, `bookings`,
`cases`, `stateBaseline`, `metering` and `billing`. Their defaults are false.
The saved dropdown values are explicitly lowercase `false` / `true`, matching
their options; ARM's `string(bool)` produces `False` / `True` and must not be
used for those defaults. Unreviewed coverage is a selected false value, not
an unset required parameter.
Review the assertions again after changing scope, store or dates. Coverage is
not inferred from the existence or absence of rows, and query/permission
failures do not become healthy zeros.

In **View > Model tokens**, a sole Foundry/OpenAI account in the exact project
resource group is selected automatically. Multiple accounts require an explicit
choice; no account produces an unavailable state, never a subscription-wide
fallback. These native token reports do not depend on business-event coverage.

The project portal dashboard has a native **Cost Analysis** chart beside its
resource-group tile, using the same `CostAnalysisPinPart` schema as the shared
factory dashboard. It shows accumulated **ActualCost** for **this month** with
Azure's **Forecast** KPI enabled, scoped to that exact project RG. Currency
comes from Azure; an unavailable forecast is not replaced by a linear estimate.
Resource-group actuals and forecast are not added to app-meter cost estimates.
Every My Project workbook view also exposes an always-visible native Cost
Analysis link, independent of the coverage, factory, store and session filters.

The deployed project number and telemetry environment are fixed in the
workbook. Every query filters the **exact Application Insights component**
inside the workspace before applying factory/scaleset/project/environment,
store and local-date filters. Identical event IDs in different stores do not
collide for chat usage; conflicting duplicates within the same identity
invalidate results. Distinct conversation/device counts are exact rather than
approximate `dcount` estimates.

Phase `esml-genai-1\10-aifactory-dashboards.bicep` forwards the parameters and
returns `myProjectWorkbookId`, `myProjectWorkbookName`,
`myProjectWorkbookUrl` and `myProjectSourceIds`, also included in its existing
dashboard output objects. The workbook module and its query assets are:

```text
modules\myProjectWorkbook.bicep
modules\workbooks\my-project\context.kql
modules\workbooks\my-project\usage.kql
modules\workbooks\my-project\cost.kql
```

This adds only a saved workbook, **not** a workspace, diagnostic setting,
ingestion pipeline, role assignment or scheduled collector. Existing telemetry,
query RBAC and network access are prerequisites. Native Cost Management remains
a separate project-RG billing destination with its own filters; the workbook's
session/IP costs come from recorded meter evidence. There are no embedded
fictional samples presented as live native data.

**Deployment status (20 September 2026):** the approved consumer-driven
dashboard-only rollout deployed the project dashboards and 37-item My Project
workbooks for Dev projects 001 and 002, and refreshed the shared factory dashboard
without losing either project's inventory. Orange retained ownership of
`variables.json` and pinned purple commit `76727432`. The updated workbooks have
37 items, valid lowercase coverage defaults and single-account auto-selection.
Both project dashboards again contain native RG ActualCost charts with Azure
forecast enabled. The ADO dashboard-only deployment runs were 2345 and 2346.

Eight aggregate queries from each actual saved workbook were executed against
the existing workspace. Project 001 returned real per-model input, output and
cached-token observations; Project 002 returned no matching request-usage rows
for the selected window, not measured zero. Missing business events and
session/IP cost evidence remain unavailable. No telemetry was synthesized or
ingested, and no Azure roles or underlying infrastructure were changed.
**Rendered Portal inspection (21 September 2026):** both project dashboards
visibly render their native accumulated actual-cost and forecast charts. Both
workbooks select all nine coverage defaults and execute usage validation without
the former missing-parameter blocker.

**Remaining defect:** both Model tokens views auto-select the correct project
account, but their runtime scope check still reports `AccountSelected=false`
and `Unavailable - no valid scoped account`, hiding the native metric charts.
This is a workbook parameter/scoping issue, not proof of missing token telemetry.
The earlier direct KQL checks supplied explicit parameter values and did not
exercise the Portal's parameter substitution. The deployment was left unchanged
as requested; a token-view rendering correction has not been deployed.

**September 22 local continuation:** the source now uses a scalar account ARM ID,
explicitly serialized inventory, and a separately validated Metrics resource
binding. It accepts documented/legacy scalar, JSON-string and singleton-array
selection forms, while rejecting multiple accounts, wrong resource kinds and
out-of-RG identities. The validation table exposes the selection/inventory shapes
and whether the Metrics binding matches. This is local hardening, not proof of
the exact earlier runtime serialization or a deployed fix. Real Portal acceptance
is still required after a reviewed dashboard-only rollout.

### Keeping MAUI and Tkinter API hosts in sync

Both hosts package the same `src.api` and My Project/Cost reducers from the
Tkinter repository. Both package build scripts now run an authenticated,
offline semantic comparison against the canonical source: the template catalog,
Retail/Booking/Support and Cost, with All stores and a selected store. A mismatch
fails the build. Generation timestamps are ignored; scope, values, provenance
and warnings are not.

`POST /api/v1/my-project/scopes`, with `aifactory_folder` set to an
`azurefactory` register root, supplies registered placement identities without
migration, Azure discovery or a default live-project choice. Tkinter uses the
same resolver; MAUI can load these scopes directly without first visiting the
Factory catalog page. Source/identity changes invalidate old scope results.

Spider validation uses:

```text
C:\code\code_py_25\002_demo\azuredevops\aifactory-spider-001\azurefactory
```

The local validation artifacts are isolated under the consumer's ignored
`reports-out\native-my-project-20260918` folder; customer settings and the
submodule pointer are not replaced. The legacy sibling `aifactory` folder is
not substituted for this register. Published accelerator bundles remain
separately commit/version-pinned: local native-template changes still follow
the normal publication/consumer-update process before an actual deployment.

### Native model/deployment token consumption

The project dashboard also exposes **Model tokens** in its My Project workbook.
This view is independent of application-specific factory/store event filters:
it discovers only Foundry (`AIServices`) and Azure OpenAI accounts inside the
exact deployed project resource group.

Two source families are shown **separately**, never added together:

| Source | Input/output | Cached input | Grouping |
|---|---|---|---|
| Foundry / Models platform metrics | `InputTokens`, `OutputTokens` | `cacheReadInputTokens`, when that account/model emits a series | Account, deployment, model, version |
| Standard Azure OpenAI platform metrics | `ProcessedPromptTokens`, `GeneratedTokens` | The cache-count metric may be unavailable; a cache-hit percentage is not substituted | Account, deployment and version; this metric schema does not expose `ModelName` |
| `AzureDiagnostics` / `AzureOpenAIRequestUsage` | Explicit request-usage counters | Explicit `cachedTokens` or a supported response-usage cached-token field | Observed account, deployment, model and version |

Use the token time-range control for both native Metrics and request-log detail.
Deployment/model selectors further narrow the log table and its daily series;
they do not silently claim to filter the separate native metric tables.
The report shows source freshness, missing fields, conflicts and deduplication
coverage. A missing metric series or missing cached field stays **Unavailable**.
An explicitly emitted cached value of zero is a measured zero.

Flat request-usage properties such as `promptTokens`, `generatedTokens` and
`cachedTokens` can be numeric arrays. The query validates every element before
summing them. It does not coerce missing or malformed counters to zero. Cached
tokens are a subset of inclusive input tokens: **do not add input + cached**.
No cache-rate-times-input calculation is presented as observed usage.

Existing diagnostic routing must send `AzureOpenAIRequestUsage` to the selected
workspace. Metrics can remain available independently of diagnostic exports.
Request logs are not necessarily exhaustive and can be older than platform
metrics. No prompts, response content or raw user/IP identifiers are projected.

### Dashboard-only ADO and GitHub Actions workflows

Manual pipeline templates are supplied alongside the existing project pipelines:

```text
copy_to_local_settings\azure-devops\esml-yaml-pipelines\esml-infra-project\infra-project-dashboards.yaml
copy_to_local_settings\github-actions\infra-project-dashboards.yml
scripts\deploy-dashboards-only.py
```

They consume the same persistent `variables.json` and select one environment:
Dev uses `dev`; Stage/Test and Prod use `stage_prod`, with their own exact
subscription selectors. No selected-environment subscription falls back to Dev.
The project-number input is an assertion against the configuration, not a
request to relabel another project's configuration.

The default is **plan**. Explicit **deploy** updates only:

- The selected project's Azure Portal dashboard and My Project workbook.
- The shared incremental factory dashboard, preserving existing project and
  environment inventory while reconciling accessible resources.
- The associated incremental ARM deployment records.

The runner compiles and checks an allowed resource-type list before writing.
It does not create missing resource groups, grant roles, create identities,
enable diagnostics or rerun networking/Foundry/compute deployment. Read-only
`existing` resource references used by naming are not resource creation.

Use the existing environment service connection/OIDC identity. Runner selection
can explicitly choose a hosted runner when self-hosted agents are offline;
it does not start or provision a build VM. The new ADO pipeline needs
authorization to use its selected existing service connection.

Example read-only plan from a consumer checkout:

```powershell
python .\azure-enterprise-scale-ml\environment_setup\aifactory\bicep\scripts\deploy-dashboards-only.py `
  --consumer-root . --repo-root azure-enterprise-scale-ml `
  --variables-json aifactory/variables.json --environment dev --project 001 --mode plan
```

Nested registered project `variables.json` paths are supported. Canonical
factory/scale-set identities can be resolved from the matching `azurefactory`
register or supplied explicitly; resource naming is not used as a substitute
for those telemetry identities. Configuration contents and credentials are not
uploaded as build artifacts.

Use **dashboard-only deploy**, rather than rerunning the general infrastructure
pipeline, when only visualizations need refreshing. Stage/Prod/project targets
whose resource groups do not exist remain an explicit missing-deployment
condition; this workflow does not provision those environments.

### 2a. Bicep dashboards and telemetry

The module inventory contains three portal-dashboard declarations. These are
not three Foundry agent-ROI dashboards.

| Asset | Purpose and source | Scope / caveat |
|---|---|---|
| [`aifactory-dash-01.bicep`](../../../environment_setup/aifactory/bicep/modules/aifactory-dash-01.bicep) | Factory/shared landing-zone navigation and resource-group cost/inventory tiles | Configured factory/scaleset/environment resources; tiles can reference resources not yet deployed |
| [`projectDash01.bicep`](../../../environment_setup/aifactory/bicep/modules/projectDash01.bicep) | Project resource dashboard and native resource/cost navigation | Actual project resource IDs determine scope; a generated dashboard name does not prove deployment |
| [`appinsightsDashboard.bicep`](../../../environment_setup/aifactory/bicep/modules/appinsightsDashboard.bicep) | Application Insights operational dashboard | Application instrumentation is required; not a cost or realized-value collector |
| [`monitoring/agentMonitoringWorkbook.bicep`](../../../environment_setup/aifactory/bicep/modules/monitoring/agentMonitoringWorkbook.bicep) | Opt-in usage/token, quality, value, cost and security workbook over evidence-backed observations | One common-RG workbook, existing explicit workspace; five All-default scope selectors plus time; no collection, ingestion or RBAC deployment |
| [`myProjectWorkbook.bicep`](../../../environment_setup/aifactory/bicep/modules/myProjectWorkbook.bicep) | Project-scoped chat templates and daily/session/IP-group Cost views, linked from `projectDash01` | Fixed project/component; explicit factory/scaleset and coverage; existing `aifactory.chat` / `aifactory.chat.meter` telemetry |

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
| `native_monitoring.py` + `native_monitoring_v2.py` | Offline six-family evidence report, JSON/CSV, lossless v2 interchange and prepared AppEvents | Already-collected, explicitly sample or live observations; not a new Azure collector; native verified-finance calculations remain unavailable |
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

`enableAgentMonitoring` defaults to `false` in phase
`esml-genai-1\10-aifactory-dashboards.bicep`. Enabling requires the explicit
`agentMonitoringWorkspaceResourceId` of an existing Log Analytics workspace.
The standalone module uses `workspaceResourceId`. An existing-resource read
resolves the workspace's `customerId`; the deployment identity therefore needs
workspace read access. Empty, wrong-type, missing or inaccessible references
fail rather than creating or guessing a workspace.

Phase 10 deploys one stable workbook in the **common resource group**, with
optional project-dashboard navigation rather than one duplicate workspace-wide
workbook per project. Outputs are `agentMonitoringWorkbookId` and
`agentMonitoringWorkbookUrl`. Disabling omits future deployment; it does not
delete an already deployed workbook. There is no automatic telemetry sink,
role assignment, collection schedule or application instrumentation.

The separate **dashboard-only runner does not deploy this workbook**. Supply
the reviewed phase-10 output as `agentMonitoringWorkbookResourceId` in the
selected configuration to retain its navigation tile during dashboard-only
refresh. The reference must be in the selected subscription/common RG.
Without that configuration the tile is omitted, not the existing workbook.

The workbook queries `AppEvents`, event `aifactory.agent.observation`. Its
sections show collection coverage, usage/tokens, quality/reliability, modeled
and quality-qualified benefit, separately grouped actual/amortized/estimated
cost, and recorded security evidence.
The native source is Logs/Application Insights; imported cost observations
retain their Cost Management source. Currency and cost basis are never
combined silently.

| Contract | Role |
|---|---|
| `aifactory.monitoring-observations.v1` | Shared flat observation input accepted by the canonical backend and native importer |
| `aifactory.agent-observations/v1` | Native observation/event input; scope includes AI Factory, scaleset, project, environment and agent |
| `aifactory.agent-observations/v2` | Lossless canonical-wrapper evidence for all six report families, including original per-field provenance and finance evidence objects |
| `aifactory.native-monitoring-report/v1` | Native report output, including `inputSchema` and imported-observation provenance |
| `aifactory.native-monitoring-report/v2` | Explicit native projection of v2 evidence with shared classification/qualification metadata and unavailable unsupported financial calculations |
| `aifactory.monitoring-report.v1` | Desktop/API canonical report envelope; not the native report output |
| `aifactory.aggregate-report.v1` | Existing monitoring execution bridge; additive `dataSource` and `lineage` preserve compatibility |

The legacy native bridge maps flat `factory` to `scope.aiFactory` and `agent_id` to
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
**`--events` only prepares event payloads; it does not ingest them.** The optional
agent-monitoring workbook was not deployed or rendered against newly published
business-value telemetry. This is separate from the deployed My Project
Usage/Cost/Model Tokens workbooks described above.

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

### Native v2 and the shared six-report evidence

Use v2 for the complete canonical evidence interchange; v1 remains accepted
with its existing formulas and behavior. Ship `native_monitoring_v2.py`
alongside `native_monitoring.py`, and `agentMonitoringCanonical.kql` alongside
the workbook's existing query assets.

```powershell
python -I -B .\native_monitoring.py `
  --input .\samples\monitoring-observations.canonical-reviewed.sample.json `
  --source sample --native-version 2 `
  --aiFactory "Demo AI Factory" --scaleset demo-east --project 001 --environment dev
```

The reviewed sample is separately pinned with original and LF-normalized
SHA-256 metadata. Its fixed historical timestamps do not become fresh live
observations when the command runs. For numeric comparisons with generated
canonical samples, select the same concrete placement and **one sample day**.

V2 preserves input/output tokens, requests, request success, evaluation counts,
latency sum/sample count, outcomes, cost, security, per-field source evidence
and optional financial evidence without flattening unknown into zero.
`value_class` uses the shared `observed | modeled | unavailable` vocabulary;
native `value_tier` is a separate detail. All visible rows must qualify before
strict qualified totals are shown. Legacy v1 retains its documented behavior.

**Intentional native boundary:** `realized_benefit_amount`, `value_evidence`
and `cost_evidence` round-trip, but native verified monetary benefit, net value,
ROI and cost per accepted outcome remain unavailable. The native workbook
does not independently reproduce the canonical financial-evidence validator.
Use the canonical CLI/API for those calculations; do not turn a supplied
amount into "verified realization" merely because it exists in an event.

V2 preserves canonical input numbers up to the canonical bound, while native
projections withhold values outside the exact interoperable absolute range
`2^53 - 1`. Range and unsupported-evidence reasons are visible. Local event-file
fidelity does not establish Azure ingestion-size compatibility, retention,
KQL execution or Portal rendering. No new observations were ingested as part
of this local implementation.

## 3. MAUI Monitoring

MAUI is a visual consumer of the canonical Tkinter backend, not a second
calculation engine. Its existing Monitoring surfaces are retained:

| View | What it shows | Evidence boundary |
|---|---|---|
| Monitoring hub | Four delivery groups, canonical report/template shortcuts, source prerequisites and native-navigation readiness | Catalog metadata only; does not deploy, collect or start jobs |
| Overview | Monitoring summary and navigation | Source-specific operational context |
| Current AI Factory | Factory analytics; sample sections include capacity, model lifecycle, project inventory, agent/ML health | Configuration, cached/discovered evidence or explicitly labeled samples |
| Models & quota | Model quota/allocation, token popularity and quota risk | Model/region/pool scope; quota is not actual billed consumption |
| ML | Model and agent monitoring across Dev/Stage/Prod | Subject/environment-specific monitoring, not automatic business-value realization |
| Automation reports | Existing Foundry tokens, showback and deployment-usage workflow | Reviewed legacy execution; a leaking aggregate is blocked rather than relabeled |
| Value & insights | New canonical value, cost, usage, quality and security reports, plus native-source catalog | Same filtered canonical observations and metrics used by API/CLI |
| My Project | Retail, Booking and Support usage/outcomes plus separate Cost | One concrete placement with its own date, store, time-zone and evidence rules |

**Monitoring hub / Value & insights** provide the shared AI Factory / Scaleset / Project / Environment
selectors, default All, and all six canonical report types listed below. The
client rejects an unexpected returned scope or out-of-scope rows before showing
metrics, charts, tables or exporting the report. Changing scope, source or
identity invalidates stale work.

Native project labels are keyboard-accessible controls with Cost analysis
tooltips. Links must be HTTPS Azure Portal destinations whose decoded scope
matches the validated observation metadata. Sample links are disabled.
Report/chart source text and calculated-metric formula/input/upstream lineage
remain visible.

The hub consumes the backend's navigation index rather than maintaining a
competing resource registry. It opens existing local views or reviewed
automation setup; it never starts a report run merely because a card is opened.
Native actions resolve the exact supplied navigation identity, including
separate project contexts for a shared physical workbook. Documentation links
remain separate from live-resource actions.

My Project accepts shared-scope transfer only when all four dimensions identify
a placement in its own catalog. Legacy operations and automation retain their
own clearly labeled scope. The shared Tk-specific **capacity issues**,
**lifecycle/services** and **agent inventory** workspaces are explicitly
unsupported in MAUI's shared catalog; MAUI does not silently substitute its
different allocation, model-lifecycle or ML-metric panels. Those MAUI panels
remain available through their separately labeled routes.

Live unified reporting uses an explicitly selected
`aifactory.monitoring-observations.v1` JSON input, with an 8 MiB / 10,000-row
limit. The client does not authenticate a new collector or query Azure
implicitly. Source claims in imported evidence are not independently attested
by the UI. A native nested event/report document is not directly interchangeable
with the flat observation input.

### MAUI / Tkinter differences

| Capability | MAUI | Tkinter |
|---|---|---|
| Unified six-report calculation | Canonical API consumer | Canonical Python implementation used directly by the UI |
| Common entry | Monitoring hub | Monitoring hub, first Dashboards entry |
| Combined overview | Six backend-owned sections in the hub, with detailed-report drill-down | Combined summary tab followed by the four existing delivery groups |
| Consistent All-default canonical filtering | Factory / Scaleset / Project / Environment and optional UTC dates shared by summary and insights | Factory / Scaleset / Project / Environment and optional UTC dates shared by summary and reports |
| Existing operational layout | Current AI Factory, Models & quota, ML and other Monitor tabs | Separate Capacity, Lifecycle, Models & Quota and Agents tabs |
| Existing automation workflow | Dedicated legacy Automation reports surface | Canonical and existing report choices in the same Automation reports area |
| Sample data | Explicit dummy/sample mode; unified samples come from canonical API | Explicit isolated in-memory demo/sample mode |
| Live evidence | Explicit flat-observation JSON import, submitted to canonical API | Explicit observation/report import and existing reviewed collectors |
| Source details | Source/provenance panels and native catalog | Sources & provenance subtab and report details |
| Filtered export | Canonical JSON copied through the UI | JSON/CSV actions; CLI/API also export |
| Preflight capacity, lifecycle/services, agent inventory | Shared actions explicitly unsupported; distinct MAUI operational panels remain | Dedicated existing operational workspaces |
| My Project | Typed API consumer; concrete compatible scope transfer | Direct canonical Python rendering; concrete placement |
| Native nested observation input | Export canonical flat observations before import | Use purple's v2 canonical/native bridge; never relabel nested events as flat API requests |
| Native resource actions | Exact context/identity and permitted URL checks; no sample links | Same backend metadata-binding model; no sample links |
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
| Monitoring hub | Four delivery groups, six report shortcuts, My Project templates, existing operations and scoped native navigation | Shared capability catalog; explicitly supplied resource bindings are not cloud discovery |
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
  --demo --maximized --view automation-reports --report showback `
  --factory-scope "Demo AI Factory" --scaleset demo-east `
  --project 001 --environment dev
```

`--demo` is explicit and non-persistent. The native **Sources & provenance**
subtab explains the collection boundaries; report details and filtered JSON/CSV
retain metric inputs and upstream references.

The default launcher view is **Monitoring hub**. Use `--view hub --section`
with `azure-native`, `factory-native`, `on-demand` or `custom` to open one
delivery group. `--days 1`, `7` or `30` controls the sample observation window;
it is not an implicit date filter on imported live evidence. The same compound
sample placement identities are reused by the hub, canonical reports and
My Project. Legacy operational samples intentionally describe a narrower
scenario and disclose that scope; they are not tenant-wide totals.

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

The catalog now adds `navigation_contract: "aifactory.monitoring-navigation.v1"`,
`navigation_groups` and `navigation_entries`, retaining existing `reports`,
`native_dashboards` and `native_sources`. Its four group IDs are `azure-native`,
`factory-native`, `on-demand` and `custom`. Each entry describes availability,
supported data modes, scope dimensions/limitations, prerequisites, source and
an allowlisted navigation action. A navigation action never executes an
arbitrary command or starts a cloud report job.

An optional `native_bindings` array supplies actual ARM resource IDs, concrete
factory/scaleset/project/environment, configured/observed metadata and optional
tenant/subscription IDs. The backend checks type/scope consistency and
constructs the permitted Azure Portal URL; caller-supplied URLs are not accepted.
`metadata_validated` means **metadata validation only**, not proof of resource
existence, deployment, permissions or telemetry. Resolve the exact returned
`navigation_id`, not the first item with the same resource type. Multiple
logical scopes can deliberately share one physical workbook. Sample and
unbound entries never become actionable live resources.

Imports accept **8 MiB (8,388,608 bytes)** and at most **10,000 observations**;
the canonical API permits at most **100 native bindings**. Live imports reject
explicit sample markers. `source: "sample"` generates isolated fixtures rather
than accepting caller rows. `POST /monitoring/export` returns filtered **CSV
text** using the same request as `/report`; there is no invented JSON export
wrapper or `format` request property.

Metric values are numeric or null, not preformatted success-shaped strings.
Metric metadata includes `data_source`, `formula`, `inputs`, `upstream` and
status, plus additive `value_class`, `qualification`, `cost_basis`, `currency`
and `estimate_type`. `value_class` is `observed`, `modeled` or `unavailable`;
it does not override the report's sample/live mode. Chart `links` align with chart labels; row `native_link` records contain
the URL, tooltip, scope, source and access notice. Samples have no fake live
resource links.

The older `/api/v1/automation-reports` prepare/start/jobs/latest workflow remains
separate. Its singular `foundry-token` ID is preserved for compatibility;
the canonical report ID is `foundry-tokens`. Where a legacy result is projected,
`job.report.monitoring` carries the canonical representation. Do not substitute
the native importer output schema for either API response schema.

### Purple consumer CLI and SDK

The reusable CLI now calls the same authenticated report API instead of
implementing its own metric arithmetic:

```powershell
azurefactory monitoring catalog
azurefactory monitoring report --report agent-value --source sample --days 1 `
  --factory "Demo AI Factory" --scaleset demo-east --project 001 --environment dev
azurefactory monitoring export --report showback --source sample --days 7 `
  --factory "Demo AI Factory" --scaleset demo-east --project 001 --environment dev --format csv
```

Use an already running approved local API, with `AIFACTORY_API_URL` and
`AIFACTORY_API_KEY` supplied through the supported host configuration. The key
is sent as `X-API-Key`, not placed in a URL or committed configuration.
Generated CLI requests default to seven sample days; an API request omitting
`days` retains its existing 30-day default. Live CLI calls require an explicit
reviewed `--request` file with `source: live` and `rows`; they do not trigger
Azure collection.

SDK methods are `monitoring_catalog()`, `monitoring_report(request)` and
`monitoring_export(request)`. Runnable Python/PowerShell requests are under
`environment_setup\install_config_wizard\api-usage-examples`, including
`python\monitoring_report.py` and `monitoring\sample-report.json` /
`sample-export.json`. CLI JSON export returns the canonical report; CSV uses
the API's filtered export. Opening a report is distinct from a reviewed legacy
automation job.

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

### Implemented canonical evidence gates

The six-report backend now exposes additive strict metrics without changing
the meaning of older clients' fields:

| Metric | Required evidence and meaning |
|---|---|
| `hours_saved`, legacy `realized_value` | Existing supplied-input time/capacity calculation, now explicitly **modeled**; the historical field name does not make it realized money |
| Historical `net_value`, `roi_percent` | Compatibility modeled arithmetic; `cost_coverage` says matched or unverified. These are not the strict financial metrics below |
| `qualified_outcomes`, `qualified_hours_saved` | Explicit `outcome_quality_passed: true` and provenance references for completed outcomes, baseline minutes and assisted minutes across all visible rows |
| `verified_realized_value` | Explicit realized benefit amount plus complete approved value evidence, matching scope/agent/currency and a valid, nonoverlapping measurement period |
| `cost_per_accepted_outcome` | Positive qualified outcomes and complete, exactly matched actual-cost evidence |
| `verified_net_value`, `verified_roi_percent` | Verified benefit and complete matched cost; ROI additionally requires positive actual cost |

Qualification of a subset does not produce an apparently complete accepted
total. Missing/failed evidence remains unavailable with a reason; explicit
failed quality also suppresses modeled benefits. Qualified labor capacity is
still **modeled**, not cash realization.

Optional `realized_benefit_amount` is a finite nonnegative amount supplied by
the business, never inferred from a labor rate. `value_evidence` must include
`owner`, `baseline_reference`, timezone-aware `period_start`/`period_end`,
`valuation_method`, `evidence_reference`, `approval_reference`, `currency` and
`scope`. `cost_evidence` includes the same period/currency/scope, a `reference`,
and `coverage: complete | partial | unknown`. Only complete exact attribution
supports strict cost/return measures. Financial overlap checks are independent
of model; a project-total observation cannot be counted again through its
child-agent observations. Touching period endpoints are allowed.

These gates validate the consistency of **caller-supplied approved evidence**.
They do not independently audit finance records, sign an approval or attest
that a business claim is true. The report shows the references and qualification
state so owners can review them. Demonstration values remain fictional even
when they satisfy all sample evidence gates.

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

For Foundry client instrumentation, disabling message-content recording is not
by itself a complete privacy policy: Python `@trace_function` can record
arguments and return values independently. Allowlist aggregate metadata, avoid
decorating functions that carry business content, and review error text and
tool arguments/results before collection. See
[client tracing settings](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side#enable-content-recording).
The documented [sensitive-content routing change](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/traces-sensitive-content)
is scheduled for **30 September 2026**, after this review; do not assume that
future routing already protects current telemetry. Access controls are not a
substitute for avoiding unnecessary content collection.

Use explicit cost allocation evidence when consumption is shared. Keep
unattributed cost visible instead of distributing it silently. Version the
contract so existing clients and automation can evolve compatibly.

## Implementation sequence

### September 22 continuation: from navigation to a combined dashboard

`MAUI-preview` is a runnable, dated application build, not the source repository
or a deployment of the native Azure workbooks. Continue development in the MAUI,
Tkinter/backend and purple repositories; copying a preview does not update an
installed application, the orange consumer pin or an Azure resource.

The existing four-group hub and six reports are the foundation, not work to
recreate. This local continuation adds one combined, source-aware overview and
an explicit reporting window, with source-level fixes for the native rendering
defects found in the September 21 captures.

| Surface | Current native possibility / implementation direction | Boundary |
|---|---|---|
| Azure Cost Management | Resource/service/meter cost views, actual versus amortized cost, exports and budgets; retain links to the financial source | Foundry token-cost estimates are not billing amounts or full application cost |
| Azure Monitor and Application Insights | Platform metrics, logs, workbooks, operational traces, custom-event funnels and HEART task-success analysis | Outcomes require instrumentation; empty telemetry is not measured zero |
| Foundry | Model/agent token usage, requests, latency, run success, evaluations and estimated costs | Core portal GA does not make Monitoring or Operate Overview/Assets/Compliance GA; those experiences remain Preview |
| Purple Bicep | Repair My Project token-account binding and unavailable-series rendering; preserve the existing default-off shared agent workbook | A local fix still needs reviewed deployment and real Portal acceptance |
| Purple on-demand and CLI/API | Reuse existing evidence reducers and guarded API clients for the same combined overview and date-bounded reports | No implicit collector, authentication, job, ingestion, scheduler or upload |
| MAUI and Tkinter | Combined value, cost, usage, quality and security sections under one source/scope/window, with same-context report drill-down | Legacy operational panels and native Portal pages retain their declared filter capabilities |

This native baseline was rechecked on **22 September 2026** against
[Cost Analysis](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/quick-acm-cost-analysis),
[Foundry readiness](https://learn.microsoft.com/en-us/azure/foundry/concepts/general-availability),
[Foundry cost guidance](https://learn.microsoft.com/en-us/azure/foundry/concepts/manage-costs),
[agent monitoring](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard)
and [Application Insights usage](https://learn.microsoft.com/en-us/azure/azure-monitor/app/usage).
Foundry monitoring still needs the relevant connected telemetry and permissions.
Its estimates exclude negotiated discounts and provisioned throughput; the
aggregate agent estimate also excludes prompt and non-Foundry agents. Neither
run completion nor a model evaluation establishes finance-approved realization.

| Step | Implementation plan | Acceptance criterion |
|---|---|---|
| 1. Shared projection | Add a compact summary using the existing six canonical report calculations, not a new metric engine | Each section matches its detailed report for identical evidence, scope and dates; raw observations are not duplicated six times |
| 2. Explicit period | Optional paired inclusive UTC calendar dates, applied before aggregation | Invalid/undatable selections fail explicitly; omitted bounds retain legacy behavior; `days` stays a sample-generation setting |
| 3. Desktop experience | Surface the summary in both hubs, preserve source/qualification disclosures and same-context drill-down | Source/scope/date changes invalidate stale display/export; live evidence never falls back to samples |
| 4. Native correctness | Isolate account-parameter serialization and all-unavailable chart behavior | Exact resource-group/account guards remain; no synthetic zero history; cloud acceptance stays a separate rollout step |
| 5. Consumer integration | Exercise the purple SDK/CLI against the source API from Spider's directory | Consumer settings, copied templates and submodule pin remain unchanged |
| 6. Release | Package coordinated client/API sources and deploy reviewed native assets through their normal release flows | A dated preview and local compilation are not treated as proof of installation, deployment or production evidence |

The plan does not grant permissions to the denied Foundry inventory, enable
business-event coverage, or invent accepted outcomes. Those require source-owner
review and evidence. My Project retains its independent concrete placement,
local-time-zone, store and state-history rules.

#### Implemented summary and explicit-period contract

`POST /api/v1/monitoring/summary` returns
`aifactory.monitoring-summary.v1`. It prepares the source, compound scope and
window once, then reuses the six existing report calculations. `sections` carries
each report's `report_id`, `title`, `data_source`, exact `metrics`, `provenance`
and `warnings`. The envelope carries the shared source/scope/coverage,
native/navigation metadata and filtered `rows` **once**. Sections overlap:
do not add their costs, tokens or outcomes together. The summary introduces no
client-side monetary arithmetic or finance attestation.

```json
{
  "source": "sample",
  "days": 7,
  "filters": {
    "factory": "Demo AI Factory",
    "scaleset": "demo-east",
    "project": "001",
    "environment": "dev"
  },
  "start_date": "2026-09-09",
  "end_date": "2026-09-16"
}
```

The same optional `start_date` / `end_date` fields apply to detailed report and
CSV export requests. They mean **inclusive UTC calendar dates**, supplied
together, at most 90 days. Timestamped point observations are filtered in UTC.
For aggregate observations, the half-open `[period_start, period_end)` interval
takes precedence and must fit wholly within the requested window. A partial
overlap or unusable date in a selected scope is an explicit error, not a
prorated bill/benefit or a silently excluded unknown. Scope filtering happens
first. Omitting both bounds preserves legacy unbounded behavior and reports
the count of undated rows. `days` continues to control only sample generation.

The frozen sample clock is **2026-09-16T10:00:00Z**; seven sample days run from
September 9 at 10:00 UTC to September 16 at 10:00 UTC. The example's eight
inclusive calendar dates enclose those seven complete daily grains. Choosing
September 15 as the end would cut the final grain and is rejected. The response
separates requested dates, observed bounds, sample clock, and report-generation
time. Generation time is not evidence freshness.

```powershell
# Existing authenticated local API; no Azure collector or job.
azurefactory monitoring summary --source sample --days 7 `
  --factory "Demo AI Factory" --scaleset demo-east --project 001 --environment dev `
  --start-date 2026-09-09 --end-date 2026-09-16

# Direct canonical backend CLI, from its repository.
python -m src.monitoring_reports --summary --source sample --days 7 `
  --factory "Demo AI Factory" --scaleset demo-east --project 001 --environment dev `
  --start-date 2026-09-09 --end-date 2026-09-16
```

The SDK equivalent is `client.monitoring_summary(request)`; a summary request
has no `report_id`. The purple Python example supports
`monitoring_report.py --summary --request ..\monitoring\sample-summary.json`.
Summary exports are JSON; CSV remains a selected detailed-report export.
Both hosts clear stale output/export when evidence, source, scope or dates
change and preserve the selected dates when opening a detailed canonical report.

The native My Project source now gates its three daily business charts on
defined numeric values. All-unavailable series show an explanation instead of
feeding all-null columns to a time chart. Partial series retain null days and
reviewed/measured zeros remain zeros. These changes flow through the existing
Bicep and dashboard-only module; no new deployment parameters, automatic
diagnostics or ingestion are introduced.

The source API, purple SDK/CLI, date-filtered CSV and example were exercised
from Spider's directory. Its status, working diff and submodule entry remained
unchanged. This does not update Spider's copied templates or publish the purple
changes. Native deployment/Portal acceptance and normal installer release remain
separate. The September 20/21 presentation and copied OneDrive preview are
historical artifacts, not a build of this continuation.

The current MAUI source has also been exercised in a maximized Windows client
against the authenticated loopback source API: all six overview sections load,
editing dates clears stale export, and showback drill-down retains the same dates.
Returning to the hub reloads the overview. The standalone client output is
`ESAIF.ConfigWizard\artifacts\monitoring-summary-20260922\standalone-client`;
it contains its .NET/Windows App SDK runtimes but **not** an updated bundled API.
Use the updated Python source API and configure its matching endpoint/key; an
older installed API correctly reports the summary route as unsupported.

The normal coordinated installer remains a separate release step. At this
checkpoint the Python API packager's required
`build\creation-source\aifactory-source.json` is absent. Do not bypass that
provenance prerequisite or attach a stale `ApiHost` to claim a complete package.
The earlier `preview` directory from a no-build publish is not the accepted
runtime output; use the self-contained client above. No installed application,
consumer pin, diagnostic setting or deployed Azure workbook was replaced.

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

### September 20 implementation and rollout plan

| Workstream | Local implementation | Production or follow-on work |
|---|---|---|
| Shared experience | Four-group, 26-entry capability/navigation catalog; six unchanged report IDs; explicit scope/source/availability | Configure actual native resource bindings and review which source supports which filters |
| Business value | Modeled compatibility measures plus strict quality-qualified and evidence-backed realized-value measures in the canonical backend | Instrument accepted outcomes and obtain business/finance-approved baseline, valuation and cost-coverage evidence |
| Native evidence | V2 lossless interchange, usage/reliability KQL, default-off common-RG workbook and project navigation | Publish the reviewed module, deploy against an existing workspace, ingest approved metadata-only events, and verify real KQL/Portal behavior |
| Native monetary realization | Original finance evidence preserved; unsupported native financial calculations remain unavailable | Reuse the canonical financial validator before publishing a versioned, attributable derived-result event; add native display only with equivalent overlap/period/currency/coverage gates |
| Automation and CLI/API | Native offline reducer/wrapper, canonical API/CSV and purple SDK/CLI examples | Configure approved existing collectors/runbooks separately; catalog browsing must not dispatch jobs |
| Samples and operation | Shared placement identities, scoped popularity samples, aligned lifecycle thresholds and no live synthetic history fallback | Validate current source freshness and completeness before operational decisions |
| Consumer adoption | Updated source exercised from Spider's directory without overwriting its modified files or submodule pin | Publish/version the approved purple change, review the consumer template merge, then update its pin through the normal owner-controlled process |

For further automated realization, reuse My Project's outcome events but
validate successful transactions/resolutions against the business system of
record. Add explicit accepted-outcome and human-handoff observations, reviewed
baseline versions, and aggregate review/rework effort. Join an approved
financial export using the same compound scope and period; do not reinterpret
cart activity, token volume or an evaluator score as revenue.

For native finance parity, the next step is **validator reuse**, not another
approximate KQL ROI formula. A proposed derived-result contract should preserve
validator version, qualified scope/period/currency, input/evidence references,
cost coverage, publication identity and freshness. It must make stale,
partially attributed or unvalidated results unavailable. This is follow-on
design, not an implemented ingestion service or an attestation mechanism.

No local source update changes an already distributed desktop installer or an
already deployed workbook. Build/package from the reviewed source and use the
normal release flow. Keep the source API and MAUI's packaged API host aligned;
a matching API version string alone does not prove matching report behavior.

## Earlier native capture observations

The earlier recorded read-only Spider capture pass opened the existing shared factory dashboard,
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

## Earlier delivery and capture boundaries

The six canonical report families now have shared scope-first filtering,
All-default organizational selectors, explicit missing-data handling, retained
source/formula/input provenance and filtered exports. MAUI uses compact metric
cards with expandable lineage rather than allowing long source details to push
the overview below the fold. Both clients retain readable compound project
identities on their charts.

Real project chart labels and keyboard-accessible links use the documented
Cost analysis route. The capture pass also imported one manually recorded
Project 001 billing observation into each client, preserving its actual currency,
period and source reference without publishing customer billing amounts here.
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

**Not performed in the initial desktop/screenshot pass:** Azure deployment,
telemetry ingestion, schedule creation, permission changes or live rendering of
the optional agent-monitoring workbook. The later approved My Project
dashboard-only deployment is documented above. The agent workbook's grid uses the
verified text-link renderer and a visible tooltip-description column; a
custom workbook hover renderer is not claimed. Existing native portal
dashboards remain deployment-specific and do not inherit the desktop filters.
Production value realization still needs approved instrumentation, allocation,
baseline and outcome evidence.

The earlier delivery contains **89 full-resolution screenshots** (8 Azure-native,
56 MAUI and 25 Tkinter) and the **98-slide**
`AI-Factory-Monitoring-FinOps-Value.pptx`, with a `capture-index.json` describing
each view, mode, scope and source. The requested output folder uses the name
`screebshots`. Office applied a sensitivity label to the final PowerPoint;
that protection was preserved. Open it with an authorized Office account and
review the audience before sharing.

## September 20 local delivery

This refresh preserves the earlier presentation and captures. Its new artifacts
in the requested `monitoring-finops` folder are:

| Artifact | Contents |
|---|---|
| `AI-Factory-Monitoring-FinOps-20260920.pptx` | 206-slide reference atlas: capability/architecture summary, every new full-window capture, enlarged details, filters, sources and citations |
| `screebshots\20260920-refresh` | 147 actual maximized 3840 x 2076 captures: 48 MAUI and 99 Tkinter |
| `screebshots\20260920-refresh\details` | 48 exact crops from those retained full images, not redrawn dashboards |
| `capture-index-20260920.json` | Per-view mode, scope, sources, full-image/detail paths and capture notes |

The standard MAUI canonical captures use **30 sample days**; Tkinter's main
canonical sweep uses **7 sample days**, with explicit scoped/one-day examples.
My Project captures use their displayed local-date/store/time-zone selections
(MAUI Europe/Berlin; Tkinter UTC). Compare totals only after aligning scope,
period and time zone. Shared formulas do not make different selected windows
numerically identical.

The local MAUI preview is under
`<MAUI-repository>\artifacts\monitoring-hub-20260920\preview`. It includes the
updated `ApiHost\aifactory-api.exe`. Run `Start-MonitoringSample.ps1` there for
an isolated sample session: the launcher starts its own authenticated loopback
API, opens Monitoring hub and stops its API when that app exits. Keep its
PowerShell session open while using the preview. It does not overwrite stored
API connection settings or require the temporary capture server. Normal
executable launch continues to honor the application's connection settings.

The updated source/API and packaged host were exercised locally, including
all six report families, full All-scope responses, scoped exports and the
purple consumer examples run from Spider. Spider's existing modified files
and submodule pin were retained; no normal consumer release was silently
replaced.

**September 20 live boundary (superseded by the September 21 capture below):**
no new Azure Portal screenshots were captured in that refresh.
The initial attempt required interactive sign-in; a later browser check showed
a different tenant, which was not captured or changed. At that point a confirmed
Spider portal session was still required. Native catalog cards in the apps are not
substituted for live Azure views. This refresh did not deploy the
optional agent workbook, ingest telemetry, start cloud report jobs, change
permissions or create schedules. Native verified-finance calculations remain
unavailable as documented; the canonical custom reports support the explicit
financial-evidence gates.

## September 21 native evidence supplement

The user completed interactive sign-in, and the Spider account and tenant were
confirmed before accessing resources. This pass captured **actual native Azure
and Foundry pages**, not the desktop capability catalog. The browser was full
screen; the retained PNG viewport is **2195 x 1235 CSS pixels**. The earlier
MAUI/Tkinter screenshots, presentations, consumer settings and submodule pin
were preserved.

| Artifact in the requested `monitoring-finops` folder | Contents |
|---|---|
| `AI-Factory-Monitoring-FinOps-Native-20260921.pptx` | 40-slide native supplement: interpretation, all 27 captures, seven enlarged details, filters, sources and limitations |
| `screebshots\20260921-native` | 27 native browser captures, including explicit unavailable/access-error states |
| `screebshots\20260921-native\details` | Seven exact image crops; full originals retained |
| `capture-index-native-20260921.json` | Per-image scope, source, capture time, dimensions, hashes and interpretation boundaries |

Use this supplement together with the **206-slide September 20 local atlas**.
It does not replace or relabel the sample MAUI/Tkinter views as live telemetry.
Live screenshots include tenant/resource identifiers and billing information;
review the audience and apply an appropriate sensitivity label before sharing.
The public guide intentionally does not reproduce those identifiers or amounts.

### What actually opened, and what it establishes

| Native surface | September 21 observation | Interpretation |
|---|---|---|
| Shared factory dashboard | Connectivity/common cost tiles loaded; stage/prod resource tiles reported invalid resource IDs | Working cost tiles do not prove every environment is deployed |
| Project 001 DEV dashboard | Opened successfully, including My Project and model-token links | Supersedes the earlier observation that this project-dashboard destination was absent |
| My Project Usage | Retail, Booking and Support rendered; coverage declarations remained false/unreviewed and business cards unavailable | No completeness, accepted outcomes or business realization was asserted |
| My Project empty charts | Some all-unavailable daily charts displayed `Could not find appropriate columns for Time chart` | A visible native-rendering limitation, not a valid zero-valued history |
| My Project Cost | Separate actual/allocated/estimated rows had no coverage; no observed currency was available for the charts | App-meter evidence is independent of the working resource-group billing view |
| My Project Model tokens | A discovered account name was displayed, but account validation returned no valid scoped account and empty account ID | Unresolved deployed-workbook binding/validation issue; it is not evidence of no token consumption |
| Azure Cost Analysis | Actual and amortized views both loaded with the project RG, month and currency visible; forecast remained separate | Billing-derived, open-period cost; neither basis should be added to the other or to forecast |
| Azure Monitor account metrics | The 24-hour window had no displayed token value; seven days showed measured inference-token activity | Window selection matters; native platform metrics do not depend on business-event coverage |
| Application Insights | Operational overview loaded; Agents Preview displayed its setup/no-recent-activity state | Neither zero request counts nor missing agent data establishes complete health coverage |
| Foundry model Monitor | Deployment requests, input/output tokens, latency and estimated cost loaded for the seven-day window | Technical model activity and a native estimate, not full workload cost or business ROI |
| Azure Monitor Dashboards with Grafana | The built-in AI Foundry view opened from Foundry's own link with the actual subscription/RG/account and period | Native usage/cost-estimate/reliability panels without creating a Grafana resource or saving a dashboard |
| Foundry Operate | Overview displayed no agent totals; Assets returned HTTP 403 | A missing or denied source is not an empty healthy inventory; no alternate access path was used for that inventory |
| Foundry Compliance | Policy list and recommendation panel were empty; the model guardrail configuration matrix loaded | Configured controls, absent recommendations and effective protection are different evidence types |

Native controls were used only for unsaved view selection, time/basis changes
and scrolling. The workbook's coverage declarations and scope guards were not
relaxed. Model Monitor's visible cost-processing warning was preserved.
Grafana/Foundry estimates were not substituted for Cost Management amounts,
and model-token totals were not substituted for business outcomes.

The exact Foundry model-monitor route was reached through the live portal's
navigation. This confirms that destination for this observed deployment; it
does **not** establish a durable, generic Foundry deep-link contract for the
desktop catalog or every tenant.

### Follow-on work exposed by live rendering

1. Reproduce the deployed token-workbook account selection against its saved
   parameter values, discovered ARM IDs and inventory. Correct the binding or
   serialization mismatch only after isolating it; retain exact-RG validation
   and fail-closed behavior. Acceptance requires real input/output metric
   series and independently scoped request logs, not simply successful Bicep
   compilation or a populated account label.
2. Make all-unavailable business-series rendering explicit without turning
   missing values into zeros. Verify the native empty and partial states in
   Portal as well as the KQL output schema.
3. Have the source owner review denied agent-inventory access and telemetry
   prerequisites. Do not reinterpret HTTP 403, no policies, no recommendations
   or no recent agent data as a healthy score.
4. Instrument accepted outcomes, review/rework effort and comparable baselines;
   supply approved valuation and matched cost evidence before claiming realized
   benefit. Native model requests and guardrail settings cannot provide that
   business evidence automatically.

**Not performed:** cloud deployment, saved Azure edits, diagnostic settings,
RBAC changes, telemetry ingestion, inference, evaluations, report jobs or
schedules. The optional agent-evidence workbook and standalone generated
Application Insights dashboard were not verified in this pass. On-demand cloud
execution was deliberately not started. Those surfaces retain their existing
deployment/execution prerequisites; these screenshots do not imply otherwise.
