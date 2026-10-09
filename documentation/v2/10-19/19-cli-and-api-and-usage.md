# 19. Add and update an AI factory

Choose **one tool tab for this whole tutorial**. Each tab connects independently,
selects real targets, prepares changes and stops for review before confirmation.
Start with [18 — connection and compatibility checks](18-cli-and-api-and-usage.md);
use [20 — removal and recovery](20-cli-and-api-and-usage.md) for deletion or an
uncertain result. [17](17-cli-and-api-and-usage.md) remains historical context.
On GitHub, expand the matching tool section. The documentation website uses
one linked tab selector for the same content.

## Before you start

- Obtain the **owning API's URL and key** from your operator. A demo address/key
  is not for real resources. These administrative endpoints currently require
  local-host access. Keep the key out of browser code, source control and output.
- `folder`, `repo_root` and import paths refer to the **API host**. Request files
  and reviews below are **client-local**. A needs an operator-created, empty
  `azurefactory` folder; B–E need the real registered catalog, not a smoke-test root.
- **No deployment yet:** confirming configuration saves settings (`job: null`).
  Runtime confirmation is separate and can create billable resources, publish Git
  changes and start pipelines. `can_execute: true` is not approval or proof of success.
- **STOP and review** the exact folder, IDs, environment, tenant/subscription,
  version, changes, ownership, warnings and expiry. Keep reviews in private,
  persistent storage outside Git and temporary cleanup folders; verify its access
  permissions. Checksums detect file changes; they are not signatures or approval.
- **Never retry an uncertain write**, or switch tools to repeat it. Inspect saved
  state first. A timeout stops waiting, not the deployment.
- Settings saves and typed `unset` do not delete Azure resources. `null` is not a
  general unset. Changes to shared **`stage_prod`** settings can affect both Stage
  and Prod: replacing shared values can lose settings the other environment uses.
  Review both; do not assume Stage-only isolation. A parameter profile reset discards **all old protected parameter
  settings in that scale set**, even when one project is selected; do not use it
  to bypass an error.

<details markdown="1">
<summary>More info</summary>

| Intent | Support and limit |
|---|---|
| **A. New factory, selected Dev/Stage/Prod, project001, own hub intent; clone** | **implemented** configuration preparation and confirmation. The short request does not configure or deploy a complete VPN/hub. |
| **B. Add a scale set and/or project** | **implemented**; separate configuration changes. An AI Factory scale set is an environment/network/subscription grouping, **not Azure VMSS**. |
| **C. Latest successful scale in an explicit environment** | **implemented** in newer API source. Environment-only placement is **not yet in the published API baseline**; install-compatible host required, no implicit Dev. |
| **D. Stage/Prod placement versus captured promotion** | Placement is **implemented**. Executing a captured successful Dev configuration/version through Stage and Prod is **not implemented**. Backend capture/review work is in progress, not a published executable promotion route. |
| **E. Typed parameters and scoped settings** | **implemented**, including named CLI/SDK preparation and typed review receipts. |
| Runtime and registered Full bootstrap | **conditional/blocked** by host/runtime versions, permissions, bindings, ownership, identity, runners and network readiness. |
| Migration, draft identity correction, direct binding configuration, registered creation API | **generic-access only** where supported; no invented dedicated helpers. |
| Unified APIM-versus-Kong deployment choice | **not implemented**. Newer MCP/AI Gateway component pipelines have **conditional/blocked** support; Application Gateway is a different product and its registered workflow is blocked. |

Read the chosen API's capabilities and OpenAPI before using a request. A newer
client cannot supply a missing server/runtime feature. `DEV/001`, `STAGE/001`
and `PROD/001` are different targets; `001` is not a UUID. API environments are
`dev`, `stage`, `prod` (some Azure naming uses `test` for Stage).

</details>

## Choose your tool

<details markdown="1" data-factory-tool="CLI (PowerShell)">
<summary>CLI (PowerShell)</summary>

## Connect and define the local helpers

Use Windows PowerShell 5.1+ or PowerShell 7, an existing API Python environment
and the approved accelerator checkout. No console-script installation or
variables from another tab are required. These snippets run in **one shell**.

```powershell
$ErrorActionPreference = 'Stop'
$ApiRoot = Read-Host 'Absolute path to your existing API checkout'
$AcceleratorRoot = Read-Host 'Absolute path to your approved accelerator checkout'
$Python = Join-Path $ApiRoot '.venv\Scripts\python.exe'
$SdkSource = Join-Path $AcceleratorRoot 'environment_setup\azurefactory-cli\src'
if (!(Test-Path -LiteralPath $Python -PathType Leaf) -or
    !(Test-Path -LiteralPath $SdkSource -PathType Container)) { throw 'Check existing tool paths.' }
$env:PYTHONPATH = $SdkSource
$env:AIFACTORY_API_URL = Read-Host 'Operator-provided owning API URL, without trailing slash'
if (!$env:AIFACTORY_API_URL) { throw 'Do not use an implicit demo URL.' }
if (!$env:AIFACTORY_API_KEY) {
    $Secret = Read-Host 'Operator-provided API key' -AsSecureString
    $Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
    try { $env:AIFACTORY_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer) }
}
if (!$env:AIFACTORY_API_KEY) { throw 'Missing API key.' }
& $Python -m azurefactory health
if ($LASTEXITCODE -ne 0) { throw 'API unavailable.' }
& $Python -m azurefactory doctor
if ($LASTEXITCODE -ne 0) { throw 'Incompatible host; stop.' }
$FactoryFolder = Read-Host 'Exact absolute azurefactory folder ON THE API HOST'
if (![IO.Path]::IsPathRooted($FactoryFolder)) { throw 'Use an absolute API-host path.' }
$ReviewRoot = Join-Path $env:LOCALAPPDATA ('AzureFactory\reviews\' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $ReviewRoot -Force | Out-Null

function New-ReviewPath([string]$Label) {
    return (Join-Path $ReviewRoot ($Label + '-' + [guid]::NewGuid().ToString('N') + '.json'))
}
function Write-ReviewJson($Value, [string]$Label) {
    $Path = New-ReviewPath $Label
    [IO.File]::WriteAllText($Path, (ConvertTo-Json -InputObject $Value -Depth 100),
        [Text.UTF8Encoding]::new($false))
    return $Path
}
function Read-Catalog {
    $Text = & $Python -m azurefactory catalog list --folder $FactoryFolder
    if ($LASTEXITCODE -ne 0) { throw 'Catalog read failed.' }
    $Value = ($Text -join "`n") | ConvertFrom-Json
    if ($Value.contract_version -ne 1 -or $Value.mode -ne 'catalog') { throw 'Not a registered catalog.' }
    return $Value
}
function Read-Target([switch]$Scale, [switch]$Project, [switch]$Placed) {
    $Catalog = Read-Catalog
    $Catalog.factories | Select-Object id,key,region,version_ref | Format-Table | Out-Host
    $Id = Read-Host 'Exact factory UUID'
    $Found = @($Catalog.factories | Where-Object { $_.id -eq $Id })
    if ($Found.Count -ne 1) { throw 'Select exactly one listed factory.' }
    $Factory = $Found[0]; $SelectedScale = $null; $SelectedProject = $null
    if ($Scale) {
        $Factory.scale_sets | Select-Object id,environment,suffix,tenant_id,subscription_id | Format-Table | Out-Host
        $Id = Read-Host 'Exact scale-set UUID'
        $Found = @($Factory.scale_sets | Where-Object { $_.id -eq $Id })
        if ($Found.Count -ne 1) { throw 'Select exactly one listed scale.' }
        $SelectedScale = $Found[0]
    }
    if ($Project) {
        $Factory.projects | Select-Object id,number,display_name,placements | Format-List | Out-Host
        $Id = Read-Host 'Exact project UUID'
        $Found = @($Factory.projects | Where-Object { $_.id -eq $Id })
        if ($Found.Count -ne 1) { throw 'Select exactly one listed project.' }
        $SelectedProject = $Found[0]
        if ($Placed -and !@($SelectedProject.placements | Where-Object {
            $_.scale_set_id -eq $SelectedScale.id -and $_.environment -eq $SelectedScale.environment
        }).Count) { throw 'Project is not placed in this scale.' }
    }
    return @{ catalog=$Catalog; factory=$Factory; scale=$SelectedScale; project=$SelectedProject }
}
function Read-NewScale {
    $Environment = (Read-Host 'Environment: dev, stage or prod').Trim().ToLowerInvariant()
    if ($Environment -notin @('dev','stage','prod')) { throw 'Invalid environment.' }
    $Suffix = Read-Host 'Unused three-digit suffix, 001 through 999'
    if ($Suffix -notmatch '^(?!000)[0-9]{3}$') { throw 'Invalid suffix.' }
    $Tenant = [guid](Read-Host 'Approved existing tenant UUID')
    $Subscription = [guid](Read-Host 'Approved existing subscription UUID')
    if ($Tenant -eq [guid]::Empty -or $Subscription -eq [guid]::Empty) { throw 'Nonzero UUIDs required.' }
    $Route = (Read-Host 'Orchestrator: ado or gha').Trim().ToLowerInvariant()
    if ($Route -notin @('ado','gha')) { throw 'Invalid route.' }
    $Cidr = Read-Host 'Approved non-overlapping VNet CIDR'
    $Capacity = [int](Read-Host 'Approved project capacity, 1 through 8')
    if ($Capacity -lt 1 -or $Capacity -gt 8) { throw 'Invalid capacity.' }
    return @{ environment=$Environment; suffix=$Suffix; tenant_id=$Tenant.ToString()
        subscription_id=$Subscription.ToString(); orchestrator=$Route
        network=@{ vnet_cidr=$Cidr; max_projects=$Capacity } }
}
```

## A. Save a new factory and project001

Select the environments explicitly. The owned-hub flags save intent only:
this is **not a complete VPN run**. Use a fresh identity; creation does not
reopen an existing draft. No tenant or subscription is created.

```powershell
$Before = Read-Catalog
if (@($Before.factories).Count) { throw 'This example requires the approved empty new-factory root.' }
$FactoryKey = Read-Host 'New unique factory key'
$Prefix = Read-Host 'Approved new prefix'
$Region = Read-Host 'Approved region supported by capabilities'
$Version = Read-Host 'Approved registered source version: main or supported 125+'
$Environments = @((Read-Host 'Selected environments, comma-separated: dev,stage,prod').Split(',') |
    ForEach-Object { $_.Trim().ToLowerInvariant() })
if (!$Environments.Count -or @($Environments | Where-Object { $_ -notin @('dev','stage','prod') }).Count -or
    @($Environments | Select-Object -Unique).Count -ne $Environments.Count) { throw 'Select each environment once.' }
$Scales = @()
foreach ($Environment in $Environments) {
    Write-Host "Enter the new scale for $Environment."
    $Scale = Read-NewScale
    if ($Scale.environment -ne $Environment) { throw 'Environment differs from selection.' }
    $Scales += $Scale
}
$InitialProject = @{ number='001'; display_name=(Read-Host 'Project001 display name')
    placements=@($Scales | ForEach-Object { @{ environment=$_.environment; suffix=$_.suffix } }) }
$ScalePath = Write-ReviewJson $Scales 'scales'
$ProjectPath = Write-ReviewJson $InitialProject 'project001'
$SettingsPath = Write-ReviewJson @{ enableAIFactoryHub=$true; centralDnsZoneByPolicyInHub=$false } 'settings'
$ReceiptPath = New-ReviewPath 'factory-create'
& $Python -m azurefactory factory create --folder $FactoryFolder --factory-key $FactoryKey `
    --kind ai --prefix $Prefix --region $Region --aifactory-version $Version `
    --expected-revision $Before.revision --scale-set-json $ScalePath `
    --initial-project-json $ProjectPath --settings-json $SettingsPath --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Creation preview blocked.' }
```

**STOP.** Use the separate confirmation block below only after configuration
approval. Re-read and verify project001's selected placements; **do not add
project001 again**. Stage/Prod configuration and similarly named GitHub
environments do not deploy Stage/Prod. Registered bootstrap starts with its
selected initial Dev target.

### Clone configuration instead

This copies configuration, not resources, data, models or credentials.

```powershell
$Scope = Read-Target
$Prefix = Read-Host 'Approved new prefix'
$Region = Read-Host 'Approved target region'
$Include = Read-Host 'Copy project configuration: none or all'
if ($Include -notin @('none','all')) { throw 'Choose none or all.' }
if ($Prefix -eq $Scope.factory.prefix -and $Region -eq $Scope.factory.region) { throw 'Choose a new identity.' }
$ReceiptPath = New-ReviewPath 'factory-clone'
& $Python -m azurefactory factory clone --folder $FactoryFolder --factory-id $Scope.factory.id `
    --prefix $Prefix --region $Region --include-projects $Include `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Clone preview blocked.' }
```

