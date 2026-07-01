# FinOps Showback — Azure Automation Runbook

**Cross-charging as *showback*** (visibility & accountability — **no** billing transfer). Reports cost
per AI Factory **project / environment / cost center** for the current billing month, with an optional
forecast, and archives the report to the common data lake.

> Supersedes the legacy Azure DevOps pipeline
> `azure-devops/esml-yaml-pipelines/aifactory-governance/gov-cross-charging.yaml`
> and its `bicep/scripts/ado/120-124_*.sh` chain.

## Why a runbook (not Logic App / Function)
Scheduled periodic batch report, no HTTP/event trigger — the canonical Automation Runbook case. It
reuses the sibling FinOps runbook pattern in `../` (`Update-FoundryTokenReport.ps1`) and the shared
`../common/AifFactory.psm1` (naming resolution, MI auth, MD→HTML→PDF export, blob upload). A Logic App
suits connector/approval/email flows; a Function needs its own app host + CI — both heavier here.

## Files
| File | Purpose |
|---|---|
| `Update-ShowbackReport.ps1` | Runbook: discover project RGs, query Cost Management (actual + forecast), join `CostCenter`/`AIF-Project Owners` tags, emit Markdown, export + upload |
| `report-config.json` | Naming seed + showback options (currency, forecast, lake upload) + DryRun sample data |
| `deploy-automation.bicep` | Subscription-scoped: Automation Account + MI + schedule + **Cost Management Reader** & **Reader** RBAC |
| `modules/automationAccount.bicep` | RG-scoped module: Automation Account + runbook + schedule |
| `run-and-export.ps1` | Local preview → `reports-out/` (MD/HTML/PDF) |

## Resource-name resolution (no hardcoding)
Subscription + RGs are built like `infra-project.yml` / `CmnAIfactoryNaming.bicep`; **all** project
RGs are discovered by naming pattern (showback spans every project number).

| Item | Rule |
|---|---|
| Project RGs | `{aifactoryPrefix}{projectPrefix}project<NNN>-{loc}-{env}{aifactorySuffix}{projectSuffix}` (regex, all NNN) |
| Common RG | `{aifactoryPrefix}{vnetResourceGroupBase}-{loc}-{env}{aifactorySuffix}` |
| Cost / owner | `CostCenter` + `AIF-Project Owners` tags on each RG |
| Data lake | `*esml*` storage account in the Common RG (auto-discovered) |

## Preview locally (no Azure)
```powershell
pwsh ./run-and-export.ps1                 # DryRun, sample data -> reports-out/
```

## Run for real
```powershell
# Source: config (report-config.json), github (.env) or ado (variables.yaml)
pwsh ./Update-ShowbackReport.ps1 -Source github -UseCurrentLogin -SubscriptionId <subId>
```
Requires `Cost Management Reader` + `Reader` at subscription scope (see bicep).
Modules: `Az.Accounts`, `Az.Resources`, `Az.Storage`.

## Deploy as Automation Runbook
```powershell
az deployment sub create -l <region> -f deploy-automation.bicep `
  -p automationResourceGroupName=<coreteam-rg> location=<region>

az automation runbook replace-content -g <coreteam-rg> --automation-account-name aa-aif-showback `
  --name Update-ShowbackReport --content @Update-ShowbackReport.ps1
az automation runbook publish -g <coreteam-rg> --automation-account-name aa-aif-showback `
  --name Update-ShowbackReport
```
Import `../common/AifFactory.psm1` into the Automation Account as a PowerShell 7.2 module (Modules
blade or `New-AzAutomationModule`). For monthly showback, deploy with `scheduleFrequency=Month`.

## Notes
- **Showback, not chargeback:** no cost is moved between teams — the report gives visibility and
  accountability by `CostCenter` / project owner.
- **Email is out of scope** (visibility, not enforcement). If needed later, add Azure Communication
  Services / Graph as a follow-up step — the old `124_send_email_notifications.sh` was only a stub.
