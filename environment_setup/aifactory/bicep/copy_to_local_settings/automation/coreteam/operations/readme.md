# Development compute STOP/START automation

Create an isolated Azure Automation deployment for a customer's Factory, using
their existing `variables.json`. No tenant, subscription, Factory prefix or
resource name is hardcoded.

The scripts resolve the selected Factory resource groups using the existing
`dev` baseline and `stage_prod` overlay. `stage` means physical `test`. Tenant
and subscription must come from the exact selected section. Within those exact
groups, read-only Azure inventory supplies the real resource names, including
salted and custom names; the scripts do not guess Bicep `uniqueString` outputs.

**Discovery is not authorization.** The output is a frozen target plan. Review
every ID and explicitly approve its hash before deployment. Resource types are
limited to Container Apps and standalone VMs. Production, AKS, VM scale sets,
managed compute, app environments, networking and all other services are
excluded. Common-group VMs require a separate opt-in.

## Default tutorial: one development Factory

Use PowerShell 7.6 and Azure CLI on Windows or PowerShell Cloud Shell. The
deployment caller needs resource creation and custom-role/assignment management
permissions; the Automation identity receives only exact resource-scoped
permissions. Runtime operations use managed identity and ARM REST, without a
laptop or Hybrid Worker.

Start in this `operations` folder in your registered Factory's copied settings
or in this accelerator checkout. Set the customer's actual variables path:

```powershell
$variablesPath = Read-Host 'Full path to the customer variables.json'
$variables = Get-Content -LiteralPath $variablesPath -Raw |
    ConvertFrom-Json -AsHashtable -DateKind String

az login --tenant $variables.dev.tenantId
az account set --subscription $variables.dev.dev_sub_id

$planPath = Join-Path (Split-Path $variablesPath -Parent) 'cost-optimizer.local.json'
```

Create a **read-only** discovery plan. This example uses the project number in
`variables.json`, selects both supported compute types, and explicitly includes
common-group VMs. Omit `-IncludeCommonVms` to restrict the plan to the project RG.

```powershell
.\New-CostOptimizerPlan.ps1 -VariablesPath $variablesPath -Environment dev `
    -Kinds ContainerApp,VirtualMachine -IncludeCommonVms `
    -TimeZone 'Europe/Berlin' -StopTime '03:00' -StartTime '08:00' `
    -OutputPath $planPath
```

Review the saved tenant, subscription, environment, resource groups, every
target, schedule and plan hash:

```powershell
$plan = Get-Content -LiteralPath $planPath -Raw |
    ConvertFrom-Json -AsHashtable -DateKind String
$plan.targets | Format-Table kind,id -AutoSize
$plan | Select-Object tenantId,subscriptionId,timeZone,firstStop,firstStart,planHash
```

The existing template bootstrap copies this package recursively with the rest
of `automation`. In a consumer, it is normally available under
`aifactory\automation\coreteam\operations` (or the staged
`aifactory-templates\automation\coreteam\operations` layout). No additional
pipeline or Wizard integration is required for this standalone operator route.

If the list is too broad, generate a **new filename**, using
`-TargetResourceIds` with the exact wanted IDs. Missing IDs are errors, not
silently ignored. Do not edit the reviewed plan or add resources to a live
configuration. There are at most 16 targets per deployment; split larger scopes.

Only after human review, deploy using the exact hash printed during review:

```powershell
$approvedHash = Read-Host 'Paste the reviewed plan hash to approve deployment'
.\Deploy-TenantCostOptimizer.ps1 -ConfigurationPath $planPath `
    -ApprovedPlanHash $approvedHash
```

This provisions a dedicated Automation RG, PowerShell 7.6 account/runtime,
private state storage, published runbook, least-privilege identity assignments
and two **disabled** schedules. Hosted STOP/START previews and state-only VERIFY
must succeed. Setup does not execute a live target STOP or START.

To explicitly enable the schedules after review:

```powershell
.\Deploy-TenantCostOptimizer.ps1 -ConfigurationPath $planPath `
    -ApprovedPlanHash $approvedHash -EnableSchedules
```

The default first STOP is tomorrow in the selected timezone, not immediately.
`Europe/Berlin` follows CET/CEST automatically. Daily jobs include weekends.
If START is earlier than STOP, its initial occurrence is the following day.
Invalid/ambiguous daylight-saving initial times are rejected.

## Manual commands

Use explicit plan paths, preventing accidental reuse of another customer's
configuration. These commands submit authenticated cloud jobs:

```powershell
.\Invoke-TenantCostOptimizer.ps1 STATUS -ConfigurationPath $planPath
.\Invoke-TenantCostOptimizer.ps1 STOP -ConfigurationPath $planPath -Preview

# Interrupts the reviewed development services:
.\Invoke-TenantCostOptimizer.ps1 STOP -ConfigurationPath $planPath

