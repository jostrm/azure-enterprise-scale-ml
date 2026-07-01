================================================================================
 AI Factory - Foundry Token Report Runbook  :  QUICKSTART / HOW-TO
================================================================================

Folder: aifactory-templates/automation/runbooks

WHAT IT DOES
  Reproduces the "Reports: Foundry models and token" report (see readme.md /
  ignore.md) from Log Analytics, then adds PAYGO-vs-PTU Recommendations.

FILES
  Update-FoundryTokenReport.ps1   The runbook (PowerShell 7.2).
  report-config.json              Model info + Discount/adjustments + naming seed.
  deploy-automation.bicep         Automation Account + MI + daily schedule + RBAC.
  RUNBOOK.md                      Naming rules + deploy details.
  readme.md / ignore.md           The report template it reproduces.

--------------------------------------------------------------------------------
 1) PREREQUISITES
--------------------------------------------------------------------------------
  - PowerShell 7+  (pwsh)
  - Modules: Az.Accounts, Az.Resources, Az.OperationalInsights, Az.Storage
        Install-Module Az.Accounts,Az.Resources,Az.OperationalInsights,Az.Storage
  - Signed in:   Connect-AzAccount   (local)   OR   managed identity (in Azure)

--------------------------------------------------------------------------------
 2) PREVIEW LOCALLY (no Azure needed) - sample numbers
--------------------------------------------------------------------------------
  pwsh ./Update-FoundryTokenReport.ps1 -DryRun

--------------------------------------------------------------------------------
 3) RUN FOR REAL - pick where the variables come from
--------------------------------------------------------------------------------
  GitHub Actions (.env):
    pwsh ./Update-FoundryTokenReport.ps1 -Source github -UseCurrentLogin -SubscriptionId <subId>

  Azure DevOps (variables.yaml):
    pwsh ./Update-FoundryTokenReport.ps1 -Source ado    -UseCurrentLogin -SubscriptionId <subId>

  Notes:
    -Source github  reads ../../../.env                       (gh-esml-project004-sdc-dev-001-rg)
    -Source ado     reads variables.yaml                      (mrvel-1-esml-project001-eus2-dev-001-rg)
    -SettingsPath   override the .env / variables.yaml path
    -LookbackDays N report window (default 30)
  Resource Group is concatenated; Foundry/LogAnalytics/UAMI discovered by type.

--------------------------------------------------------------------------------
 4) DEPLOY AS AZURE AUTOMATION RUNBOOK (daily)
--------------------------------------------------------------------------------
  # uses the project UAMI (mi-prj*) so no extra RBAC is needed
  az deployment group create -g <project-rg> -f deploy-automation.bicep \
     -p commonResourceGroupName=<common-rg> projectUamiResourceId=<mi-prj resourceId>

  az automation runbook replace-content -g <project-rg> --automation-account-name <aa> \
     --name Update-FoundryTokenReport --content @Update-FoundryTokenReport.ps1
  az automation runbook publish -g <project-rg> --automation-account-name <aa> \
     --name Update-FoundryTokenReport

  In Azure: pass -UamiClientId <mi-prj clientId> in the schedule parameters.

--------------------------------------------------------------------------------
 5) CONFIGURE THE MODEL & DISCOUNTS
--------------------------------------------------------------------------------
  Edit report-config.json: eaDiscount, cacheRate, model rates, inputTpmPerPtu.

--------------------------------------------------------------------------------
 6) ZERO VALUES?
--------------------------------------------------------------------------------
  Means no token traffic, or token metrics not routed to Log Analytics. Enable a
  diagnostic setting on the Foundry (CognitiveServices) account -> the LAW, and
  ensure there is model usage in the window.
================================================================================
