# AI Factory - Main Branch and Roadmap

### Implemented progress. Focused next steps. No implied delivery commitments.

**[v1.25 release notes](RELEASE_125.md)** &nbsp; / &nbsp; **[Main-only change](#2-what-is-genuinely-main-only)** &nbsp; / &nbsp; **[Roadmap candidates](#4-unscheduled-roadmap-candidates-and-acceptance-gates)** &nbsp; / &nbsp; **[Workshop sequencing](#5-proposed-workshop-sequencing-october-2026-march-2027)**

**Evidence snapshot:** 30 September 2026; cumulative v1.25 assessment retained from 23 September.  
**Baseline requested:** [RELEASE_124.md](RELEASE_124.md), including v1.24.1.  
**Published main reviewed:** [`7b8605c2d97017ecce84043f5047e43c69add152`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/7b8605c2d97017ecce84043f5047e43c69add152).  
**v1.25 comparison point:** [`1bd9020e009036427763a0f66b2b2449ca38f288`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/1bd9020e009036427763a0f66b2b2449ca38f288).

This document compares the supplied v1.24 notes with published `main` and also isolates what is newer than the accompanying [v1.25 notes](RELEASE_125.md). It does not turn already implemented features into future promises. The original `RELEASE_124.md` is unchanged.

## Read the status correctly

| Status | Meaning |
|---|---|
| Baseline | Already described in v1.24/v1.24.1 |
| In v1.25 source | Present in the exact reviewed `release/v1.25` branch; not automatically deployed in a customer tenant |
| Main-only | Committed beyond that release in published `main` |
| Candidate / gap | Proposed or incomplete work; no committed delivery date or owner |

Published `main` is **30 commits ahead** of the requested release branch, with **zero release-only commits**. The exact `release/v1.25` branch remains at the commit documented in [RELEASE_125.md](RELEASE_125.md). Since the previous main snapshot, **29 additional commits** have landed; they are not part of that v1.25 snapshot.

> [!IMPORTANT]
> **Already implemented is not the same as adopted.** The roadmap separates published source changes, installed/runtime adoption and proposals that still need owners and acceptance criteria. A published repair is not evidence that a workbook was refreshed or a deployment completed.

> **8 October 2026 follow-up:** the [post-v1.25 source addendum](RELEASE_125.md#post-v125-addendum--8-october-2026) covers Factory Agent Chat, Factory MCP, CLI/API execution boundaries, the shared dual graph, Azure Monitor health models and opt-in personas. It labels committed versus working-tree implementation and remaining integration/adoption gaps separately. The dated snapshot, commit counts and published-main comparisons below remain the 30 September assessment; the addendum does not retroactively add these features to v1.25.

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

### What "personas" means in the v1.24.1 summary

**Post-snapshot implementation:** the opt-in `groups-v1` nine-persona source model
now has separate group bootstrap, bound seeding records, declarative permissions
and common/project reconciliation. It is not a retroactive capability claim for
v1.24.1/v1.25 snapshots or installed desktop/API packages. See the
[current specification and adoption requirements](documentation/v2/20-29/25-personas-aifactory.md).
Live tenant authorization remains an operator validation requirement.

These are **team responsibilities and identity/access groupings**, not LLM personalities or system prompts. With `use_ad_groups: "true"`, configuration supplies Entra security-group ObjectIDs for project/core-team membership. Pipeline parameters pass this as `useAdGroups`; RBAC modules use `principalType: 'Group'` rather than `'User'`. The `personas_project_esml`, `personas_project_genai_1` and `personas_core_team` strings describe persona names; changing a label alone is not a new access policy.

The documented project groupings include team lead, data scientist and front-end roles for ESML, and the GenAI grouping adds Foundry, agentic and data-operations responsibilities. Effective permissions still depend on the actual resource assignments, scope and group membership. See the [persona specification][personas], [configuration parameters][persona-config] and [example RBAC module][persona-rbac].

## 2. What is genuinely main-only?

### Native workbook defaults and resource-group cost charts

Commit [`76727432`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/76727432ba47e8e9b8fcf314f0eada0066b7e6c7), dated **20 September 2026**, was the entire published-main delta at the previous snapshot. It remains part of the current comparison.

- Workbook coverage dropdown defaults use lowercase `false`/`true`, matching the expected parameter values.
- A sole Foundry/OpenAI account in the exact project resource group is selected automatically; multiple accounts still require an explicit choice.
- The project dashboard restores the native Azure `CostAnalysisPinPart` scoped to the **exact resource group**, with accumulated **ActualCost**, **ThisMonth** and the native Azure forecast KPI.
- Native Cost Analysis links remain visible in workbook views.
- Token-cost estimates remain distinct from billed Azure cost; no fabricated linear forecast or double-counting with token estimates is implied.

The commit changes four files: the [dashboard guide][dashboards], `myProjectWorkbook.bicep`, `projectDash01.bicep` and `test_my_project_workbook.py` (179 insertions, 37 deletions). Its guide records a limited consumer rollout and saved-workbook KQL checks; interactive Portal rendering was still pending in that recorded evidence.

**Adoption implication:** review the dashboard-only plan and refresh the approved scope rather than assume a full infrastructure redeployment is required. Confirm actual rendering, account selection, evidence sources and cost scope in the target environment.

### Additional published changes through 29 September

The following groups summarize the additional published commit history, not a claim that every affected live workflow has completed.

| Area | Published changes | Representative commits |
|---|---|---|
| Native monitoring | Project workbook/pipeline integration; subsequent token-account selection and scope normalization corrections | [`c241a6c9`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/c241a6c9e6df36824112864dd6147fdcfbe9eb3e), [`a7e3ab35`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/a7e3ab3538e9101d92f4ac21756e90a12a919273) |
| Provider lifecycle and CLI | Read-only GitHub workflow monitoring, repository/enrollment reviews, packaged lifecycle helpers and explicit single-writer workflow integration | [`a4c8b98d`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/a4c8b98d3fffb77ad98efd08e776a045cc6dd42e), [`3c1470d3`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/3c1470d37d28b9f7df3855d839db5f5eecc7da58), [`56259608`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/562596086556f8a9277234c12d4a8dbc374ead65) |
| Diagnostics and plan selection | Broader default diagnostics without changing resource reuse; Defender plan selection remains opt-in | [`622570e9`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/622570e96f9dceadf8e65ad160c2efcba8d2fc51), [`5175a628`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/5175a628eb62316c2db1d0801f3d0a727fd200b0) |
| Bootstrap evidence and identity | Durable prerequisite failure evidence, reviewed identity retention during token refresh, canonical Microsoft Graph resource and bounded transient read retries | [`5c9b5a61`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/5c9b5a61b78137e1dd78c4d3e35c5dbd1a7c752a), [`b6145b82`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/b6145b82115ede80d4112acea7a3405a3d836ac0), [`6710a576`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/6710a576c3f61541973b6f040f36eabd5ba9c4d0), [`bbb70a2d`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/bbb70a2d489dda0f7b9bd9dad51834d21fa41ed6) |
| Network preservation | Reviewed VPN route additions, regional endpoint validation, exact bootstrap ownership and independent DNS SOA preservation | [`f5d8f861`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/f5d8f8612c8cc4dec26aba58ddaafde58d6515dd), [`d09cc6d2`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/d09cc6d27d5cc6d0e42778ce02918218006b116e), [`5785f7e0`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/5785f7e00fdc14c21cab5e1e14b9fe51d8a51183), [`7b8605c2`](https://github.com/jostrm/azure-enterprise-scale-ml/commit/7b8605c2d97017ecce84043f5047e43c69add152) |

**Token-workbook adoption:** current source serializes account inventory as text, uses a scalar account selector and normalizes scalar/legacy JSON selections before accepting the resource scope. An already deployed workbook can still contain the older invalid-scope behavior until an approved dashboard refresh. Neither this documentation update nor local source coverage refreshes Azure.

**Current main guidance:** [Setup][current-setup], [updates][current-update], [ITSM/API prerequisites][current-itsm] and [monitoring][current-dashboards]. These links are pinned to the new snapshot; the cumulative v1.25 links elsewhere remain pinned to their original release evidence.

## 3. Reconcile the old v1.24 roadmap

| Old roadmap item | Current assessment | Remaining work / decision |
|---|---|---|
| GitHub Actions parity | Substantial configuration and pipeline alignment exists | Resolve documented registered-runtime provider and atomic-dispatch gaps |
| Enhanced dashboards | Delivered assets in v1.25 plus main-only native cost/default and token-scope fixes | Complete representative Portal and tenant adoption checks; supply application instrumentation |
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

**Published main versus this local checkout:** at the 30 September snapshot, local `main` is `168bb3fa`, one commit ahead and two behind published `main`. Its local-only commit concerns isolated project lake access and AML image-build compute. Published `bbb70a2d` and `7b8605c2` are not ancestors of that local HEAD. Neither local subjects nor dirty files are evidence of additional published features; do not reset or overwrite this work to adopt the published repairs.

The working tree has extensive existing modifications. They are excluded from these notes. The separate branch `release/v.1.25` is also excluded. No branch checkout, merge, reset or publication is part of this documentation task.

To reproduce the exact published comparison:

```powershell
git rev-list --left-right --count 1bd9020e009036427763a0f66b2b2449ca38f288...7b8605c2d97017ecce84043f5047e43c69add152
git log --format=fuller 1bd9020e009036427763a0f66b2b2449ca38f288..7b8605c2d97017ecce84043f5047e43c69add152
git diff --stat 1bd9020e009036427763a0f66b2b2449ca38f288 7b8605c2d97017ecce84043f5047e43c69add152
```

[current-setup]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/7b8605c2d97017ecce84043f5047e43c69add152/documentation/v2/20-29/24-end-2-end-setup.md
[current-update]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/7b8605c2d97017ecce84043f5047e43c69add152/documentation/v2/20-29/26-update-AIFactory.md
[current-itsm]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/7b8605c2d97017ecce84043f5047e43c69add152/documentation/v2/20-29/29-ITSM-integrated.md
[current-dashboards]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/7b8605c2d97017ecce84043f5047e43c69add152/documentation/v2/30-39/32-dashboards.md
[personas]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/7b8605c2d97017ecce84043f5047e43c69add152/documentation/v2/20-29/25-personas-aifactory.md
[persona-config]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/7b8605c2d97017ecce84043f5047e43c69add152/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml
[persona-rbac]: https://github.com/jostrm/azure-enterprise-scale-ml/blob/7b8605c2d97017ecce84043f5047e43c69add152/environment_setup/aifactory/bicep/modules/addUserAsCoreteamBYOVnet.bicep
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