**STOP** for separate confirmation. Review new IDs, network addresses, copied
settings and pipeline bindings before considering deployment.

## B. Add a scale set, then optionally a new project

```powershell
$Scope = Read-Target
$Scale = Read-NewScale
if (@($Scope.factory.scale_sets | Where-Object {
    $_.environment -eq $Scale.environment -and $_.suffix -eq $Scale.suffix
}).Count) { throw 'Environment/suffix already exists.' }
$ScalePath = Write-ReviewJson @($Scale) 'scale'
$ReceiptPath = New-ReviewPath 'scaleset-add'
& $Python -m azurefactory scaleset add --folder $FactoryFolder --factory-id $Scope.factory.id `
    --scale-set-json $ScalePath --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Scale preview blocked.' }
```

**STOP**, approve and confirm that configuration first. The following is an
independent change, not an all-or-nothing extension of the scale-set save.
Select the newly saved scale UUID if that is the intended placement.

```powershell
$Scope = Read-Target -Scale
$Number = Read-Host 'Unused project number, 001 through 999 (not project001 already created by A)'
if ($Number -notmatch '^(?!000)[0-9]{3}$') { throw 'Invalid number.' }
$Name = Read-Host 'Project display name'
$Placement = $Scope.scale.environment + '=' + $Scope.scale.id
$ReceiptPath = New-ReviewPath 'project-add'
& $Python -m azurefactory project add --folder $FactoryFolder --factory-id $Scope.factory.id `
    --number $Number --display-name $Name --placement $Placement `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Project preview blocked.' }
```

**STOP** and confirm separately. Server checks cover number conflicts in the
selected locations and the layout-2 project home, not an invented global rule.

## C. Let the API choose a successful scale in one environment

**Requires newer API source, not yet the published baseline.** This is an
alternative to B's project creation, not a second add of the same project.
No environment is inferred.

```powershell
$Scope = Read-Target
$Environment = (Read-Host 'Explicit environment: dev, stage or prod').Trim().ToLowerInvariant()
if ($Environment -notin @('dev','stage','prod')) { throw 'Choose an environment.' }
$Number = Read-Host 'Unused three-digit project number'
if ($Number -notmatch '^(?!000)[0-9]{3}$') { throw 'Invalid number.' }
$Name = Read-Host 'Project display name'
$ReceiptPath = New-ReviewPath 'project-auto-placement'
& $Python -m azurefactory project add --folder $FactoryFolder --factory-id $Scope.factory.id `
    --number $Number --display-name $Name --environment $Environment `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Automatic placement blocked; do not guess a scale.' }
```

**STOP** and review the resolved scale UUID and completed common deployment.
The service checks recorded success for the factory/environment/version and
capacity; it does not just choose the highest suffix. Confirmation does not
switch to a newer scale silently.

<details markdown="1">
<summary>More info</summary>

Inspect `latest-successful-placement-v1`, `resolved_placements`, source commit,
completed job and `evidence_hash`. An older API may reject environment-only
placement with HTTP 422. If the operator deliberately chooses the older explicit
selector **before preparation**, replace `--environment $Environment` with
`--placement ($Environment + '=latest-successful')`. Never use both.
`project add-placements` supports these selectors too; neither means promotion.

</details>

## D. Add a Stage or Prod placement — not captured promotion

Executing captured successful Dev settings/version in Stage then Prod is
**not implemented**. Instead, prepare a target placement, review its parameters,
then prepare deployment separately. `--version-ref` selects code; it does not
copy settings, data, models or deployment success.

```powershell
$Scope = Read-Target -Scale -Project
$Environment = $Scope.scale.environment
if ($Environment -notin @('stage','prod')) { throw 'Choose Stage or Prod.' }
if (@($Scope.project.placements | Where-Object { $_.environment -eq $Environment }).Count) {
    throw 'Placement already exists; inspect it rather than moving it implicitly.'
}
$ReceiptPath = New-ReviewPath 'project-placement'
$Placement = $Environment + '=' + $Scope.scale.id
& $Python -m azurefactory project add-placements --folder $FactoryFolder `
    --factory-id $Scope.factory.id --project-id $Scope.project.id --placement $Placement `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Placement preview blocked.' }
```

**STOP** for confirmation. Prod requires a new target review; this operation
does not automatically require Stage to have succeeded.

## E. Change typed parameters or scoped settings

First read the target's published parameter schema. This example changes one
placed project's parameter. For common-only parameters, select only a scale
and omit `project_id`/`--project-id` from the read and request.

```powershell
$Scope = Read-Target -Scale -Project -Placed
$Text = & $Python -m azurefactory parameters get --folder $FactoryFolder `
    --factory-id $Scope.factory.id --scale-set-id $Scope.scale.id --project-id $Scope.project.id
if ($LASTEXITCODE -ne 0) { throw 'Cannot read parameter schema.' }
$Parameters = ($Text -join "`n") | ConvertFrom-Json
$Parameters | ConvertTo-Json -Depth 100
if ($Parameters.requires_profile_reset) { throw 'Profile reset requires a separate wider review.' }
$Template = Read-Host 'Exact template name from the response'
$Found = @($Parameters.templates | Where-Object { $_.template -eq $Template })
if ($Found.Count -ne 1) { throw 'Select one listed template.' }
$Field = Read-Host 'Exact editable field name'
$Fields = @($Found[0].fields | Where-Object { $_.name -eq $Field -and !$_.sensitive })
if ($Fields.Count -ne 1) { throw 'This example requires a listed non-secret field.' }
$Edit = Read-Host 'set or unset'
$Patch = @{ template=$Template; parameters=@{}; unset=@() }
if ($Edit -eq 'set') {
    $Patch.parameters[$Field] = ConvertFrom-Json -InputObject (Read-Host 'Approved JSON value; no secrets')
} elseif ($Edit -eq 'unset') { $Patch.unset = @($Field) }
else { throw 'Choose set or unset.' }
$RequestPath = Write-ReviewJson @{
    contract_version=1; folder=$FactoryFolder; factory_id=$Scope.factory.id
    scale_set_id=$Scope.scale.id; project_id=$Scope.project.id
    expected_revision=$Parameters.source_revision; schema_revision=$Parameters.schema_revision
    templates=@($Patch)
} 'parameters'
$ReceiptPath = New-ReviewPath 'parameters-receipt'
& $Python -m azurefactory parameters prepare --request-json $RequestPath --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Parameter preview blocked.' }
```

**STOP** for parameter confirmation. `unset` removes an override, allowing an
inherited/default value to apply; it is not `null` or resource deletion.

For a settings replacement, use this **separate** scenario. It reads
`field_keys`, changes one scalar and leaves omitted keys unchanged.

```powershell
$Scope = Read-Target -Scale
$Text = & $Python -m azurefactory catalog settings --folder $FactoryFolder `
    --factory-id $Scope.factory.id --scale-set-id $Scope.scale.id
if ($LASTEXITCODE -ne 0) { throw 'Cannot read settings.' }
$Settings = ($Text -join "`n") | ConvertFrom-Json
$Settings | ConvertTo-Json -Depth 100
$Field = Read-Host 'Exact editable field_key'
if ($Field -notin $Settings.field_keys) { throw 'Unlisted field.' }
$Value = ConvertFrom-Json -InputObject (Read-Host 'Approved non-null scalar JSON replacement; no secrets')
if ($null -eq $Value -or $Value -is [array] -or $Value -is [pscustomobject]) { throw 'Use a non-null scalar.' }
$Changes = @{}; $Changes[$Field] = $Value
$ChangesPath = Write-ReviewJson $Changes 'settings'
$ReceiptPath = New-ReviewPath 'settings-receipt'
& $Python -m azurefactory catalog configure-settings --folder $FactoryFolder `
    --factory-id $Scope.factory.id --scale-set-id $Scope.scale.id --settings-json $ChangesPath `
    --expected-revision $Settings.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Settings preview blocked.' }
```

**STOP** before catalog confirmation. To change factory-level settings, omit
the scale selector from both read and prepare; for project settings select a
checked placed project and include its ID in both. Identity, network addresses
and code version are not arbitrary settings fields.

## Confirm the one configuration or runtime review you approved

Run this block only after reviewing the receipt from **one** scenario.
In a new shell, repeat connection setup and enter its saved receipt path.
Do not prepare the change again just to obtain a new variable.

```powershell
$ReceiptPath = Read-Host 'Absolute path to the exact reviewed receipt'
$Receipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
$Receipt.preview | ConvertTo-Json -Depth 100
$Approved = Read-Host 'After approval, paste this review confirmation_id'
if ($Approved -cne $Receipt.confirmation_id) { throw 'Approval does not match.' }
if ($Receipt.purpose -eq 'parameters-confirm' -and $Receipt.operation_mode -eq 'configuration') {
    & $Python -m azurefactory parameters confirm --receipt $ReceiptPath --yes
} elseif ($Receipt.purpose -eq 'catalog-confirm' -and $Receipt.operation_mode -eq 'runtime') {
    & $Python -m azurefactory runtime confirm --receipt $ReceiptPath --yes
} elseif ($Receipt.purpose -eq 'catalog-confirm' -and $Receipt.operation_mode -eq 'configuration') {
    & $Python -m azurefactory catalog confirm --receipt $ReceiptPath --yes
} else { throw 'Wrong receipt type for this block.' }
if ($LASTEXITCODE -ne 0) { throw 'Inspect state; do not repeat confirmation.' }
& $Python -m azurefactory catalog list --folder $Receipt.folder
if ($LASTEXITCODE -ne 0) { throw 'Readback failed; do not repeat the write.' }
```

The CLI checks receipt host, hashes, purpose, mode, expiry and server bindings.
For configuration, expect a returned catalog and `job: null`; verify the exact
saved changes and read parameters/settings again when those changed.

## Separate runtime deployment

This prepares only. Use the preceding confirmation block **only after separate
deployment approval**; it chooses `runtime confirm`, not a configuration save.

```powershell
$Kind = Read-Host 'Deploy project or common only? Type project or common'
if ($Kind -eq 'project') { $Scope = Read-Target -Scale -Project -Placed }
elseif ($Kind -eq 'common') { $Scope = Read-Target -Scale }
else { throw 'Choose project or common.' }
$Version = Read-Host 'Explicit approved runtime code version/reference'
if (!$Version) { throw 'Choose a version.' }
$ReceiptPath = New-ReviewPath 'runtime'
$Arguments = @('-m','azurefactory','runtime','deploy','--folder',$FactoryFolder,
    '--factory-id',$Scope.factory.id,'--scale-set-id',$Scope.scale.id,
    '--version-ref',$Version,'--expected-revision',$Scope.catalog.revision,'--save-receipt',$ReceiptPath)
