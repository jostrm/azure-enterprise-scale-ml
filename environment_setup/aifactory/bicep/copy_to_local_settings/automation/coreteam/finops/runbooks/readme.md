# AI Factory — Foundry Token Report Runbook: Quickstart / How-To

Folder: `aifactory-templates/automation/runbooks`

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

Means no token traffic, or token metrics not routed to Log Analytics. Enable a
diagnostic setting on the Foundry (CognitiveServices) account → the LAW, and
ensure there is model usage in the window.
