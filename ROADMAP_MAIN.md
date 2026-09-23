# AI Factory - Main Branch and Roadmap

### Implemented progress. Focused next steps. No implied delivery commitments.

**[v1.25 release notes](RELEASE_125.md)** &nbsp; / &nbsp; **[Main-only change](#2-what-is-genuinely-main-only)** &nbsp; / &nbsp; **[Roadmap candidates](#4-unscheduled-roadmap-candidates-and-acceptance-gates)** &nbsp; / &nbsp; **[Workshop sequencing](#5-proposed-workshop-sequencing-october-2026-march-2027)**

**Evidence snapshot:** 23 September 2026.  
**Baseline requested:** [RELEASE_124.md](RELEASE_124.md), including v1.24.1.  
**Published main reviewed:** [`76727432ba47e8e9b8fcf314f0eada0066b7e6c7`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/76727432ba47e8e9b8fcf314f0eada0066b7e6c7).  
**v1.25 comparison point:** [`1bd9020e009036427763a0f66b2b2449ca38f288`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/1bd9020e009036427763a0f66b2b2449ca38f288).

This document compares the supplied v1.24 notes with published `main` and also isolates what is newer than the accompanying [v1.25 notes](RELEASE_125.md). It does not turn already implemented features into future promises. The original `RELEASE_124.md` is unchanged.

## Read the status correctly

| Status | Meaning |
|---|---|
| Baseline | Already described in v1.24/v1.24.1 |
| In v1.25 source | Present in the exact reviewed `release/v1.25` branch; not automatically deployed in a customer tenant |
| Main-only | Committed beyond that release in published `main` |
| Candidate / gap | Proposed or incomplete work; no committed delivery date or owner |

Published `main` is **exactly one commit ahead** of the requested release branch, with **zero release-only commits**. Most of the cumulative progress since v1.24 therefore belongs in v1.25, not in a future-release column.

> [!IMPORTANT]
> **Already implemented is not the same as adopted.** The roadmap separates source capabilities, the one verified main-only change and proposals that still need owners and acceptance criteria.

---

## 1. Cumulative main progress versus the v1.24 notes

| Area | v1.24/v1.24.1 baseline | Added or extended in v1.25, also present on main | Documentation |
|---|---|---|---|
| Configuration and delivery | Wizard, YAML/environment variables, preflight and ADO/GHA pipelines | JSON-first config, identity routing and coordinated feature refresh | [JSON configuration][json], [update AI Factory][update] |
| Setup and access | Common/project infrastructure and private networking | End-to-end bootstrap, private-access hub, VPN/DNS and cross-tenant ADO bootstrap | [Set up AI Factory][setup] |
| Lifecycle and UX | Existing factory configuration | Registered/legacy layouts, reviewed enrollment, receipts, MAUI installer, CLI/SDK/API | [CLI/API][cli-overview], [operator reference][cli], [MAUI][maui] |
| Agent use cases | Foundry/private-agent infrastructure | Agent Factory runtimes, multi-agent patterns, source-bound RAG and narrow private MCP | [Agent code][agents], [RAG][rag], [MCP][mcp] |
| ML and data | Existing lake and ML infrastructure | Model Factory, versioned inputs, Delta/ESML v2, shareback and model-selection gates | [Model code][models], [DataOps][dataops], [MLOps][mlops] |
| Storage selection | Existing common/project storage infrastructure | Shared explicit `use_common_datalake_storage` contract across agent/ML examples | [Agent storage][agents], [ML storage][models] |
| Operations and FinOps | Token reports, showback, throttling and dashboards | Native usage/token workbooks, monitoring and plan-first dashboard-only refresh | [Main dashboard guide][dashboards] |
| Gateway | BYO APIM connectivity | Weighted pools, token controls, retry/circuit-breaker policies and optional Kong edge | [APIM pools][apim], [Kong edge][kong] |
| Private-platform reliability | Capability hosts and private Search connectivity | Search-region capacity override, existing-host reconciliation and shared-link repairs | [Setup][setup], [update][update] |

Detailed scope, representative commits and migration caveats are in [RELEASE_125.md](RELEASE_125.md). Existing persona groups, CMEK, MI-only setup, per-environment SKUs and baseline FinOps are not new announcements.

## 2. What is genuinely main-only?

### Native workbook defaults and resource-group cost charts

Commit [`76727432`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/76727432ba47e8e9b8fcf314f0eada0066b7e6c7), dated **20 September 2026**, is the entire published-main delta beyond the requested release.

- Workbook coverage dropdown defaults use lowercase `false`/`true`, matching the expected parameter values.
- A sole Foundry/OpenAI account in the exact project resource group is selected automatically; multiple accounts still require an explicit choice.
- The project dashboard restores the native Azure `CostAnalysisPinPart` scoped to the **exact resource group**, with accumulated **ActualCost**, **ThisMonth** and the native Azure forecast KPI.
- Native Cost Analysis links remain visible in workbook views.
- Token-cost estimates remain distinct from billed Azure cost; no fabricated linear forecast or double-counting with token estimates is implied.

The commit changes four files: the [dashboard guide][dashboards], `myProjectWorkbook.bicep`, `projectDash01.bicep` and `test_my_project_workbook.py` (179 insertions, 37 deletions). Its guide records a limited consumer rollout and saved-workbook KQL checks; interactive Portal rendering was still pending in that recorded evidence.

**Adoption implication:** review the dashboard-only plan and refresh the approved scope rather than assume a full infrastructure redeployment is required. Confirm actual rendering, account selection, evidence sources and cost scope in the target environment.

## 3. Reconcile the old v1.24 roadmap

| Old roadmap item | Current assessment | Remaining work / decision |
|---|---|---|
| GitHub Actions parity | Substantial configuration and pipeline alignment exists | Resolve documented registered-runtime provider and atomic-dispatch gaps |
| Enhanced dashboards | Delivered assets in v1.25 plus the main-only native cost/default fix | Complete representative Portal and tenant adoption checks; supply application instrumentation |
| Persona re-enablement | Entra groups/personas were already described in the v1.24.1 patch | Specify any additional persona behavior before treating it as a new feature |
| Email integration | Report generation exists; authenticated report-email delivery is not implemented | Select identity, delivery channel, distribution controls and attachment policy |
| Enhanced security | Scoped identity, private networking and read-only MCP improvements are concrete | Validate each deployment's permissions and controls; no blanket compliance guarantee |

The [showback runbook][showback] explicitly excludes email; the [notification script][email-script] simulates sending. Report-dispatch Logic Apps and email alerts are not the same as emailing generated cross-charge reports.

## 4. Unscheduled roadmap candidates and acceptance gates

These are evidence-based gaps or workshop proposals, **not release commitments**.

| Candidate | Evidence / rationale | Suggested acceptance gate |
|---|---|---|
| Authenticated report delivery | Showback email remains out of scope; simulated notification implementation | Reviewed recipients and sensitivity policy; real authenticated delivery with failure handling |
| Registered-operation consistency | CLI/API documents common-only, GHA atomic-dispatch and shared-remote blockers | Supported operation/provider matrix; immutable reviewed configuration and correct scoped receipts |
| Production adoption of native monitoring | Portal rendering and instrumentation remain environment-dependent | Real project/account scope; explicit unavailable-data states; traceable usage versus billed-cost evidence |
| Broader ML scenario coverage | AutoML vision evaluation/promotion and packaged Databricks vision remain incomplete | Repeatable held-out evaluation and approved promotion path for each added engine/scenario |
| Distribution hardening | MAUI is unsigned preview; public SDK package publication is not established | Approved installation/update channel, signatures and compatibility matrix |
| Existing-factory UX and guidance | Tutorial labels the unified Simple Mode engine, guidance and clone-retargeting scenes as proposed/blocked | Demonstrated existing-factory create/update flow with review, clear blockers and deployable target configuration |

Sources: [CLI operational contract][cli], [tutorial manuscript][tutorial], [MLOps][mlops], [MAUI distribution][maui], [main dashboard guide][dashboards].

## 5. Proposed workshop sequencing: October 2026-March 2027

The following is a **discussion framework**, not an approved engineering schedule. Owners, dates and acceptance criteria must be agreed separately.

| Proposed horizon | Focus | Decision/output |
|---|---|---|
| Stabilize first | Pin the adopted release; reconcile effective JSON/version defaults; assess regional capacity and the main-only dashboard fix | Approved baseline, representative upgrade/rollback exercise and operational evidence |
| Adopt selectively | Choose useful agent/ML examples, private tool scope, monitoring and gateway patterns | Small workload pilots with owners, identity/network boundaries and measurable results |
| Close agreed gaps | Report delivery, registered-provider consistency, customer subscription-vending handoff and operator UX | Prioritized backlog with explicit dependencies and acceptance gates |

Subscription vending is an integration discussion, not a completed customer-specific handoff proven by this repository audit. Capacity options do not reserve capacity. Gateway policies do not remove SKU/network limitations. A model-selection win does not constitute production deployment approval.

## 6. Version and source hygiene

**Explicit version selection matters:** the reviewed release still contains legacy create default `124`, configuration minor version `24` and some older Bicep fallbacks. Use an approved target and the effective configuration, not a blanket assumption that all defaults are 1.25. ESML v2 is a new API; storage switches do not move data or grant RBAC.

**Published main versus this local checkout:** at the snapshot, local `main` is `d44105e1`, three commits ahead and seven behind `origin/main`. Its local-only commits are `f82fcef3` (runner/enrollment/monitoring), `0a4a5bb1` (storage selection) and `d44105e1` (project dashboards). Related topics also appear under different upstream commits; neither local subjects nor dirty files are evidence of additional published features.

The working tree has extensive existing modifications. They are excluded from these notes. The separate branch `release/v.1.25` is also excluded. No branch checkout, merge, reset or publication is part of this documentation task.

To reproduce the exact published comparison:

```powershell
git rev-list --left-right --count 1bd9020e009036427763a0f66b2b2449ca38f288...76727432ba47e8e9b8fcf314f0eada0066b7e6c7
git log --format=fuller 1bd9020e009036427763a0f66b2b2449ca38f288..76727432ba47e8e9b8fcf314f0eada0066b7e6c7
git diff --stat 1bd9020e009036427763a0f66b2b2449ca38f288 76727432ba47e8e9b8fcf314f0eada0066b7e6c7
```

[setup]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/documentation/v2/20-29/24-end-2-end-setup.md
[update]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/documentation/v2/20-29/26-update-AIFactory.md
[json]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/environment_setup/aifactory/bicep/copy_to_local_settings/pipeline-config/readme.md
[cli-overview]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/documentation/v2/10-19/17-cli-and-api-and-usage.md
[cli]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/environment_setup/azurefactory-cli/readme.md
[maui]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/environment_setup/install_config_wizard/maui/readme.md
[agents]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/usecase_code/40-agent-factory/readme.md
[rag]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/usecase_code/40-agent-factory/45-rag-agent/readme.md
[mcp]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/usecase_code/40-agent-factory/44-azure-mcp/readme.md
[models]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/usecase_code/50-ml-model-factory/readme.md
[dataops]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/documentation/v2/30-39/36-dataops.md
[mlops]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/documentation/v2/30-39/37-mlops.md
[dashboards]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/76727432ba47e8e9b8fcf314f0eada0066b7e6c7/documentation/v2/30-39/32-dashboards.md
[apim]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/README.md
[kong]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/environment_setup/aigateway/kong/readme.md
[tutorial]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/documentation/v2/20-29/28-tutorial-walkthrough.md
[showback]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/RUNBOOK.md
[email-script]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/1bd9020e009036427763a0f66b2b2449ca38f288/environment_setup/aifactory/bicep/scripts/ado/124_send_email_notifications.sh