if ($Kind -eq 'project') { $Arguments += @('--project-id',$Scope.project.id) }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw 'Runtime blocked; do not switch to legacy/bootstrap.' }
```

Omitting the project deliberately means **common-only**, not every project.
Common-only, GHA and shared-remote execution require compatible runtime support.
After the approved confirmation, observe the returned job:

```powershell
$Receipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
& $Python -m azurefactory catalog jobs --folder $Receipt.folder
if ($LASTEXITCODE -ne 0) { throw 'Cannot read jobs.' }
$JobId = Read-Host 'Exact job UUID returned by your runtime confirmation; verify its scope above'
& $Python -m azurefactory runtime status --folder $Receipt.folder --job-id $JobId
if ($LASTEXITCODE -ne 0) { throw 'Inspect the reported state.' }
& $Python -m azurefactory runtime poll --folder $Receipt.folder --job-id $JobId --poll-timeout 300 --poll-interval 2
if ($LASTEXITCODE -ne 0) { throw 'Inspect timeout/failure/uncertainty; do not redispatch.' }
```

Check actual pipeline results, target and version before claiming success.

## Registered Full bootstrap

**Conditional/blocked.** Read the [shared bootstrap requirements](#registered-full-bootstrap)
first. It can create billable resources, identities, groups, networks, runners
and repositories, commit/push and start pipelines. Do not recreate an existing
factory to change routes or substitute a legacy launcher to bypass a blocker.

```powershell
& $Python -m azurefactory bootstrap capabilities
if ($LASTEXITCODE -ne 0) { throw 'Cannot read capabilities.' }
& $Python -m azurefactory schema --openapi
if ($LASTEXITCODE -ne 0) { throw 'Cannot read schema.' }
$Scope = Read-Target -Scale -Project -Placed
if ($Scope.scale.environment -ne 'dev') { throw 'Select the initial Dev target.' }
$ConfigPath = Read-Host 'Existing client-local JSON file containing the complete reviewed bootstrap_config object'
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
foreach ($Key in @('subscription_id','tenant_id','scale_set_number','repo_root','team_member_email','team_group_name')) {
    if (!$Config.$Key) { throw "Missing bootstrap field: $Key" }
}
if ($Config.subscription_id -ne $Scope.scale.subscription_id -or $Config.tenant_id -ne $Scope.scale.tenant_id -or
    $Config.scale_set_number -ne $Scope.scale.suffix -or $Config.project_number -ne $Scope.project.number) {
    throw 'Bootstrap configuration differs from the saved target.'
}
$ApprovalMode = Read-Host 'Choose per-stage or whole-workflow'
if ($ApprovalMode -notin @('per-stage','whole-workflow')) { throw 'Choose an approval mode.' }
$WorkflowRequest = @{
    contract_version=1; operation='create-factory'; execution_mode='privileged-bootstrap'
    creation_mode='full-bootstrap'; approval_mode=$ApprovalMode; expected_revision=$Scope.catalog.revision
    scope=@{ folder=$FactoryFolder; factory_id=$Scope.factory.id; scale_set_id=$Scope.scale.id; project_id=$Scope.project.id }
    bootstrap_config=$Config
}
$WorkflowPath = Write-ReviewJson $WorkflowRequest 'workflow-request'
$PreflightPath = Write-ReviewJson @{
    contract_version=1; orchestrator=$Scope.scale.orchestrator; bootstrap_config=$Config
    scope=$WorkflowRequest.scope; expected_revision=$Scope.catalog.revision
} 'preflight-request'
$ReportPath = New-ReviewPath 'preflight'
& $Python -m azurefactory preflight --request-json $PreflightPath --save-report $ReportPath
if ($LASTEXITCODE -ne 0) { throw 'Preflight blocked/incomplete; no deployment approval.' }
$WorkflowReceiptPath = New-ReviewPath 'workflow-review'
& $Python -m azurefactory bootstrap workflow prepare --request-json $WorkflowPath --save-receipt $WorkflowReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Workflow preparation blocked.' }
```

**STOP**. For per-stage mode review this stage. For optional bounded
whole-workflow mode review **all listed stages**, targets, expiry, fingerprints,
`authorization_hash` and estimated cost (not a spending limit). Do not blindly
approve stages in a loop.

```powershell
$WorkflowReceipt = Get-Content -LiteralPath $WorkflowReceiptPath -Raw | ConvertFrom-Json
$Approved = Read-Host 'After approval, paste the exact workflow confirmation_id'
if ($Approved -cne $WorkflowReceipt.confirmation_id) { throw 'Approval does not match.' }
& $Python -m azurefactory bootstrap workflow start --receipt $WorkflowReceiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect workflow state; do not repeat start.' }
$WorkflowId = $WorkflowReceipt.preview.workflow_id
& $Python -m azurefactory bootstrap workflow status --folder $FactoryFolder --workflow-id $WorkflowId
if ($LASTEXITCODE -ne 0) { throw 'Inspect the reported boundary.' }
```

For per-stage mode, **only when status reports `requires_review: true`**:

```powershell
$WorkflowReceiptPath = New-ReviewPath 'next-stage'
& $Python -m azurefactory bootstrap workflow next --folder $FactoryFolder `
    --workflow-id $WorkflowId --save-receipt $WorkflowReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'No confirmable next stage.' }
```

**STOP again**, then use the start block with this new receipt after its own
approval. For whole-workflow mode, use the following only when the server
reports safe continuation of the **existing** approval, never as a retry of
a running, failed or uncertain stage:

```powershell
$OriginalReceiptPath = Read-Host 'Original approved whole-workflow receipt path'
$Original = Get-Content -LiteralPath $OriginalReceiptPath -Raw | ConvertFrom-Json
$Hash = $Original.preview.review.workflow_authorization.authorization_hash
if (!$Hash) { throw 'Not a whole-workflow receipt.' }
if ((Read-Host 'After checking server state, type CONTINUE') -cne 'CONTINUE') { throw 'Stopped.' }
& $Python -m azurefactory bootstrap workflow continue --folder $Original.folder `
    --workflow-id $Original.preview.workflow_id --authorization-hash $Hash
if ($LASTEXITCODE -ne 0) { throw 'Inspect state; never loop continue on failure.' }
```

<details markdown="1">
<summary>Alternative and Legacy ways</summary>

Advanced enrollment is a **local-core** workflow, not an SDK/REST equivalent
or mandatory prerequisite for API-managed Full bootstrap. `enrollment plan`
reads provider state; `ensure` can create billable resources and grant roles.
Independently approve its plan, then review `prepare-binding` and approve
`publish`. `plan-and-publish` is an alternative combining enrollment and binding
publication, not an extra step. Its governance flag acknowledges administrator-
arranged exclusive writers; it does not arrange them. Do not change an existing
binding's coordination mode to unblock it. Follow the
[complete enrollment reference](../../../environment_setup/azurefactory-cli/readme.md#enroll-a-registered-factory--scale-set).

Legacy `aifactory` roots use `legacy list`, `config review`, then separately
approved `config save --expected-review … --yes`. Preserve `_json_source`;
choose an exact saved project, not a startup hint. Saving writes configuration
and normally pipeline variables, not deployment or Git publication.
`--snapshot-only` must be used on **both** review and save when chosen.
Separate `legacy plan` → `legacy prepare` → approved `legacy start` →
`legacy status` uses deployment contract 2. `submitted` means the local launcher
finished, **not** Azure success; inspect `execution_result`.
Older `bootstrap prepare/start/status` uses the legacy launcher API, not
`bootstrap workflow`. Legacy 124 is not a registered-version fallback.
See the [canonical CLI reference](../../../environment_setup/azurefactory-cli/readme.md).

</details>

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="Python SDK">
<summary>Python SDK</summary>

## Connect and save the reusable Python helpers

These are **normal Python programs**, not PowerShell scripts. Use Python 3.10+
and your existing approved accelerator checkout. The helper prompts for that
checkout's root and adds its SDK source directory to Python's import path
**before importing the client**. Neither this tab nor guide 18 requires an SDK
installation. No CLI call is needed to discover IDs or prepare a change.

Save the following as **`aif_review.py`** in your private working folder.
Each scenario below is a separate file in the same folder. `connect()` prompts
for the API-host catalog path; it never assumes guide 18's demo target.

```python
import getpass
import ipaddress
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4

accelerator = Path(input("Absolute path to your approved accelerator checkout: ").strip()).expanduser()
source = accelerator / "environment_setup" / "azurefactory-cli" / "src"
if not accelerator.is_absolute() or not (source / "azurefactory" / "client.py").is_file():
    raise RuntimeError("Check the existing approved accelerator checkout path.")
sys.path.insert(0, str(source))

from azurefactory import AzureFactoryClient
from azurefactory.client import (
    canonical_json_hash, catalog_settings_request, factory_create_request, redact_secrets,
)
from azurefactory.catalog_requests import (
    factory_clone_request, scaleset_add_request,
    project_add_request, project_add_placements_request,
)
from azurefactory.review import load_receipt, parse_expires_at, validate_preview, write_receipt

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def choice(prompt, allowed):
    value = input(prompt).strip()
    require(value in allowed, "Choose exactly one listed value.")
    return value

def connect():
    url = os.getenv("AIFACTORY_API_URL") or input("Operator-provided owning API URL: ").strip()
    key = os.getenv("AIFACTORY_API_KEY") or getpass.getpass("API key: ")
    require(bool(url and key), "Explicit URL and key required; no demo default.")
    c = AzureFactoryClient(base_url=url, api_key=key)
    c.health()
    folder = input("Exact absolute azurefactory folder ON THE API HOST: ").strip()
    require(bool(folder), "Select the approved host folder.")
    return c, folder

def show(c, value):
    print(json.dumps(redact_secrets(value, c.api_key), indent=2, ensure_ascii=False))

def read_json(prompt):
    return json.loads(Path(input(prompt).strip()).expanduser().read_text(encoding="utf-8-sig"))

def private_directory():
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        os.umask(0o077)
        base = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    root = base / "AzureFactory" / "reviews"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root

def save_json(c, value, label):
    path = private_directory() / f"{label}-{uuid4().hex}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(redact_secrets(value, c.api_key), stream, indent=2, ensure_ascii=False)
    print("Saved private file:", path)
    return path

def catalog(c, folder):
    result = c.catalog_list(folder)
    require(result.get("contract_version") == 1 and result.get("mode") == "catalog",
            "Choose a registered catalog, not a legacy root.")
    return result

def exact(c, rows, label):
    show(c, rows)
    identifier = input(f"Exact {label} UUID from this list: ").strip()
    matches = [row for row in rows if row["id"] == identifier]
    require(len(matches) == 1, "Selection is not exact.")
    return matches[0]

def select(c, folder, *, scale=False, project=False, placed=False):
    current = catalog(c, folder)
    f = exact(c, current["factories"], "factory")
    s = exact(c, f["scale_sets"], "scale-set") if scale else None
    p = exact(c, f["projects"], "project") if project else None
    if placed:
        require(s is not None and p is not None and any(
            item["scale_set_id"] == s["id"] and item["environment"] == s["environment"]
            for item in p["placements"]), "Project is not placed in that scale.")
    return current, f, s, p

def number(prompt):
    value = input(prompt).strip()
    require(re.fullmatch(r"(?!000)[0-9]{3}", value), "Use 001 through 999.")
    return value

def new_scale(environment=None):
    env = environment or choice("Environment (dev/stage/prod): ", ("dev", "stage", "prod"))
    suffix = number(f"Unused {env} scale suffix: ")
    tenant = UUID(input("Approved existing tenant UUID: ").strip())
    subscription = UUID(input("Approved existing subscription UUID: ").strip())
    require(tenant.int and subscription.int, "Nonzero UUIDs required.")
    route = choice("Orchestrator (ado/gha): ", ("ado", "gha"))
    cidr = str(ipaddress.ip_network(input("Approved non-overlapping VNet CIDR: ").strip()))
    capacity = int(input("Approved project capacity (1 through 8): "))
    require(1 <= capacity <= 8, "Invalid capacity.")
    return {"environment": env, "suffix": suffix, "tenant_id": str(tenant),
            "subscription_id": str(subscription), "orchestrator": route,
            "network": {"vnet_cidr": cidr, "max_projects": capacity}}

def save_review(c, body, preview, operation):
    show(c, body)
    show(c, preview)
    validate_preview(preview)
    if body.get("expected_revision"):
        require(preview.get("source_revision") == body["expected_revision"], "Revision changed.")
    save_json(c, body, f"{operation}-request")
    purpose = ("parameters-confirm" if operation == "parameters" else
               "creation-workflow-start" if operation == "creation-workflow" else "catalog-confirm")
    path = private_directory() / f"{operation}-{uuid4().hex}.receipt.json"
    write_receipt(str(path), client=c, purpose=purpose, operation=operation,
                  request_body=body, preview=preview)
    print("STOP. Review and obtain approval before confirming:", path)
    return path
```

Run a saved scenario with your configured Python interpreter, for example:

```bash
python prepare_factory.py
```

The helper only prepares/saves reviews; it never confirms. Do not concatenate
preparation and confirmation programs into an unattended script.
Keep the separately saved request JSON with its receipt. Parameter receipts
intentionally omit parameter values; review those values in the private request
file as well as the server preview. Do not edit either after review.

## A. New factory, selected environments and project001

Save as **`prepare_factory.py`**. This records own-hub intent, not a complete
VPN/network setup, and does not create a tenant or subscription.

```python
from aif_review import *

c, folder = connect()
before = catalog(c, folder)
require(not before["factories"], "This example needs the approved empty new-factory root.")
environments = [part.strip() for part in input("Selected environments, comma-separated: ").split(",")]
require(environments and len(set(environments)) == len(environments)
        and all(env in ("dev", "stage", "prod") for env in environments), "Select each environment once.")
