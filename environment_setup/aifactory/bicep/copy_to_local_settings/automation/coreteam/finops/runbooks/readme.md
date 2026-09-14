# AI Factory — Foundry Token Report Runbook: Quickstart / How-To

Folder: `aifactory-templates/automation/runbooks`

## Optional desktop / cloud report protocol

`automation\report_compute.py --request <request.json>` is a stdlib-only adapter.
Imports, discovery, samples and viewing saved reports require no Azure packages.
Live PowerShell reports optionally require PowerShell 7 and existing Az modules;
the Python usage report optionally requires its existing `requirements.txt` and
Azure CLI. Nothing is installed or authenticated automatically.
In a frozen/packaged application, live Python usage reports explicitly return
unavailable; use a regular Python interpreter for that optional report.
PowerShell and existing standalone Azure CLI installations remain supported.

Version-1 requests contain `action` (`run`/`status`), `compute`
(`local`/`runbook`/`logicapp`), `report_type` (`foundry-tokens`/`showback`/
`foundry-usage`), `factory_folder`, `days` (1–90), `dry_run`,
`cloud_resource_id`, `run_id`, `report_config`, and `target`.
The exact target contains `subscription_id`, `tenant_id`, `project_number`,
`environment`, `project_resource_group`, `common_resource_group`, and `naming`.
Do not put credentials or callback URLs in requests. `plan()` produces an
offline skeleton; callers must resolve exact targets before live execution.

Results contain `status`, `source`, `compute`, `run_id`, `output`, `warnings`
and `report` (schema-version-1 envelope or null). Cloud results also return
`automation_account_resource_id` and `job_resource_id`. Poll with the original
request plus `action: "status"` and the returned UUID `run_id`. A warning with
a run ID after an uncertain submission means **poll before retrying**.
Failed/unavailable CLI results exit nonzero. Samples never authenticate or
submit jobs, even when cloud compute is selected.

The PowerShell scripts support optional `-ConfigJson`, `-ReportFormat Json`,
`-TenantId` and `-NoUpload`. Markdown, file-based configuration, scheduled
execution and explicitly requested uploads remain available.
`-NoUpload` always wins over blob parameters and showback `uploadToLake`.
Dry runs never upload. No local report files are created unless an output
folder/upload was requested. JSON stdout contains only the report; progress
goes to verbose. Query failures are failed or warning reports, never healthy
initialized zeros. Foundry model pricing/cache/discount/PTU figures are
**configuration assumptions and estimates, not verified actual billing**.

The existing **Monitoring API** bridge is separate and unchanged:
`-MonitoringRequest` plus `-MonitoringPython` routes to
`common\monitoring_report.py` and its strict
`aifactory.aggregate-report.v1` contract. That bridge continues to use selected
identity checks, sparse measurements and selected-project actual cost.
The Python script retains strict `--automation-json` with
`--expected-object-id`, while `--tenant-id` plus `--debug-json` also supports
the compute-selector adapter without ambient-credential fallback.

Live desktop execution checks the current Az PowerShell (PowerShell reports)
or Azure CLI (Python/cloud reports) account against both selected tenant and
subscription. Context autosave is disabled only in the PowerShell child.
Generated Python PDF/JSON intermediates are removed after aggregates are read.
An optional `report_config.workspace_id` must belong to the selected common RG.

For cloud execution, publish the updated matching report runbook. Also import
`common\AifFactory.psm1` as the `AifFactory` module into the Automation runtime
for showback; local execution uses the adjacent module file. The adapter
refuses older published runbooks lacking the safe JSON/NoUpload/target
parameters. Jobs omit `runOn`, and no schedules are deployed or changed.
`foundry-usage` supports local compute only; the existing Python cloud runbook
does not expose this JSON request protocol.

An optional separate report-only Consumption workflow is provided at
`..\logicapps\report-dispatch\main.bicep`. Nothing deploys automatically.
Deploy under a new name, authorize the caller object ID, and explicitly grant
its managed identity only job creation/read and report-runbook read permissions
on the configured existing Automation Account. The report runbook identity
still needs its existing telemetry/cost read permissions. The caller needs
workflow read/listCallbackUrl and runbook/job/output read access.
SAS authentication is disabled. The adapter discovers the Azure callback only
in memory and invokes it using Entra OAuth for the selected tenant/ARM audience.
No callback URL or token is saved. Mandatory tags are
`aifactory-purpose=report-dispatch` and `aifactory-report-protocol=1`.
The existing network-throttling Logic App is never a report endpoint and must
never be selected or invoked.

## What it does

Reproduces the "Reports: Foundry models and token" report (see `readme.md` /
`ignore.md`) from Log Analytics, then adds PAYGO-vs-PTU recommendations.

## Files

| File | Purpose |
|---|---|
| `Update-FoundryTokenReport.ps1` | The runbook (PowerShell 7.2). |
| `report-config.json` | Model info + discount/adjustments + naming seed. |
| `deploy-automation.bicep` | Automation Account + MI + daily schedule + RBAC. |
| `RUNBOOK.md` | Naming rules + deploy details. |
| `readme.md` / `ignore.md` | The report template it reproduces. |

## 1) Prerequisites

- PowerShell 7+ (`pwsh`)
- Modules: `Az.Accounts`, `Az.Resources`, `Az.OperationalInsights`, `Az.Storage`

  ```powershell
  Install-Module Az.Accounts,Az.Resources,Az.OperationalInsights,Az.Storage
  ```

- Signed in: `Connect-AzAccount` (local) **or** managed identity (in Azure)

## 2) Preview locally (no Azure needed) — sample numbers

```powershell
pwsh ./Update-FoundryTokenReport.ps1 -DryRun
```

## 3) Run for real — pick where the variables come from

GitHub Actions (`.env`):

```powershell
pwsh ./Update-FoundryTokenReport.ps1 -Source github -UseCurrentLogin -SubscriptionId <subId>
```

Azure DevOps (`variables.yaml`):

```powershell
pwsh ./Update-FoundryTokenReport.ps1 -Source ado -UseCurrentLogin -SubscriptionId <subId>
```

Notes:

- `-Source github` reads `../../../.env` (`gh-esml-project004-sdc-dev-001-rg`)
- `-Source ado` reads `variables.yaml` (`mrvel-1-esml-project001-eus2-dev-001-rg`)
- `-SettingsPath` override the `.env` / `variables.yaml` path
- `-LookbackDays N` report window (default 30)

Resource Group is concatenated; Foundry/LogAnalytics/UAMI discovered by type.

## 4) Deploy as Azure Automation Runbook (daily)

```bash
# uses the project UAMI (mi-prj*) so no extra RBAC is needed
az deployment group create -g <project-rg> -f deploy-automation.bicep \
   -p commonResourceGroupName=<common-rg> projectUamiResourceId=<mi-prj resourceId>

az automation runbook replace-content -g <project-rg> --automation-account-name <aa> \
   --name Update-FoundryTokenReport --content @Update-FoundryTokenReport.ps1
az automation runbook publish -g <project-rg> --automation-account-name <aa> \
   --name Update-FoundryTokenReport
```

In Azure: pass `-UamiClientId <mi-prj clientId>` in the schedule parameters.

## 5) Configure the model & discounts

Edit `report-config.json`: `eaDiscount`, `cacheRate`, model rates, `inputTpmPerPtu`.

## 6) Zero values?

Missing observations are unavailable, not proof of zero token traffic. JSON mode
reports failed or partial queries explicitly. Check diagnostic routing from the
Foundry account to the selected Log Analytics workspace and the caller's read
permissions. Only an actual returned zero measurement establishes zero traffic.
