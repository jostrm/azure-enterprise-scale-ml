# Foundry Token Report — Azure Automation Runbook

Reproduces the report in [readme.md](readme.md) / `ignore.md` from Log Analytics, then appends
**Recommendations** (PAYGO vs PTU). Inputs for `Model info` and `Discount and adjustments` live in
[report-config.json](report-config.json).

## Files
| File | Purpose |
|---|---|
| `Update-FoundryTokenReport.ps1` | Runbook: resolve resources, query logs, derive cost + PTU, emit Markdown |
| `report-config.json` | Model info + Discount/adjustments + naming concat seed |
| `deploy-automation.bicep` | Automation Account + MI + daily schedule + Reader RBAC |

## Resource-name resolution (no hardcoding)
Subscription + RGs are built like `infra-project.yml` / `CmnAIfactoryNaming.bicep`; resources are
discovered by type because the live name carries a salt.

| Item | Rule | Example (.env) |
|---|---|---|
| Project RG | `{AIFACTORY_PREFIX}{PROJECT_PREFIX}project{PROJECT_NUMBER}-{loc}-{env}{AIFACTORY_SUFFIX}{PROJECT_SUFFIX}` | `gh-esml-project004-sdc-dev-001-rg` |
| Common RG | `{AIFACTORY_PREFIX}{VNET_RESOURCE_GROUP_BASE}-{loc}-{env}{AIFACTORY_SUFFIX}` | `gh-esml-common-sdc-dev-001` |
| Log Analytics | `la-cmn-*` in Common RG | discovered |
| Foundry acct | `Microsoft.CognitiveServices/accounts` in Project RG | discovered |

## Deploy & upload
```powershell
az deployment group create -g <project-rg> -f deploy-automation.bicep -p commonResourceGroupName=<common-rg>
az automation runbook replace-content -g <project-rg> --automation-account-name <aa> --name Update-FoundryTokenReport --content @Update-FoundryTokenReport.ps1
az automation runbook publish -g <project-rg> --automation-account-name <aa> --name Update-FoundryTokenReport
# Grant the Automation MI 'Log Analytics Reader' on the common RG + 'Reader' on the project RG.
```
Required modules: `Az.Accounts`, `Az.OperationalInsights`, `Az.Resources`, `Az.Storage`.
