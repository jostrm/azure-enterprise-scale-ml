# AI Factory monitoring: value, cost and trust

Use one monitoring story across four delivery layers: **Azure built-ins**,
**AI Factory native assets**, **MAUI Monitoring**, and **Tkinter Dashboards /
CLI / API**. These layers complement each other; a desktop chart is not a
replacement for the native billing or telemetry source.

This guide covers the reusable **purple** module, the **orange** consumer
repository, and the two desktop clients. Native capability/source review:
**17 September 2026**; My Project and Cost extension: **18 September 2026**.
Local artifacts and sample captures are not evidence
that a resource has been deployed in Azure.

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
Review the assertions again after changing scope, store or dates. Coverage is
not inferred from the existence or absence of rows, and query/permission
failures do not become healthy zeros.

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

**Validation boundary:** the source and isolated Spider copy were compiled and
their serialized workbook/query structure checked locally. Usage, Cost and
request-log token KQL were also executed read-only against an existing workspace,
including array-valued input/output/cache counters. Missing business events
remain unavailable. The new workbook still requires an approved deployment and
Portal rendering check; successful KQL alone is not proof of the complete UI.

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
| [`monitoring/agentMonitoringWorkbook.bicep`](../../../environment_setup/aifactory/bicep/modules/monitoring/agentMonitoringWorkbook.bicep) | New opt-in value, cost and security workbook over evidence-backed observations | Existing workspace; five All-default scope selectors plus time; no collection, ingestion or RBAC deployment |
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