scales = [new_scale(env) for env in environments]
options = {
    "prefix": input("Approved new prefix: ").strip(),
    "region": input("Approved supported region: ").strip(),
    "factory_key": input("New unique factory key: ").strip(),
    "kind": "ai",
    "aifactory_version": input("Approved registered version, main or supported 125+: ").strip(),
    "scale_sets": scales,
    "initial_project": {
        "number": "001", "display_name": input("Project001 display name: "),
        "placements": [{"environment": s["environment"], "suffix": s["suffix"]} for s in scales],
    },
    "settings": {"enableAIFactoryHub": True, "centralDnsZoneByPolicyInHub": False},
    "expected_revision": before["revision"],
}
body = factory_create_request(folder, **options)
preview = c.factory_create_prepare(folder, **options)
save_review(c, body, preview, "factory-create")
```

**STOP** for separate configuration confirmation. Verify project001's selected
placements afterward; **do not add it again**. Stage/Prod configuration does not
deploy Stage/Prod; Full bootstrap selects an initial Dev target.

### Clone configuration instead

Save as **`prepare_clone.py`**. The new factory has configuration, not deployed
resources/data/models/credentials. Review its network and bindings separately.

```python
from aif_review import *

c, folder = connect()
current, f, _, _ = select(c, folder)
options = {
    "prefix": input("Approved new prefix: ").strip(),
    "region": input("Approved target region: ").strip(),
    "include_projects": choice("Copy project configuration (none/all): ", ("none", "all")),
    "expected_revision": current["revision"],
}
require((options["prefix"], options["region"]) != (f["prefix"], f["region"]), "Choose a new identity.")
body = factory_clone_request(folder, f["id"], **options)
save_review(c, body, c.factory_clone_prepare(folder, f["id"], **options), "factory-clone")
```

## B. Add a scale set, then optionally a project

Save as **`prepare_scale.py`**. This does not deploy VMSS or common resources.

```python
from aif_review import *

c, folder = connect()
current, f, _, _ = select(c, folder)
scale = new_scale()
require(not any((s["environment"], s["suffix"]) == (scale["environment"], scale["suffix"])
                for s in f["scale_sets"]), "Environment/suffix already exists.")
options = {"expected_revision": current["revision"]}
body = scaleset_add_request(folder, f["id"], [scale], **options)
save_review(c, body, c.scaleset_add_prepare(folder, f["id"], [scale], **options), "scaleset-add")
```

**STOP**, approve and confirm the scale configuration first. Then, if needed,
save **`prepare_project.py`** for an independent project change. It reads fresh
IDs itself; no CLI output or previous program variables are needed.

```python
from aif_review import *

c, folder = connect()
current, f, s, _ = select(c, folder, scale=True)
options = {
    "number": number("Unused project number (not project001 already created by A): "),
    "display_name": input("Project display name: "),
    "placements": [{"environment": s["environment"], "scale_set_id": s["id"]}],
    "expected_revision": current["revision"],
}
body = project_add_request(folder, f["id"], **options)
save_review(c, body, c.project_add_prepare(folder, f["id"], **options), "project-add")
```

**STOP** for its own review/confirmation. The server checks project-number
conflicts in selected locations and the layout-2 project home.

## C. Latest successful scale in an explicit environment

Save as **`prepare_auto_project.py`**, **instead of** B's project program for
that project. This requires newer API source; environment-only placement is
not yet in the published baseline. There is no implicit Dev.

```python
from aif_review import *

c, folder = connect()
current, f, _, _ = select(c, folder)
environment = choice("Explicit environment (dev/stage/prod): ", ("dev", "stage", "prod"))
options = {
    "number": number("Unused project number: "),
    "display_name": input("Project display name: "),
    "environments": [environment],
    "expected_revision": current["revision"],
}
body = project_add_request(folder, f["id"], **options)
save_review(c, body, c.project_add_prepare(folder, f["id"], **options), "project-add")
```

**STOP** and review `resolved_placements`, exact scale UUID, completed common
job, version/source commit and `evidence_hash`. The SDK/receipt helpers check
these bindings. Selection requires recorded successful common deployment and
capacity, not the highest suffix or a finished local command.

<details markdown="1">
<summary>More info</summary>

On an API supporting only the explicit selector, deliberately replace
`environments=[environment]` with
`placements=[{"environment": environment, "scale_set_id": "latest-successful"}]`
before preparation. Supply **one**, never both. An older API may return 422;
no automatic fallback is safe. The same options exist on
`project_add_placements_prepare`. Confirmation does not silently change the
resolved scale; no eligible scale means stop, not invent one.

</details>

## D. Add a Stage/Prod placement, not captured promotion

Save as **`prepare_placement.py`**. Executing captured successful Dev
configuration/version through Stage then Prod is **not implemented**. This
saves a target placement only; target parameters and deployment remain separate.

```python
from aif_review import *

c, folder = connect()
current, f, s, p = select(c, folder, scale=True, project=True)
require(s["environment"] in ("stage", "prod"), "Choose the Stage or Prod target.")
require(not any(item["environment"] == s["environment"] for item in p["placements"]),
        "Already placed there; do not move the project implicitly.")
options = {
    "placements": [{"environment": s["environment"], "scale_set_id": s["id"]}],
    "expected_revision": current["revision"],
}
body = project_add_placements_request(folder, f["id"], p["id"], **options)
preview = c.project_add_placements_prepare(folder, f["id"], p["id"], **options)
save_review(c, body, preview, "project-add-placements")
```

**STOP** before confirmation. This does not require Stage success before Prod.
There is no `project_promote` method; a runtime `version_ref` selects code,
not the previous deployment's settings, data, models or success.

## E. Typed parameters and scoped settings

Save as **`prepare_parameters.py`**. Choose a non-secret field from the target's
schema; boolean JSON input becomes Python `True`/`False`, not a string.

```python
from aif_review import *

c, folder = connect()
kind = choice("Parameter scope (common/project): ", ("common", "project"))
current, f, s, p = select(c, folder, scale=True, project=kind == "project", placed=kind == "project")
project_id = p["id"] if p else None
schema = c.catalog_parameters(folder, f["id"], s["id"], project_id)
show(c, schema)
require(not schema["requires_profile_reset"], "A profile reset needs a separate wider review.")
template_name = input("Exact template name from this response: ").strip()
matches = [t for t in schema["templates"] if t["template"] == template_name]
require(len(matches) == 1, "Unknown template.")
field = input("Exact editable field name: ").strip()
require(any(item["name"] == field and not item["sensitive"] for item in matches[0]["fields"]),
        "Choose a listed non-secret field.")
edit = choice("Edit (set/unset): ", ("set", "unset"))
patch = {"template": template_name, "parameters": {}, "unset": []}
if edit == "set":
    patch["parameters"][field] = json.loads(input("Approved JSON value; no secrets: "))
else:
    patch["unset"] = [field]
body = {"contract_version": 1, "folder": folder, "factory_id": f["id"], "scale_set_id": s["id"],
        "expected_revision": schema["source_revision"], "schema_revision": schema["schema_revision"],
        "templates": [patch]}
if project_id:
    body["project_id"] = project_id
save_review(c, body, c.parameter_prepare(body), "parameters")
```

**STOP** for parameter confirmation. `unset` removes an override, not resources;
inherited/default values may apply. A profile reset loses all old protected
parameter settings in that scale, not only those of the selected project.

Save the following **separate scenario** as **`prepare_settings.py`**. It uses
named `catalog_settings_prepare`, not a generic-only placeholder.

```python
from aif_review import *

c, folder = connect()
kind = choice("Settings scope (factory/scale/project): ", ("factory", "scale", "project"))
current, f, s, p = select(c, folder, scale=kind != "factory",
                        project=kind == "project", placed=kind == "project")
scope = {}
if s:
    scope["scale_set_id"] = s["id"]
if p:
    scope["project_id"] = p["id"]
settings = c.catalog_settings(folder, f["id"], **scope)
show(c, settings)
field = input("Exact editable field_key: ").strip()
require(field in settings["field_keys"], "Unknown or locked field.")
value = json.loads(input("Approved non-null scalar JSON replacement; no secrets: "))
require(type(value) in (str, bool, int, float), "Use a non-null scalar, not an object or array.")
changes = {field: value}
options = {**scope, "expected_revision": settings["revision"]}
body = catalog_settings_request(folder, f["id"], changes, **options)
preview = c.catalog_settings_prepare(folder, f["id"], changes, **options)
save_review(c, body, preview, "catalog-settings")
```

**STOP** for catalog confirmation. Omitted fields are unchanged; `null` is not
a general unset. Shared `stage_prod` settings affect both environments.
Neither a settings save nor disabling a flag deletes Azure resources.

## Confirm exactly one approved configuration or runtime receipt

Save as **`confirm_review.py`**, and run separately **after approval**. Choose
the intended operation explicitly. The API key is never printed or persisted.

```python
from aif_review import *

c, folder = connect()
kind = choice("Approved operation (configuration/parameters/runtime): ",
              ("configuration", "parameters", "runtime"))
purpose = "parameters-confirm" if kind == "parameters" else "catalog-confirm"
mode = "runtime" if kind == "runtime" else "configuration"
path = input("Absolute path to the exact reviewed receipt: ").strip()
receipt = load_receipt(path, client=c, purpose=purpose, operation_mode=mode)
require(receipt["folder"] == folder, "Receipt targets another folder.")
show(c, receipt["preview"])
require(input("After approval, paste this confirmation_id: ").strip() == receipt["confirmation_id"],
        "Approval does not match the review.")
if kind == "parameters":
    result = c.parameter_confirm(folder, receipt["confirmation_id"])
else:
    result = c.catalog_confirm(folder, receipt["confirmation_id"])
save_json(c, result, "confirmation-result")
show(c, result)
require(result.get("contract_version") == 1, "Unknown response; inspect state, never resend.")
if mode == "configuration":
    require(isinstance(result.get("catalog"), dict) and result.get("job") is None,
            "Not a configuration-only result; inspect state.")
    show(c, catalog(c, folder))
else:
    job = result.get("job")
    require(isinstance(job, dict), "Missing runtime job; inspect state, never resend.")
    require(all(job.get(key) == receipt["request"].get(key)
                for key in ("factory_id", "scale_set_id", "project_id")), "Unexpected runtime target.")
    print("Observe this job, do not redispatch:", job["id"])
```

Check the readback's exact IDs and changes. Read settings/parameters again
when changed. A transport error may occur after a write took effect; do not
catch it by automatically running this program again.

## Separate runtime deployment and observation

Save as **`prepare_runtime.py`**. Project deployment requires an existing
placement. Common-only deliberately omits `project_id`; it does not mean all
projects. Both require compatible runtime support and a valid pipeline binding.

```python
from aif_review import *

c, folder = connect()
kind = choice("Deployment target (common/project): ", ("common", "project"))
current, f, s, p = select(c, folder, scale=True, project=kind == "project", placed=kind == "project")
version = input("Explicit approved runtime code version/reference: ").strip()
require(bool(version), "Select a version.")
body = {"contract_version": 1, "folder": folder, "action": "deploy", "factory_id": f["id"],
        "scale_set_id": s["id"], "expected_revision": current["revision"], "version_ref": version}
if p:
    body["project_id"] = p["id"]
save_review(c, body, c.review_catalog_prepare(body), "runtime-deploy")
```

**STOP**. Deployment approval is distinct from configuration approval. Only
afterward run `confirm_review.py` with `runtime`. Do not bypass blockers with
legacy/bootstrap calls.

Save **`observe_runtime.py`** to inspect the returned job. This bounded loop
only reads; it does not retry deployment.

```python
import time
from aif_review import *

c, folder = connect()
jobs = c.catalog_jobs(folder)
job = exact(c, jobs["jobs"], "job returned by your confirmation; verify its target")
deadline = time.monotonic() + 300
while True:
    status = c.catalog_job(folder, job["id"])
    require(status.get("id") == job["id"] and all(status.get(k) == job.get(k)
            for k in ("factory_id", "scale_set_id", "project_id")), "Unexpected job scope.")
    show(c, status)
    if status.get("status") not in ("queued", "running"):
        break
    if time.monotonic() >= deadline:
        print("Observation deadline reached; deployment is NOT cancelled.")
        break
    time.sleep(2)
show(c, c.catalog_terminal(folder, job["id"], cursor=0))
```

Check pipeline deployment results, exact target and version before claiming
success. A queued job or completed local process alone is insufficient.

## Registered Full bootstrap

**Conditional/blocked.** Read the [shared bootstrap requirements](#registered-full-bootstrap).
This workflow can create resources/identities/repositories, commit/push and
dispatch pipelines. Save as **`prepare_bootstrap.py`**. Supply a real,
operator-reviewed JSON object matching the live `WorkflowBootstrapConfig`,
not a placeholder or the short settings object from A.

```python
from aif_review import *

c, folder = connect()
show(c, c.creation_capabilities())
save_json(c, c.openapi(), "openapi")
current, f, s, p = select(c, folder, scale=True, project=True, placed=True)
require(s["environment"] == "dev", "Choose the initial Dev bootstrap scope.")
config = read_json("Client-local file containing complete reviewed bootstrap_config: ")
require(all(config.get(k) for k in ("subscription_id", "tenant_id", "scale_set_number",
                                  "repo_root", "team_member_email", "team_group_name")),
        "Missing mandatory bootstrap settings.")
