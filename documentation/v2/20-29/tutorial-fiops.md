# AI Factory tutorial: FinOps monitoring

Use the **Monitor** dashboard in the Tkinter app to review resource inventory,
model usage, quota signals and project costs. This walkthrough covers read-only
monitoring and report generation, not deployment or cost-control actions.
It does not change resource configuration, quotas, throttling, schedules, email
delivery or Blob storage.

## Before you begin

Open your configured factory in the Tkinter app and select the intended project
and environment. Existing single-factory repositories use the `aifactory` folder.
For live reports, sign in with the Azure permissions required to read the selected
resources and cost data. Confirm the tenant and subscription before proceeding.

Follow the two phases below: inspect current observations, then generate a
reviewed FinOps report. Check each chart's data source and observation time.
Sample, cached and live data serve different purposes and should not be treated
as interchangeable.

## Phase 1: observe before acting

1. Open **Dashboards > AI Factory - overview** for the configured project,
   scale-set, and environment counts. Saved plans are not deployed resources.
2. Open **Capacity issues**. If `preflight-status.json` is absent, capacity is
   explicitly **unknown**. An empty issue list does not confirm available capacity.
3. Open **Lifecycle & services**. Cached data remains labeled cached; refresh is
   the only Azure inventory collection action. Short or single observations do
   not prove an object's age.
4. Open **Models & Quota**. Capacity and token traffic are separate signals.
   Review verified, scoped tokens-per-minute (TPM) pools separately from
   unavailable capacity data; do not combine unrelated quota allocations.
5. Use **Token popularity** for observed input plus output token totals. Choose
   **This month** or **This year** only to change the observation window, not the
   allocation or billing scope.
6. Use **Quota risk** for peak allocated/max TPM pressure. Set a finite threshold
   greater than zero and no more than 100. A 429, partial history, or absent
   pool is not proof of quota exhaustion or available headroom.

## Phase 2: turn evidence into FinOps reporting

1. Open **Automation reports** and select the report, compute target, project,
   environment, and lookback window. Local laptop is the default; Runbook and
   report-only Logic App modes require an explicit approved resource ID.
2. **Sample preview** is fictional, local, and never written to report history.
   It is useful for explaining visualizations, not for a cost or capacity decision.
3. In live mode, choose **Preview execution**. Inspect the exact subscription,
   tenant, project resource group, common resource group, command, days, and
   report-only warnings. Editing an input invalidates the preview.
4. Choose **Run reviewed report** only after the target is correct. The dispatcher
   accepts only its known report scripts and disables upload. It does not alter
   deployments, diagnostics, throttling, schedules, email delivery, or storage.
5. Interpret the returned source, status, warnings, tables, and charts together.
   A missing value means unavailable, not zero.

## Report selection

| Report | Question answered | Important limitation |
|---|---|---|
| Foundry token / PAYGO / PTU | What is the observed account token demand, and how do pay-as-you-go (PAYGO) and provisioned throughput unit (PTU) estimates compare? | Pricing, cache rate, user count and PTU sizing are assumptions, not billed costs or measured per-model utilization. |
| Project and cost-center showback | Which tagged project/cost center incurred billed usage in the selected period? | Showback creates visibility and accountability, not a billing transfer. A failed forecast remains unavailable. |
| Foundry / OpenAI / AI Search usage | Which observed deployment-level request and token measurements are available? | Sessions are summed hourly activity, not period-wide distinct users. Missing telemetry is unavailable, not zero. |

## CLI and API boundary

The Monitor UI prepares the same immutable report request used by the local CLI
dispatcher:

```powershell
python .\automation\report_compute.py --request .\reviewed-report-request.json
```

Create the request through the UI or the Monitor API's planning flow; do not hand
edit a previous request. A live request requires exact target identifiers,
1-90 days, a known report type, and a credential-free report configuration. The
dispatcher verifies the selected Azure CLI tenant/subscription before live
execution. Azure PowerShell reports also require their own signed-in context.

Live Foundry usage reports authenticate against the selected subscription and
validate the token's tenant and identity. If authentication fails, correct the
Azure CLI context and prepare a fresh report request.

## Interpret the results

Compare metrics only when their time window, resource scope and source match.
Use the following distinctions when interpreting a report:

| Result | How to interpret it |
|---|---|
| Input and output tokens | Observed telemetry for the selected scope and period, not a billing total. |
| Total tokens | Input plus output tokens within the same observation scope. |
| Showback actual | Azure Cost Management usage assigned to the selected project or cost center. |
| Unavailable forecast | An incomplete or failed forecast, not zero expected spend. |
| Unavailable quota pool | Insufficient scope or unit evidence; capacity and headroom remain unknown. |

### Track a quota request

The quota-ticket button remains disabled until a verified pool is selected. When
enabled, **Request TPM for this pool** saves a private local tracking draft only;
it does not submit a quota request, send a message, or change Azure.

## Suggested operating cadence

| Cadence | Review |
|---|---|
| Weekly | Token popularity, report warnings, and changed lifecycle observations |
| Monthly | Cost-center showback, billing/forecast completeness, and PAYGO/PTU assumptions |
| Before a scale or model change | Fresh scoped quota snapshot, capacity/preflight evidence, and a reviewed report target |

Return to [end-to-end setup](24-end-2-end-setup.md) for configuration and
deployment boundaries, and to the [full walkthrough](28-tutorial-walkthrough.md)
for the broader application/API/CLI tutorial.
