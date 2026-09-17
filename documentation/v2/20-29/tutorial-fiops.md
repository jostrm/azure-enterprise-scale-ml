# AI Factory tutorial: FinOps monitoring

**Recording: 16 September 2026 · Spider consumer · native Tkinter Monitor dashboard**

This companion walkthrough covers only **Monitor**. It uses the Spider consumer's
active legacy `aifactory` folder and live, read-only Azure observations. It is not
a deployment tutorial: no resource configuration, quota change, schedule, email,
blob upload, or throttling action is performed.

## Tutorial assets

Keep these assets outside the repository with the local tutorial material:

```text
tutorial\
  ppt\Tkinter-tutorial-monitoring.pptx
  ppt\AI Factory tutorial - Monitoring.pptx
  video\AI-Factory-tutorial-monitoring.mp4
  video\tkinter\Tkinter-tutorial-monitoring-screen-recording.mp4
  video\snippets\monitor-phase-1-observe.mp4
  video\snippets\monitor-phase-2-finops.mp4
  image-screenshots\tkinter\
```

The recording is intentionally split into two phases. Read each source and
observation-time label before treating a chart or a table as evidence.

## Phase 1: observe before acting

1. Open **Dashboards > AI Factory - overview** for the configured project,
   scale-set, and environment counts. Saved plans are not deployed resources.
2. Open **Capacity issues**. If `preflight-status.json` is absent, capacity is
   explicitly **unknown**. No issue is not a capacity approval.
3. Open **Lifecycle & services**. Cached data remains labeled cached; refresh is
   the only Azure inventory collection action. Short or single observations do
   not prove an object's age.
4. Open **Models & Quota**. Capacity and token traffic are separate signals.
   The dashboard presents verified scoped TPM pools separately from unavailable
   capacity evidence, never adding allocations together.
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
| Foundry token / PAYGO / PTU | What observed account token demand exists, and what do configured pricing/PTU assumptions estimate? | Pricing, cache rate, user count, and PTU sizing are assumptions; they are not billing truth or per-model measured utilization. |
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

The live Foundry usage worker uses the selected subscription to obtain the Azure
CLI token. Azure CLI rejects token requests that specify both `--tenant` and
`--subscription`; strict monitoring mode continues to validate the resulting
token tenant and object identity.

## Recorded Spider evidence

The recording showed the following live observations for the selected 30-day
period. They are examples from one consumer environment, not reusable forecasts:

| Observation | Recorded value | Interpretation |
|---|---:|---|
| gpt-5.1 input tokens | 338,692 | Observed telemetry |
| gpt-5.1 output tokens | 27,324 | Observed telemetry |
| gpt-5.1 total tokens | 366,016 | Input plus output telemetry |
| Project 001 showback actual | USD 61.43 | Azure Cost Management result for the selected period |
| Showback forecast | Unavailable | Incomplete forecast response, never substituted with zero |
| Verified quota pools | Unavailable | Scope/unit evidence was insufficient; no TPM fact was presented |

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