require(all(config.get(k) == value for k, value in {
    "subscription_id": s["subscription_id"], "tenant_id": s["tenant_id"],
    "scale_set_number": s["suffix"], "project_number": p["number"],
}.items()), "Bootstrap settings differ from the saved target.")
scope = {"folder": folder, "factory_id": f["id"], "scale_set_id": s["id"], "project_id": p["id"]}
report = c.preflight({"contract_version": 1, "orchestrator": s["orchestrator"],
                     "scope": scope, "expected_revision": current["revision"], "bootstrap_config": config})
save_json(c, report, "preflight")
show(c, report)
require(report["ready"] is True, "Preflight blocked/incomplete; stop.")
mode = choice("Approval mode (per-stage/whole-workflow): ", ("per-stage", "whole-workflow"))
body = {"contract_version": 1, "operation": "create-factory", "execution_mode": "privileged-bootstrap",
        "creation_mode": "full-bootstrap", "approval_mode": mode, "scope": scope,
        "expected_revision": current["revision"], "bootstrap_config": config}
save_review(c, body, c.creation_workflow_prepare(body), "creation-workflow")
```

**STOP**. Preflight reads provider state but approves nothing; its estimated
cost is not a spending limit. Per-stage mode approves one reviewed stage.
Optional whole-workflow mode needs review of all listed stages, expiry, target,
fingerprints and `authorization_hash`; the receipt helpers validate its
`bounded-full-bootstrap-v1` binding.

Save **`start_bootstrap.py`**, used only after approval:

```python
from aif_review import *

c, folder = connect()
receipt = load_receipt(input("Exact approved workflow receipt path: ").strip(),
                       client=c, purpose="creation-workflow-start")
require(receipt["folder"] == folder, "Different target folder.")
preview = receipt["preview"]
show(c, preview)
require(input("After approval, paste confirmation_id: ").strip() == receipt["confirmation_id"],
        "Approval does not match.")
authorization = preview["review"].get("workflow_authorization")
options = {"authorization_hash": authorization["authorization_hash"]} if authorization else {}
result = c.creation_workflow_start(folder, preview["workflow_id"], receipt["confirmation_id"], **options)
save_json(c, result, "workflow-start")
require(result.get("scope") == preview["scope"] and result.get("workflow_id") == preview["workflow_id"],
        "Unexpected workflow result; inspect state, never resend.")
show(c, c.creation_workflow_status(folder, preview["workflow_id"]))
```

Save **`next_bootstrap.py`** for a per-stage workflow. It reads status before
preparing the next review; it never approves it.

```python
from aif_review import *

c, folder = connect()
workflow_id = input("Exact existing workflow UUID: ").strip()
status = c.creation_workflow_status(folder, workflow_id)
show(c, status)
require(status.get("requires_review") is True, "Server has not requested another review.")
body = {"folder": folder, "workflow_id": workflow_id}
save_review(c, body, c.creation_workflow_next(folder, workflow_id), "creation-workflow")
```

**STOP again** before using `start_bootstrap.py` with the new stage's receipt.
Never write an automatic approval loop.

For bounded whole-workflow approval, save **`continue_bootstrap.py`** and run
it **only when server status says continuation of the existing approval is
safe**. It is not a retry of a running, failed or uncertain stage.

```python
from aif_review import *

c, folder = connect()
receipt = read_json("Original approved whole-workflow receipt: ")
require(receipt.get("format") == "azurefactory-review-receipt-v1"
        and receipt.get("purpose") == "creation-workflow-start"
        and receipt.get("base_url") == c.canonical_base_url and receipt.get("folder") == folder,
        "Different receipt purpose, host or folder.")
require(receipt["request_hash"] == canonical_json_hash(receipt["request"])
        and receipt["preview_hash"] == canonical_json_hash(receipt["preview"]), "Archived review changed.")
preview = receipt["preview"]
authorization = preview["review"].get("workflow_authorization")
require(receipt["request"].get("approval_mode") == "whole-workflow"
        and isinstance(authorization, dict) and authorization["contract"] == "bounded-full-bootstrap-v1"
        and authorization["scope"] == preview["scope"] and preview["scope"]["folder"] == folder
        and authorization["workflow_id"] == preview["workflow_id"], "Not the approved bounded workflow.")
require(authorization["authorization_hash"] == canonical_json_hash(
    {k: v for k, v in authorization.items() if k != "authorization_hash"}), "Approval hash changed.")
require(parse_expires_at(authorization["expires_at"]) > datetime.now(timezone.utc), "Workflow approval expired.")
show(c, c.creation_workflow_status(folder, preview["workflow_id"]))
require(input("After checking safe continuation, type CONTINUE: ") == "CONTINUE", "Stopped.")
result = c.creation_workflow_continue(folder, preview["workflow_id"], authorization["authorization_hash"])
save_json(c, result, "workflow-continue")
show(c, result)
```

Continuation checks the existing **whole-workflow approval's expiry**, not
whether the earlier one-time stage-start preview could still be started.
The server also checks the original approval and current workflow state.

<details markdown="1">
<summary>Alternative and Legacy ways</summary>

There is no `AzureFactoryClient` equivalent for local enrollment provisioning.
Generic `catalog_prepare` can review an operator-produced
`action: "configure-binding"` request; separately approved `catalog_confirm`
saves it, not infrastructure.

For legacy `aifactory` configuration, use
[`ConfigurationDraft.load/review/save`](../../../environment_setup/install_config_wizard/api-usage-examples/python/edit_configuration.py),
preserving `_json_source` and exact saved project identity. Review/save is not
deployment; snapshot-only must be chosen consistently for both.
Legacy runtime methods are `project_deployment_plan`,
`project_deployment_prepare`, separately approved `project_deployment_start`,
and `project_deployment_terminal`. Review deployment contract 2 and
`execution_result`; `submitted` is not Azure success.
Legacy `bootstrap_prepare`, `bootstrap_start`, `bootstrap_job` are different
from registered `creation_workflow_*`, and must not bypass a blocker.
See the [published SDK/API examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md).

</details>

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="REST (curl)">
<summary>REST (curl)</summary>

## Connect with Bash / Git Bash

Prerequisites: **Bash, curl 7.76+** (`--fail-with-body`), **jq 1.6+** and
**sha256sum**. This tab needs no CLI or Python SDK. Use one Bash session; in
Git Bash enter client-local paths in Bash notation, but API-host paths exactly
as the host expects. `read -r` preserves Windows backslashes in those values.

Save the setup/helper block as **`review_helpers.sh`** in your private working
folder and source it. It defines only read/prepare helpers, not confirmation.
There are no redirects or automatic HTTP retries.

```bash
set -euo pipefail
set +x
umask 077
for tool in curl jq sha256sum; do command -v "$tool" >/dev/null; done
read -r -p 'Operator-provided owning API URL: ' API_URL
API_URL=${API_URL%/}
case "$API_URL" in
  http://127.0.0.1:*|http://localhost:*|http://\[::1\]:*|https://*) ;;
  *) printf '%s\n' 'Use the approved loopback HTTP or HTTPS API URL.' >&2; exit 1 ;;
esac
[[ "$API_URL" != *'@'* && "$API_URL" != *'?'* && "$API_URL" != *'#'* ]]
API_KEY=${AIFACTORY_API_KEY:-}
if [[ -z "$API_KEY" ]]; then read -r -s -p 'API key: ' API_KEY; printf '\n'; fi
[[ -n "$API_KEY" ]]
read -r -p 'Exact absolute azurefactory folder ON THE API HOST: ' FOLDER
[[ -n "$FOLDER" ]]
BASE="${LOCALAPPDATA:-${XDG_STATE_HOME:-$HOME/.local/state}}/AzureFactory/reviews"
mkdir -p -- "$BASE"

