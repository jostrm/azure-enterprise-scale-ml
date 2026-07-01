# AI Factory — FinOps SHOWBACK Runbook: Quickstart / How-To

Folder: `automation/coreteam/finops/runbooks/showback`

## What it does

Cross-charging as **showback** (visibility, no billing transfer). Reports cost per
AI Factory project / environment / cost center for the current month + forecast,
and archives MD/HTML/PDF to the common data lake.

Replaces the old ADO pipeline `gov-cross-charging.yaml` + `120-124_*.sh`.

## Files

| File | Purpose |
|---|---|
| `Update-ShowbackReport.ps1` | The runbook (PowerShell 7.2). |
| `report-config.json` | Naming seed + showback options + sample data. |
| `deploy-automation.bicep` | Automation Account + MI + schedule + RBAC (sub scope). |
| `modules/automationAccount.bicep` | RG-scoped Automation Account module. |
| `run-and-export.ps1` | Local preview → `reports-out/`. |
| `RUNBOOK.md` | Full details + deploy steps. |

## 1) Prerequisites

- PowerShell 7+ (`pwsh`)
- Modules: `Az.Accounts`, `Az.Resources`, `Az.Storage`

  ```powershell
  Install-Module Az.Accounts,Az.Resources,Az.Storage
  ```

- Signed in: `Connect-AzAccount` (local) **or** managed identity (in Azure)
- RBAC: `Cost Management Reader` + `Reader` at **subscription** scope (deploy bicep grants this)

## 2) Preview locally (no Azure needed) — sample numbers

```powershell
pwsh ./run-and-export.ps1
# or:
pwsh ./Update-ShowbackReport.ps1 -DryRun
```

## 3) Run for real — pick where the variables come from

GitHub Actions (`.env`):

```powershell
pwsh ./Update-ShowbackReport.ps1 -Source github -UseCurrentLogin -SubscriptionId <subId>
```

Azure DevOps (`variables.yaml`):

```powershell
pwsh ./Update-ShowbackReport.ps1 -Source ado -UseCurrentLogin -SubscriptionId <subId>
```

Notes:

- `-Source config` uses `report-config.json` `naming` block (default)
- `-Source github` reads `../../../../.env`
- `-Source ado` reads `variables.yaml`
- `-SettingsPath` override the `.env` / `variables.yaml` path
- `-NoForecast` skip the forecast column
- `-OutDir <path>` also write MD/HTML/PDF locally

Subscription + all project RGs are discovered by naming pattern; tags supply cost center/owner.

## 4) Deploy as Azure Automation Runbook

```bash
az deployment sub create -l <region> -f deploy-automation.bicep \
   -p automationResourceGroupName=<coreteam-rg> location=<region>

az automation runbook replace-content -g <coreteam-rg> \
   --automation-account-name aa-aif-showback \
   --name Update-ShowbackReport --content @Update-ShowbackReport.ps1
az automation runbook publish -g <coreteam-rg> \
   --automation-account-name aa-aif-showback --name Update-ShowbackReport
```

Import `../common/AifFactory.psm1` as a PowerShell 7.2 module into the Automation Account.
For monthly showback: deploy with `scheduleFrequency=Month`.