# Restores only resources confirmed stopped by this automation:
.\Invoke-TenantCostOptimizer.ps1 START -ConfigurationPath $planPath
```

Optional convenience commands in a dedicated terminal session:

```powershell
. .\Commands.ps1
STOP-COST-OPTIMIZE-TENANT -ConfigurationPath $planPath -Preview
START-COST-OPTIMIZE-TENANT -ConfigurationPath $planPath
```

Avoid loading these over another installation's same-named commands in a
terminal that controls a different Factory. Direct script invocation is the
least ambiguous route.

In Azure Portal open the generated Automation account, **Runbooks**, then
`Tenant-Cost-Optimizer`. Select **Start** with explicit `Action=STOP` or `START`
and `Mode=Live`. The runbook defaults to `STATUS` / `Preview`.

## Scope and naming

| Input | Used for |
| --- | --- |
| Exact `dev` / `stage_prod` tenant and `{dev,test}_sub_id` | Azure identity |
| `admin_aifactoryPrefixRG`, `admin_aifactorySuffixRG` | Factory/scale-set naming |
| `projectPrefix`, `projectSuffix`, project number, location suffix | Project resource group |
| `vnetResourceGroupBase`, optional `commonResourceGroup_param` | Common resource group |
| Bounded live resource inventory | Actual Container App and VM names |
| Explicit projects, kinds, optional exact target IDs | Reviewable target selection |

Project RG: `{factoryPrefix}{projectPrefix}project{NNN}-{locationSuffix}-{env}{factorySuffix}{projectSuffix}`.
Common RG: `{factoryPrefix}{vnetResourceGroupBase}-{locationSuffix}-{env}{factorySuffix}`,
unless the existing BYO common RG override is present.

Multiple project groups can be selected using `-ProjectNumbers '007','008'`.
Quote project numbers to preserve leading zeroes in PowerShell.
No other Factory/scale-set is swept merely because it shares a subscription.
Prepare a separate variables-derived plan for that Factory.

For Stage, select its exact identity before planning:

```powershell
az login --tenant $variables.stage_prod.tenantId
az account set --subscription $variables.stage_prod.test_sub_id
.\New-CostOptimizerPlan.ps1 -VariablesPath $variablesPath -Environment stage `
    -ProjectNumbers '007' -Kinds ContainerApp `
    -OutputPath (Join-Path (Split-Path $variablesPath -Parent) 'cost-optimizer-stage.local.json')
```

Keep customer plans and runtime checkpoints outside source control. Do not
upload credentials, the complete variables file or private inventory to a
customer-neutral template. Only identity/naming-derived operational fields and
the variables file hash are exported, never unrelated config values.

## State, recovery and limits

Already-off resources remain off. STOP first saves the original running states;
repeated STOP preserves that cycle. START without an outstanding STOP starts
nothing. START requires a confirmed accepted STOP for each originally running
resource. Unknown STOP acceptance fails closed, not as a successful skip.

Container Apps use the documented app-level Stop/Start API, preserving Single
versus Multiple revision mode without changing the app configuration. Saved
deployment/routing/revision state is checked; changed deployments require
operator review, not activation of obsolete revisions.

Private Storage data-plane access is not required. Checkpoints are compressed
into dedicated container metadata through ARM. A non-expiring, job-bound
container lease serializes cooperating writers. ARM metadata writes are not
lease-fenced compare-and-swap operations; this is not an eight-resource atomic
transaction or protection against unrelated administrative writes.

Ownership is rechecked before changes. Unknown checkpoint writes retain the
mutex. Only its exact terminal-job owner, settled for ten minutes, can be
automatically reclaimed. Suspended/running owners are never stolen. The
compressed metadata cap is checked before target changes; large revision
histories can require a smaller target plan even below the 16-resource cap.

On failure, inspect job exception/output/errors. Retry the same action for
confirmed partial failures. For an unconfirmed STOP that left a resource off,
inspect/restore it manually if appropriate, then retry START. Never discard
the checkpoint or force-release a live mutex to clear an error.

Code-only redeployment requires the same reviewed plan, no active jobs and no
outstanding restore. Schedules are paused during update and restored only after
successful hosted validation. A failed update leaves them disabled visibly.
Changed scope/timing needs deliberate isolated planning, not silent overwriting.
Disable any superseded deployment's schedules before deploying an overlapping
plan; independent Automation accounts do not share a mutex.

Disabling a schedule does not restore resources. If STOP already ran, restore
that cycle before disabling both schedules. Do not disable START while leaving
STOP active unintentionally.

Compute shutdown interrupts pipelines and runner jobs; there is no graceful
build-queue drain integration. START begins at the configured hour, not a
readiness guarantee for that hour. Disks, Search, private endpoint infrastructure
and other fixed charges continue, as do Automation/state-service charges.

## Optional offline regression tests

Existing Pester 5.7.1+ is used with synthetic customer configurations and mocked
Azure calls:

```powershell
Import-Module Pester -MinimumVersion 5.7.1
Invoke-Pester -Path .\tests -Output Detailed
```

No live STOP/START, infrastructure deployment or billed model call is made by
these tests. The generic package is a standalone operator-owned automation, not
a newly wired Factory UI/API/SDK command or a governed MCP action.