die() { printf '%s\n' "$*" >&2; return 1; }
digest() { sha256sum -- "$1" | cut -d ' ' -f 1; }
show() {
  jq --arg key "$API_KEY" '
    walk(if type == "object" then
      with_entries(if (.key | test("password|credential|access_token|api_key|client_secret"; "i"))
                   then .value = "[redacted]" else . end)
    elif type == "string" then split($key) | join("[redacted]") else . end)' "$1"
}
get() {
  local endpoint=$1 output=$2 code; shift 2
  [[ ! -e "$output" ]] || { die 'Choose a new response filename.'; return 1; }
  code=$(curl --fail-with-body --silent --show-error --noproxy "*" \
    --get "$API_URL$endpoint" --header "X-API-Key: $API_KEY" \
    "$@" --output "$output" --write-out '%{http_code}') || {
      die "Read failed; inspect private response: $output"; return 1;
    }
  [[ "$code" == 2?? ]] || { die 'Unexpected HTTP status; no redirect followed.'; return 1; }
}
post_prepare() {
  local endpoint=$1 request=$2 output=$3 code
  case "$endpoint" in
    /api/v1/factory-catalog/prepare|/api/v1/factory-catalog/parameters/prepare|\
    /api/v1/creation/preflight|/api/v1/creation/workflows/prepare|\
    /api/v1/creation/workflows/*/prepare-next) ;;
    *) die 'Helper permits read/preparation only.'; return 1 ;;
  esac
  [[ ! -e "$output" ]] || { die 'Refusing to overwrite a response.'; return 1; }
  code=$(curl --fail-with-body --silent --show-error --noproxy "*" \
    --request POST "$API_URL$endpoint" --header "X-API-Key: $API_KEY" \
    --header 'Content-Type: application/json' --data-binary "@$request" \
    --output "$output" --write-out '%{http_code}') || {
      die "Preparation failed; inspect private response: $output"; return 1;
    }
  [[ "$code" == 2?? ]] || { die 'Unexpected status; stop.'; return 1; }
}
new_review() {
  KIND=$1 MODE=$2
  case "$KIND:$MODE" in catalog:configuration|catalog:runtime|parameters:configuration|workflow:workflow) ;;
    *) die 'Unknown review type.'; return 1 ;; esac
  DIR="$BASE/$(date -u +%Y%m%dT%H%M%S)-$$-$RANDOM"
  mkdir -- "$DIR"
  REQUEST="$DIR/request.json"; PREVIEW="$DIR/preview.json"
  printf 'Private review directory: %s\n' "$DIR"
}
read_catalog() {
  get /api/v1/factory-catalog "$DIR/catalog.json" --data-urlencode "folder=$FOLDER"
  jq -e '.contract_version == 1 and .mode == "catalog"' "$DIR/catalog.json" >/dev/null
  REVISION=$(jq -er '.revision' "$DIR/catalog.json")
}
select_factory() {
  read_catalog
  jq '.factories | map({id,key,region,version_ref})' "$DIR/catalog.json"
  read -r -p 'Exact factory UUID: ' FACTORY
  jq -e --arg id "$FACTORY" '.factories | map(select(.id == $id)) |
    if length == 1 then .[0] else error("Select exactly one listed factory") end' \
    "$DIR/catalog.json" > "$DIR/factory.json"
}
select_scale() {
  jq '.scale_sets | map({id,environment,suffix,tenant_id,subscription_id})' "$DIR/factory.json"
  read -r -p 'Exact scale-set UUID: ' SCALE
  jq -e --arg id "$SCALE" '.scale_sets | map(select(.id == $id)) |
    if length == 1 then .[0] else error("Select exactly one listed scale") end' \
    "$DIR/factory.json" > "$DIR/scale.json"
  ENVIRONMENT=$(jq -er '.environment' "$DIR/scale.json")
}
select_project() {
  jq '.projects | map({id,number,display_name,placements})' "$DIR/factory.json"
  read -r -p 'Exact project UUID: ' PROJECT
  jq -e --arg id "$PROJECT" '.projects | map(select(.id == $id)) |
    if length == 1 then .[0] else error("Select exactly one listed project") end' \
    "$DIR/factory.json" > "$DIR/project.json"
}
require_placement() {
  jq -e --arg scale "$SCALE" --arg env "$ENVIRONMENT" \
    'any(.placements[]; .scale_set_id == $scale and .environment == $env)' "$DIR/project.json" >/dev/null
}
new_scale() {
  local output=$1 env=$2 suffix tenant subscription route cidr capacity
  [[ "$env" =~ ^(dev|stage|prod)$ ]]
  read -r -p "Unused $env suffix, 001 through 999: " suffix
  [[ "$suffix" =~ ^[0-9]{3}$ && "$suffix" != 000 ]]
  read -r -p 'Approved existing tenant UUID: ' tenant
  read -r -p 'Approved existing subscription UUID: ' subscription
  read -r -p 'Orchestrator (ado/gha): ' route
  [[ "$route" =~ ^(ado|gha)$ ]]
  read -r -p 'Approved non-overlapping VNet CIDR: ' cidr
  read -r -p 'Approved project capacity (1 through 8): ' capacity
  [[ "$capacity" =~ ^[1-8]$ ]]
  jq -n --arg environment "$env" --arg suffix "$suffix" --arg tenant_id "$tenant" \
    --arg subscription_id "$subscription" --arg orchestrator "$route" \
    --arg cidr "$cidr" --argjson capacity "$capacity" \
    '{$environment,$suffix,$tenant_id,$subscription_id,$orchestrator,
      network:{vnet_cidr:$cidr,max_projects:$capacity}}' > "$output"
}
base_request() {
  jq -n --arg folder "$FOLDER" --arg factory_id "$FACTORY" --arg action "$1" \
    --arg expected_revision "$REVISION" \
    '{contract_version:1,$folder,$factory_id,$action,$expected_revision}'
}
seal_review() {
  jq -n --arg base_url "$API_URL" --arg kind "$KIND" --arg mode "$MODE" \
    --arg request_sha256 "$(digest "$REQUEST")" --arg preview_sha256 "$(digest "$PREVIEW")" \
    '{$base_url,$kind,$mode,$request_sha256,$preview_sha256}' > "$DIR/metadata.json"
}
check_review() {
  [[ "$(jq -er '.base_url' "$DIR/metadata.json")" == "$API_URL" ]]
  [[ "$(jq -er '.request_sha256' "$DIR/metadata.json")" == "$(digest "$REQUEST")" ]]
  [[ "$(jq -er '.preview_sha256' "$DIR/metadata.json")" == "$(digest "$PREVIEW")" ]]
  jq -e --arg phase "${1:-preview}" --slurpfile r "$REQUEST" --slurpfile m "$DIR/metadata.json" '
    def future: sub("\\+00:00$";"Z") | sub("\\.[0-9]+Z$";"Z") | fromdateiso8601 > now;
    . as $p | $r[0] as $b |
    .contract_version == 1 and .can_execute == true and .blockers == [] and
    (.confirmation_id | type == "string" and length > 0) and
    (if $phase == "continue" then $m[0].kind == "workflow" and $b.approval_mode == "whole-workflow"
     else (.expires_at | future) end) and
    (if $m[0].kind == "workflow" then
      (.workflow_id | type == "string" and length > 0) and
      (.source_revision | test("^[a-f0-9]{64}$")) and (.input_hash | test("^[a-f0-9]{64}$")) and
      (if $b.scope then .scope == $b.scope and .source_revision == $b.expected_revision
       else .scope.folder == $b.folder and .workflow_id == $b.workflow_id end) and
      (if $b.approval_mode == "whole-workflow" then
        .review.workflow_authorization as $a |
        $a.contract == "bounded-full-bootstrap-v1" and $a.workflow_id == .workflow_id and
        $a.scope == .scope and $a.source_revision == .source_revision and
        ($a.stages | length > 0) and ($a.expires_at | future) and
        ($a.authorization_hash | test("^[a-f0-9]{64}$")) and
        ($a.program_fingerprint | length > 0) and ($a.template_fingerprint | length > 0)
       else .review.workflow_authorization == null end)
    else
      .operation_mode == $m[0].mode and .source_revision == $b.expected_revision and
      (if $b.factory_id then .target.id == $b.factory_id else true end) and
      (if $b.action == "configure-settings" or $b.action == "deploy" then
        .factory_id == $b.factory_id and .scale_set_id == $b.scale_set_id and .project_id == $b.project_id
       else true end) and
      (if $b.action == "add-project" or $b.action == "add-project-placements" then
        (if $b.action == "add-project" then $b.project.placements else $b.placements end) as $placements |
        [$placements[] | select((.scale_set_id // "latest-successful") == "latest-successful")] as $auto |
        if ($auto | length) == 0 then true else
          (.capabilities | index("latest-successful-placement-v1") != null) and
          (.resolved_placements | length) == ($auto | length) and
          all($auto[]; .environment as $env |
            [$p.resolved_placements[] | select(.environment == $env and .factory_id == $b.factory_id and
              .selector == "latest-successful" and .evidence_kind == "recorded-verified-common-deployment" and
              .version_ref == $p.target.version_ref and (.source_commit | test("^[a-f0-9]{40}$")) and
              (.evidence_hash | test("^[a-f0-9]{64}$")))] | length == 1)
        end
       else true end)
    end)' "$PREVIEW" >/dev/null
}
prepare() {
  local endpoint
  case "$KIND" in
    catalog) endpoint=/api/v1/factory-catalog/prepare ;;
    parameters) endpoint=/api/v1/factory-catalog/parameters/prepare ;;
    workflow) endpoint=/api/v1/creation/workflows/prepare ;;
  esac
  post_prepare "$endpoint" "$REQUEST" "$PREVIEW"
  show "$PREVIEW"
  seal_review
  check_review
  printf 'STOP. Review and obtain approval. Keep this directory: %s\n' "$DIR"
}
```

In your Bash shell:

```bash
source ./review_helpers.sh
```

Requests are created with `jq -n`/`--arg`/`--argjson`, never interpolated JSON
strings. These local SHA-256 checks tie unchanged request and preview files to
the host; they are **not** the server's canonical `input_hash` or a signature.
Keep server hashes untouched. The server revalidates its saved request, owner,
revision, expiry, target and one-time confirmation.

## A. New factory, selected environments and project001

Run one scenario at a time. This saves selected scale sets and owned-hub
intent; it does not supply the complete VPN/network/bootstrap configuration.

```bash
new_review catalog configuration
read_catalog
jq -e '.factories | length == 0' "$DIR/catalog.json" >/dev/null
read -r -p 'New unique factory key: ' FACTORY_KEY
read -r -p 'Approved new prefix: ' PREFIX
read -r -p 'Approved supported region: ' REGION
read -r -p 'Approved registered version, main or supported 125+: ' VERSION
read -r -p 'Selected environments separated by spaces, e.g. dev stage: ' ENVIRONMENTS
read -r -a ENV_LIST <<< "$ENVIRONMENTS"
[[ ${#ENV_LIST[@]} -gt 0 ]]
for env in "${ENV_LIST[@]}"; do
  [[ "$env" =~ ^(dev|stage|prod)$ ]]
  [[ ! -e "$DIR/scale-$env.json" ]] || { die 'Select each environment once.'; exit 1; }
  new_scale "$DIR/scale-$env.json" "$env"
done
jq -s '.' "$DIR"/scale-*.json > "$DIR/scales.json"
read -r -p 'Project001 display name: ' NAME
jq -n --arg folder "$FOLDER" --arg expected_revision "$REVISION" --arg factory_key "$FACTORY_KEY" \
  --arg target_prefix "$PREFIX" --arg target_region "$REGION" --arg aifactory_version "$VERSION" \
  --arg name "$NAME" --slurpfile scales "$DIR/scales.json" \
  '{contract_version:1,$folder,action:"create-factory",$expected_revision,factory_kind:"ai",
    $factory_key,$target_prefix,$target_region,$aifactory_version,scale_sets:$scales[0],
    initial_project:{number:"001",display_name:$name,
      placements:[$scales[0][] | {environment,suffix}]},
    settings:{enableAIFactoryHub:true,centralDnsZoneByPolicyInHub:false}}' > "$REQUEST"
prepare
```

**STOP** and use the separate confirmation block after configuration approval.
Verify project001 and each selected placement; **do not add project001 again**.
Saving Stage/Prod configuration or named GitHub environments does not deploy
Stage/Prod. No tenant/subscription is created here.

### Clone configuration instead

```bash
new_review catalog configuration
select_factory
read -r -p 'Approved new prefix: ' PREFIX
read -r -p 'Approved target region: ' REGION
read -r -p 'Copy project configuration (none/all): ' INCLUDE
[[ "$INCLUDE" =~ ^(none|all)$ ]]
jq -e --arg prefix "$PREFIX" --arg region "$REGION" \
  '.prefix != $prefix or .region != $region' "$DIR/factory.json" >/dev/null
base_request clone | jq --arg target_prefix "$PREFIX" --arg target_region "$REGION" \
  --arg include_projects "$INCLUDE" '. + {$target_prefix,$target_region,$include_projects}' > "$REQUEST"
prepare
```

**STOP** for separate confirmation. Cloning copies configuration, not deployed
resources, data, models or credentials. Review new IDs, networking and bindings.

## B. Add a scale set and optionally a project

```bash
new_review catalog configuration
select_factory
read -r -p 'New scale environment (dev/stage/prod): ' ENVIRONMENT
new_scale "$DIR/new-scale.json" "$ENVIRONMENT"
jq -e --slurpfile s "$DIR/new-scale.json" \
  'all(.scale_sets[]; .environment != $s[0].environment or .suffix != $s[0].suffix)' \
  "$DIR/factory.json" >/dev/null
base_request create-scale-set | jq --slurpfile s "$DIR/new-scale.json" '. + {scale_sets:$s}' > "$REQUEST"
prepare
```

**STOP**, approve and confirm the scale configuration first. It does not
deploy VMSS or common resources. Then independently add a different project:

```bash
new_review catalog configuration
select_factory
select_scale
read -r -p 'Unused project number (not project001 already created by A): ' NUMBER
[[ "$NUMBER" =~ ^[0-9]{3}$ && "$NUMBER" != 000 ]]
read -r -p 'Project display name: ' NAME
base_request add-project | jq --arg number "$NUMBER" --arg display_name "$NAME" \
  --arg environment "$ENVIRONMENT" --arg scale_set_id "$SCALE" \
  '. + {project:{$number,$display_name,placements:[{$environment,$scale_set_id}]}}' > "$REQUEST"
prepare
```

**STOP** for its own confirmation. The API validates number conflicts at the
chosen placements and layout-2 project home.

## C. Latest successful scale in an explicit environment

This replaces B's project request; do not add the same project twice.
Environment-only placement needs **newer API source, not yet the published
baseline**. No environment is guessed.

```bash
new_review catalog configuration
select_factory
read -r -p 'Explicit environment (dev/stage/prod): ' ENVIRONMENT
[[ "$ENVIRONMENT" =~ ^(dev|stage|prod)$ ]]
read -r -p 'Unused project number: ' NUMBER
[[ "$NUMBER" =~ ^[0-9]{3}$ && "$NUMBER" != 000 ]]
read -r -p 'Project display name: ' NAME
base_request add-project | jq --arg number "$NUMBER" --arg display_name "$NAME" \
  --arg environment "$ENVIRONMENT" \
  '. + {project:{$number,$display_name,placements:[{$environment}]}}' > "$REQUEST"
prepare
```

**STOP**. Inspect the resolved UUID, tenant/subscription, source commit,
completed job and `evidence_hash`, and check the project placement in `target`.
The service selects from recorded successful **common** deployments for this
factory/environment/version with capacity, not by highest suffix.

<details markdown="1">
<summary>More info</summary>

For an API supporting only the explicit selector, deliberately construct
`placements:[{$environment,scale_set_id:"latest-successful"}]` instead, before
preparing. An older host can return HTTP 422; do not switch selectors as an
automatic retry. The same placement objects are top-level for
`add-project-placements`, nested in `project` for `add-project`. No eligible
scale means stop; confirmation never silently substitutes another scale.

</details>

## D. Stage/Prod placement, not captured promotion

Executing a captured successful Dev configuration/version through Stage and
Prod is **not implemented**. Save an explicit target placement, then review
target parameters and deployment separately.

```bash
new_review catalog configuration
select_factory
select_scale
select_project
[[ "$ENVIRONMENT" =~ ^(stage|prod)$ ]]
jq -e --arg env "$ENVIRONMENT" 'all(.placements[]; .environment != $env)' "$DIR/project.json" >/dev/null
base_request add-project-placements | jq --arg project_id "$PROJECT" \
  --arg environment "$ENVIRONMENT" --arg scale_set_id "$SCALE" \
  '. + {$project_id,placements:[{$environment,$scale_set_id}]}' > "$REQUEST"
prepare
```

**STOP** for confirmation. Prod needs a separate target review; this does not
require Stage success. `version_ref` chooses code, not captured settings,
data, models or success.

## E. Typed parameters and scoped settings

This parameter example targets a placed project; for common-only parameters,
omit project selection and `project_id` from the read/request.

```bash
new_review parameters configuration
select_factory
select_scale
select_project
require_placement
get /api/v1/factory-catalog/parameters "$DIR/parameters.json" \
  --data-urlencode "folder=$FOLDER" --data-urlencode "factory_id=$FACTORY" \
  --data-urlencode "scale_set_id=$SCALE" --data-urlencode "project_id=$PROJECT"
show "$DIR/parameters.json"
jq -e '.requires_profile_reset == false' "$DIR/parameters.json" >/dev/null
read -r -p 'Exact template name from the response: ' TEMPLATE
read -r -p 'Exact non-secret field name: ' FIELD
jq -e --arg t "$TEMPLATE" --arg f "$FIELD" \
  '[.templates[] | select(.template == $t) | .fields[] | select(.name == $f and .sensitive == false)] |
   length == 1' "$DIR/parameters.json" >/dev/null
read -r -p 'Edit (set/unset): ' EDIT
[[ "$EDIT" =~ ^(set|unset)$ ]]
VALUE=null
if [[ "$EDIT" == set ]]; then read -r -p 'Approved JSON value; no secrets: ' VALUE; fi
jq -n --arg folder "$FOLDER" --arg factory_id "$FACTORY" --arg scale_set_id "$SCALE" \
  --arg project_id "$PROJECT" --slurpfile schema "$DIR/parameters.json" \
  --arg template "$TEMPLATE" --arg field "$FIELD" --arg edit "$EDIT" --argjson value "$VALUE" \
  '{contract_version:1,$folder,$factory_id,$scale_set_id,$project_id,
    expected_revision:$schema[0].source_revision,schema_revision:$schema[0].schema_revision,
    templates:[{template:$template,
      parameters:(if $edit == "set" then {($field):$value} else {} end),
      unset:(if $edit == "unset" then [$field] else [] end)}]}' > "$REQUEST"
prepare
```

**STOP** for parameter confirmation. `unset` removes an override, not a
resource; inherited/default values may apply. Do not reset the entire
scale-set parameter profile just to bypass an error.

For a scale-level settings replacement, use this separate scenario:

```bash
new_review catalog configuration
select_factory
select_scale
get /api/v1/factory-catalog/settings "$DIR/settings.json" \
  --data-urlencode "folder=$FOLDER" --data-urlencode "factory_id=$FACTORY" --data-urlencode "scale_set_id=$SCALE"
show "$DIR/settings.json"
read -r -p 'Exact editable field_key: ' FIELD
jq -e --arg f "$FIELD" '.field_keys | index($f) != null' "$DIR/settings.json" >/dev/null
read -r -p 'Approved non-null scalar JSON replacement; no secrets: ' VALUE
jq -en --argjson value "$VALUE" '$value | type | . == "string" or . == "number" or . == "boolean"' >/dev/null
REVISION=$(jq -er '.revision' "$DIR/settings.json")
base_request configure-settings | jq --arg scale_set_id "$SCALE" --arg field "$FIELD" --argjson value "$VALUE" \
  '. + {$scale_set_id,settings:{($field):$value}}' > "$REQUEST"
prepare
```

**STOP** before catalog confirmation. For factory scope omit `scale_set_id`
from both read and request; for project scope select a placed project and add
its `project_id` to both. Omitted settings stay unchanged; `null` is not a
general unset. Shared `stage_prod` settings affect both Stage and Prod.
Disabling a flag does not delete resources.

## Confirm one approved review — never automatically

This block supports the catalog/parameters scenarios and registered workflow
reviews below. It requires the saved directory, unchanged files and explicit
matching approval. **Plain REST previews are not CLI/SDK receipt files.**
In a new shell, source the setup again, using the **same owning API and key**.

```bash
read -r -p 'Private directory containing the exact reviewed request, preview and metadata: ' DIR
REQUEST="$DIR/request.json"; PREVIEW="$DIR/preview.json"
KIND=$(jq -er '.kind' "$DIR/metadata.json")
MODE=$(jq -er '.mode' "$DIR/metadata.json")
check_review
show "$REQUEST"
show "$PREVIEW"
read -r -p 'After reviewing and obtaining approval, paste this confirmation_id: ' APPROVED
[[ "$APPROVED" == "$(jq -er '.confirmation_id' "$PREVIEW")" ]]
[[ ! -e "$DIR/confirmation-attempted" ]] || { die 'A write was already attempted. Inspect state; do not resend.'; exit 1; }
case "$KIND:$MODE" in
  catalog:configuration|catalog:runtime|parameters:configuration)
    ENDPOINT=/api/v1/factory-catalog/confirm
    [[ "$KIND" != parameters ]] || ENDPOINT=/api/v1/factory-catalog/parameters/confirm
    jq -n --slurpfile r "$REQUEST" --arg confirmation_id "$APPROVED" \
      '{contract_version:1,folder:$r[0].folder,$confirmation_id}' > "$DIR/confirm.json"
    ;;
  workflow:workflow)
    ENDPOINT=/api/v1/creation/workflows/start
    jq -n --slurpfile p "$PREVIEW" --arg confirmation_id "$APPROVED" \
      '{folder:$p[0].scope.folder,workflow_id:$p[0].workflow_id,$confirmation_id} +
       (if $p[0].review.workflow_authorization then
         {authorization_hash:$p[0].review.workflow_authorization.authorization_hash} else {} end)' > "$DIR/confirm.json"
    ;;
  *) die 'Wrong review kind/mode.'; exit 1 ;;
esac
(set -o noclobber; printf '%s\n' 'Inspect server state before any further write.' > "$DIR/confirmation-attempted")
CODE=$(curl --fail-with-body --silent --show-error --noproxy "*" \
  --request POST "$API_URL$ENDPOINT" --header "X-API-Key: $API_KEY" \
  --header 'Content-Type: application/json' --data-binary "@$DIR/confirm.json" \
  --output "$DIR/result.json" --write-out '%{http_code}') || {
    die 'Failed/uncertain confirmation. Inspect server state, do not resend.'; exit 1;
  }
[[ "$CODE" == 2?? ]] || { die 'Unexpected response. Inspect state, do not resend.'; exit 1; }
show "$DIR/result.json"
if [[ "$KIND" == workflow ]]; then
  jq -e --slurpfile p "$PREVIEW" '.contract_version == 1 and
    .workflow_id == $p[0].workflow_id and .scope == $p[0].scope' "$DIR/result.json" >/dev/null
elif [[ "$MODE" == configuration ]]; then
  jq -e '.contract_version == 1 and (.catalog | type == "object") and .job == null' "$DIR/result.json" >/dev/null
  FOLDER=$(jq -er '.folder' "$REQUEST")
  get /api/v1/factory-catalog "$DIR/readback.json" --data-urlencode "folder=$FOLDER"
  show "$DIR/readback.json"
else
  jq -e --slurpfile r "$REQUEST" '.contract_version == 1 and (.job | type == "object") and
    .job.factory_id == $r[0].factory_id and .job.scale_set_id == $r[0].scale_set_id and
    .job.project_id == $r[0].project_id' "$DIR/result.json" >/dev/null
fi
```

Verify saved IDs and changes in readback, and re-read settings/parameters when
changed. Any unexpected response means inspect state, **not repeat the write**.

## Separate runtime deployment

Choose common-only or a placed project. Omitting a project does **not** deploy
every project. Common-only/GHA/shared-remote routes need compatible runtime
support; do not change routes to bypass a blocker.

```bash
new_review catalog runtime
select_factory
select_scale
read -r -p 'Deployment target (common/project): ' TARGET
[[ "$TARGET" =~ ^(common|project)$ ]]
PROJECT=''
if [[ "$TARGET" == project ]]; then select_project; require_placement; fi
read -r -p 'Explicit approved runtime code version/reference: ' VERSION
[[ -n "$VERSION" ]]
base_request deploy | jq --arg scale_set_id "$SCALE" --arg project "$PROJECT" --arg version_ref "$VERSION" \
  '. + {$scale_set_id,$version_ref} + (if $project != "" then {project_id:$project} else {} end)' > "$REQUEST"
prepare
```

**STOP** for distinct deployment approval before using the confirmation block.
After confirmation, with `DIR` still pointing to that runtime review:

```bash
FOLDER=$(jq -er '.folder' "$REQUEST")
JOB=$(jq -er '.job.id' "$DIR/result.json")
[[ "$JOB" =~ ^[a-f0-9-]{36}$ ]]
STATUS="$DIR/job-$(date -u +%Y%m%dT%H%M%S)-$RANDOM.json"
get "/api/v1/factory-catalog/jobs/$JOB" "$STATUS" --data-urlencode "folder=$FOLDER"
show "$STATUS"
jq -e --slurpfile r "$REQUEST" --arg id "$JOB" '.id == $id and
  .factory_id == $r[0].factory_id and .scale_set_id == $r[0].scale_set_id and
  .project_id == $r[0].project_id' "$STATUS" >/dev/null
TERMINAL="$DIR/terminal-$(date -u +%Y%m%dT%H%M%S)-$RANDOM.json"
get /api/v1/factory-catalog/terminal "$TERMINAL" --data-urlencode "folder=$FOLDER" \
  --data-urlencode "job_id=$JOB" --data-urlencode 'cursor=0'
show "$TERMINAL"
```

Repeat only these **GETs** as needed, using the returned terminal cursor for
later output. Check pipeline results, exact version and target, not merely a
queued job or completed local command. A timeout is not cancellation.

## Registered Full bootstrap

**Conditional/blocked**: first read the [shared requirements](#registered-full-bootstrap).
This can provision resources, identities, networks, runners and repositories,
publish Git changes and start pipelines. Supply complete reviewed configuration,
not A's short settings object.

```bash
new_review workflow workflow
get /api/v1/creation/capabilities "$DIR/capabilities.json"
get /openapi.json "$DIR/openapi.json"
show "$DIR/capabilities.json"
select_factory
select_scale
select_project
require_placement
[[ "$ENVIRONMENT" == dev ]]
read -r -p 'Existing client-local JSON file containing complete reviewed bootstrap_config: ' CONFIG
jq -e --slurpfile s "$DIR/scale.json" --slurpfile p "$DIR/project.json" '
  .subscription_id == $s[0].subscription_id and .tenant_id == $s[0].tenant_id and
  .scale_set_number == $s[0].suffix and .project_number == $p[0].number and
  ([.repo_root,.team_member_email,.team_group_name] | all(.[]; type == "string" and length > 0))' "$CONFIG" >/dev/null
read -r -p 'Approval mode (per-stage/whole-workflow): ' APPROVAL_MODE
[[ "$APPROVAL_MODE" =~ ^(per-stage|whole-workflow)$ ]]
jq -n --arg folder "$FOLDER" --arg factory_id "$FACTORY" --arg scale_set_id "$SCALE" \
  --arg project_id "$PROJECT" --arg expected_revision "$REVISION" --arg approval_mode "$APPROVAL_MODE" \
  --slurpfile config "$CONFIG" \
  '{contract_version:1,operation:"create-factory",execution_mode:"privileged-bootstrap",
    creation_mode:"full-bootstrap",$approval_mode,$expected_revision,
    scope:{$folder,$factory_id,$scale_set_id,$project_id},bootstrap_config:$config[0]}' > "$REQUEST"
jq --slurpfile s "$DIR/scale.json" \
  '{contract_version,scope,expected_revision,bootstrap_config,orchestrator:$s[0].orchestrator}' \
  "$REQUEST" > "$DIR/preflight-request.json"
post_prepare /api/v1/creation/preflight "$DIR/preflight-request.json" "$DIR/preflight.json"
show "$DIR/preflight.json"
jq -e '.contract_version == 1 and .kind == "deployment-preflight" and .read_only == true and
  .authorization == false and .ready == true and .status == "ready"' "$DIR/preflight.json" >/dev/null
prepare
```

**STOP**. Preflight reads provider state; it approves no deployment. Cost
estimates are not spending limits. In per-stage mode review the current stage.
In optional whole-workflow mode review all listed stages, scope, fingerprints,
expiry and `authorization_hash`. Then use the separate confirmation block,
which sends the strict workflow-start body **without** catalog-only fields.

Read workflow status after start, or later from its saved review directory:

```bash
WORKFLOW=$(jq -er '.workflow_id' "$PREVIEW")
FOLDER=$(jq -er '.scope.folder' "$PREVIEW")
[[ "$WORKFLOW" =~ ^[a-f0-9-]{36}$ ]]
STATUS="$DIR/workflow-status-$(date -u +%Y%m%dT%H%M%S)-$RANDOM.json"
get "/api/v1/creation/workflows/$WORKFLOW" "$STATUS" --data-urlencode "folder=$FOLDER"
show "$STATUS"
jq -e --slurpfile p "$PREVIEW" '.workflow_id == $p[0].workflow_id and .scope == $p[0].scope' "$STATUS" >/dev/null
```

For per-stage mode **only when status reports `requires_review: true`**,
prepare another review:

```bash
jq -e '.requires_review == true' "$STATUS" >/dev/null
new_review workflow workflow
jq -n --arg folder "$FOLDER" --arg workflow_id "$WORKFLOW" '{$folder,$workflow_id}' > "$REQUEST"
jq '{folder}' "$REQUEST" > "$DIR/next-body.json"
post_prepare "/api/v1/creation/workflows/$WORKFLOW/prepare-next" "$DIR/next-body.json" "$PREVIEW"
seal_review
check_review
show "$PREVIEW"
printf 'STOP. Review the new stage before confirmation: %s\n' "$DIR"
```

**STOP again** before using the confirmation block. The local request records
the workflow ID for review; the strict `/prepare-next` body sends only `folder`.
Do not automate stage approvals.

For bounded whole-workflow mode, resume **only if the server reports safe
continuation of the existing approval**. Use the original review directory;
this is not a retry of a running, failed or uncertain stage.

```bash
read -r -p 'Original approved whole-workflow review directory: ' DIR
REQUEST="$DIR/request.json"; PREVIEW="$DIR/preview.json"
check_review continue
jq -e '.approval_mode == "whole-workflow"' "$REQUEST" >/dev/null
WORKFLOW=$(jq -er '.workflow_id' "$PREVIEW")
FOLDER=$(jq -er '.scope.folder' "$PREVIEW")
STATUS="$DIR/before-continue-$(date -u +%Y%m%dT%H%M%S)-$RANDOM.json"
get "/api/v1/creation/workflows/$WORKFLOW" "$STATUS" --data-urlencode "folder=$FOLDER"
show "$STATUS"
read -r -p 'After checking safe continuation, type CONTINUE: ' ANSWER
[[ "$ANSWER" == CONTINUE ]]
[[ ! -e "$DIR/continue-attempted" ]] || { die 'Inspect the earlier continuation outcome; do not resend.'; exit 1; }
jq '{folder:.scope.folder,authorization_hash:.review.workflow_authorization.authorization_hash}' \
  "$PREVIEW" > "$DIR/continue.json"
(set -o noclobber; printf '%s\n' 'Inspect server state before another write.' > "$DIR/continue-attempted")
CODE=$(curl --fail-with-body --silent --show-error --noproxy "*" \
  --request POST "$API_URL/api/v1/creation/workflows/$WORKFLOW/continue" \
  --header "X-API-Key: $API_KEY" --header 'Content-Type: application/json' \
  --data-binary "@$DIR/continue.json" --output "$DIR/continue-result.json" --write-out '%{http_code}') || {
    die 'Failed/uncertain continuation; inspect state, do not repeat.'; exit 1;
  }
[[ "$CODE" == 2?? ]]
show "$DIR/continue-result.json"
```

<details markdown="1">
<summary>Alternative and Legacy ways</summary>

There is no REST equivalent for local enrollment provisioning. An approved
binding candidate can use generic catalog `action: "configure-binding"`,
then its own catalog review/confirmation; that only saves the connection.

Legacy configuration uses `/api/v1/projects/load` with exact folder/project,
`/api/v1/validation`, then `/api/v1/export` without a destination for review.
Separately approved `/api/v1/projects/save` saves configuration, not deployment.
Preserve `_json_source`; `/startup/load` is only a hint.
Legacy deployment uses `/api/v1/operations/project-deployments/plan`,
`/prepare`, separately approved `/start`, then `/terminal`. It requires
deployment contract 2; `submitted` is local launcher completion, not Azure
success. Older launcher bootstrap uses `/api/v1/creation/bootstrap/*`,
not `/api/v1/creation/workflows/*`. Neither route bypasses registered blockers.
See the [published API examples and contracts](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md).

</details>

</details>
<!-- /factory-tool -->

<a id="registered-full-bootstrap"></a>

## Full bootstrap requirements

Registered Full bootstrap deploys its selected initial **Dev** target. Saving
Stage/Prod configurations is not a three-environment deployment. Start from the
already saved factory; do not recreate it. Local checks and preflight cannot
guarantee Azure permissions, networking or eventual success.

For an **owned integrated hub/VPN**, review `setup_hub_access: true`,
`access_hub_mode: "integrated"`, Dev VNet CIDR, `vpn_client_cidr`, network/DNS
ownership, region/subscription, project001, repository, identity and runner.
Integrated mode does not need an invented second hub VNet; external hub is
different. **This does not install a VPN client or verify workstation access.**
Hosted runners still need suitable private-network connectivity.

<details markdown="1">
<summary>More info</summary>

Read `bootstrap_fields` and `BootstrapConfig` / `WorkflowBootstrapConfig` /
`CreationWorkflowPrepare` in the **live** capabilities/OpenAPI. Required settings
include `subscription_id`, `tenant_id`, `scale_set_number`, `repo_root`,
`team_member_email`, `team_group_name`. An existing group ID does not remove
required team name/email fields. GHA needs its repository details; ADO needs its
organization/project/repository/service connection and connected tenant.

Choose `coordination_mode` deliberately. `single-writer` needs a private
repository and an administrator-approved exclusive-writer arrangement; `blob`
has additional coordination/network requirements. Do not change an existing
binding's mode to bypass a blocker. `review.workflow_authorization` uses
`bounded-full-bootstrap-v1`; changed inputs, expiry, failure or uncertainty
require stopping to inspect the state. No automatic approval/retry loops.

The limited DeveloperBastion handoff in API source `3c5694c` uses deployment
receipts and verified runner associations. It **does not unblock Full bootstrap**.
The native prerequisite handoff supplies `verified_observations_hash`, not concrete
post-success resource bodies. Unproven DNS, gateway, service association links
(SAL) and additional Bastion fields remain blocked. This does not change a frozen
runtime source pin or certify an installed host.

</details>

<a id="c-explicit-latest-successful-placement"></a>
<a id="catalog-settings--generic-access-only"></a>

<details markdown="1">
<summary>More info</summary>

The historical settings anchor above is retained for links; scoped settings now
have named CLI/SDK preparation and typed receipts. Other advanced actions remain
**generic-access only**, with separately reviewed prepare/confirm:

| Action / endpoint | Boundary |
|---|---|
| `migrate` | Register a legacy root or copy it to a separate empty modern `folder` using `source_folder`. Preserve UUIDs/source files. Never allow both copies to independently modify the same Azure targets. Registration does not prove ownership of existing resources. |
| `correct-draft-scale-identity` | Exact factory/scale IDs, revision and `draft_identity` tenant/subscription UUIDs. Eligible empty drafts only; bindings, ownership, placements or previous execution block it. This does not move resources. |
| `configure-binding` | Exact factory and typed `RuntimeBinding`; review repository, runner, identity, roles and coordination settings. Saving a connection is not deployment. |
| `/api/v1/creation/prepare` and separately `/confirm` | Registered creation API, not the legacy bootstrap launcher. Use live schemas rather than inventing a friendly wrapper or receipt operation. |

Generic catalog actions use `/api/v1/factory-catalog/prepare` then separately
approved `/confirm`. Follow the [published factory scope contract](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/docs/API.md)
and installed OpenAPI. Never pass a plain preview as a typed SDK/CLI receipt.
Catalog reads use `revision`; parameter reads/previews use `source_revision`.

</details>

## APIM, Kong, MCP/AI Gateway and Application Gateway

**Not implemented:** a unified deployment choice between APIM and Kong.
For existing APIM settings, use only the chosen version's published parameter
schema. There is no `gateway_deploy` SDK method or invented gateway CLI option.

**Conditional/blocked:** newer source has optional ADO/GHA component pipeline
support for **project001 Dev**: host the read-only Factory MCP, create/adopt an
AI Gateway and register its MCP tool server, given required images, identity and
private networking. Saving flags changes configuration only. An approved pipeline
run is separate; setting a flag to false skips a step, **not resource deletion**.

<details markdown="1">
<summary>More info</summary>

| JSON/YAML setting (default disabled) | GHA environment name |
|---|---|
| `enableAIFactoryMCP` | `ENABLE_AI_FACTORY_MCP` |
| `enableAIGatewaySKU` | `ENABLE_AI_GATEWAY_SKU` |
| `addAIFactoryMCP2AIGatewaySKU` | `ADD_AI_FACTORY_MCP_2_AI_GATEWAY_SKU` |

Accelerator `81ec23d6` added configuration-only flags; `cf8437af` added the component
pipeline support. API `08b17ce` adds corresponding partial support, not universal
host/runtime parity or Kong selection. The old "no pipeline bindings" statement
does not apply to main after `cf8437af`. See the
[component contract](https://github.com/jostrm/azure-enterprise-scale-ml/blob/cf8437af/usecase_code/40-agent-factory/45-aifactory-mcp-gateway/readme.md)
and [options reference](https://github.com/jostrm/azure-enterprise-scale-ml/blob/cf8437af/environment_setup/azurefactory-cli/readme.md#mcp--ai-gateway-options-project001-dev).
If a flag is missing from the live `field_keys`/parameter schema, do not force it.

**Azure Application Gateway is different.** Creation input
`enable_application_gateway` exists, but its registered workflow deployment is
blocked/unimplemented. Accepting an input does not implement its deployment.

</details>

## Agent Factory chat and live voice

**Conditional/blocked:** two optional project-pipeline steps run in the foundry phase. `enableFactoryChatAgent`
creates or updates the owned Foundry prompt agent. With `enableAIFactoryAgentLiveVoice` **also** set, a second step
deploys the private chat web application with Azure Voice Live for **project001 Dev**, given an Entra registration,
reader object IDs, an internal Container Apps environment and a succeeded model deployment. Saving flags changes
configuration only. An approved pipeline run is separate; `false` skips a step, **not resource deletion**.

<details markdown="1">
<summary>More info</summary>

| JSON/YAML setting (default disabled) | GHA environment name |
|---|---|
| `enableFactoryChatAgent` | `ENABLE_FACTORY_CHAT_AGENT` |
| `enableAIFactoryAgentLiveVoice` | `ENABLE_AI_FACTORY_AGENT_LIVE_VOICE` |

Inputs (default empty): `aifactoryAgentEntraAppId`, `aifactoryAgentReaderObjectIds`,
`aifactoryAgentContainerAppsEnvironment`, `aifactoryAgentVoiceName`, `aifactoryAgentVoiceLanguages`
(GHA `AIFACTORY_AGENT_ENTRA_APP_ID`, `AIFACTORY_AGENT_READER_OBJECT_IDS`,
`AIFACTORY_AGENT_CONTAINER_APPS_ENVIRONMENT`, `AIFACTORY_AGENT_VOICE_NAME`, `AIFACTORY_AGENT_VOICE_LANGUAGES`).
Voice without the chat flag fails loudly. The step never replaces an app deployed by hand; use the operator flow
for that. See [chapter 21 — Agent Factory chat and live voice](21-agent-factory-chat.md) and the
[options reference](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/azurefactory-cli/readme.md#ai-factory-agent-live-voice-options-project001-dev).
If a flag is missing from the live `field_keys`/parameter schema, do not force it.

</details>

<a id="evidence-version-boundaries-and-validation"></a>

<details markdown="1">
<summary>More info</summary>

The named helpers and receipts here were checked against accelerator main-based
source `300234cd`, including the earlier `0da0d85b` helper changes. Environment-only
placement requires newer API source and is not yet the published API default;
older APIs may return 422. Captured-project backend capture/review is in progress,
not published executable promotion. Selected immutable runtimes, API builds and
installed SDK packages can differ; check the actual host before proceeding.

References:

- [Canonical CLI/SDK reference](../../../environment_setup/azurefactory-cli/readme.md),
  [client](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py),
  [request builders](../../../environment_setup/azurefactory-cli/src/azurefactory/catalog_requests.py),
  [receipt validation](../../../environment_setup/azurefactory-cli/src/azurefactory/review.py),
  [CLI tests](../../../environment_setup/azurefactory-cli/tests).
- [Published API examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md)
  and [API baseline contract](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/docs/API.md).

Offline syntax/model checks validate the examples' shape, not real customer
values, installed features, permissions, networks or deployment outcomes.
No installation, Azure operation, pipeline dispatch, source-pin change, commit
or push is part of preparing this documentation.

</details>

For removing resources, preserving shared hub/VPN resources or recovering from
uncertainty, continue with [20 — removal and recovery](20-cli-and-api-and-usage.md).

---

[Next - 20. Remove, observe and recover](20-cli-and-api-and-usage.md)
