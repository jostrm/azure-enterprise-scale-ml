# 19. Add and update: choose the intent, then the interface

Start with [18 — connection, smoke checks and routing](18-cli-and-api-and-usage.md).
For removal and uncertain outcomes, use
[20 — removal and recovery](20-cli-and-api-and-usage.md).
Decide first between
[file-first variables.json editing and wrapper-first operations](18-cli-and-api-and-usage.md#choose-how-to-author-configuration-file-first-or-wrapper-first).
This chapter follows the wrapper-first path; hand-authored request/patch JSON
is supported input, not a manual edit of registered catalog projections.
[17 — earlier overview](17-cli-and-api-and-usage.md) remains historical context;
its shorthand about promotion or completion is **not** a promotion/success contract.

**Saved configuration is not deployed infrastructure.** A successful configuration
confirmation returns a catalog and `job: null`. Runtime preparation is another
review; runtime confirmation can create billable resources, publish Git changes
and dispatch provider pipelines. Neither HTTP acceptance nor local process exit
proves Azure deployment.

## Choose the intent

These labels describe the inspected source, **not certification of your installed
CLI/API or selected published runtime**. Run guide 18's compatibility checks
against the actual host; keep a blocked operation blocked.

| Scenario / intent | Support and boundary |
|---|---|
| **A. New AI factory, own hub/VPN, project001, selected Dev/Stage/Prod** | **implemented**: configuration for explicit selected scale sets and one initial project. **conditional/blocked**: actual owned hub/VPN and workload provisioning require the separately reviewed registered bootstrap/runtime route and complete networking inputs. The short catalog request below is deliberately only partial configuration, not a full hub deployment recipe. |
| **B. Add an AI Factory scale set** | **implemented**: `scaleset add` saves configuration, with separate project placement and runtime reviews. An AI Factory scale set is an environment/network/subscription deployment unit, **not Azure Virtual Machine Scale Sets (VMSS)**. |
| **C. Put a project on the latest successful scale set** | **implemented**, opt-in: `environment=latest-successful` on supporting API/CLI versions. **not implemented**: selection by default when placement is omitted. |
| **D. Promote captured successful Dev configuration/version to Stage, then Prod** | **not implemented** as that end-to-end contract. Explicit target placement, target parameters and runtime deployment are supported separately, but do not capture/copy a verified source deployment or enforce a Dev → Stage → Prod success chain. |
| **E. Add/update settings or typed parameters; unset an override** | **implemented**: catalog typed parameter review/confirmation and legacy configuration review/save. Catalog settings writes are **generic-access only**. None of these is resource deletion. |
| **F. Choose APIM versus Kong for an AI gateway** | **not implemented** as a unified first-class CLI/SDK/HTTP deployment choice. Later source adds conditional MCP/AI Gateway component pipeline support; Application Gateway is a different product and its registered workflow route is blocked. |

Choose **CLI** for operator/CI usage, the supported **`AzureFactoryClient` SDK**
for Python/backend integration, or **REST** for a language-neutral trusted worker.
They call the same governed backend; they are not three deployment engines.
Do not embed its API key in browser code. There are no SDK methods named
`scaleset_add`, `project_promote` or `gateway_deploy`.

## 1. Connection and exact target selection

Use Windows PowerShell **5.1+ or 7**. Run **guide 18's Window B setup in this same
shell** to select compatible client tooling. Before real-factory operations,
replace its demonstration URL/key through your approved secret mechanism with
the **actual owning API host and key**. Do not operate a real factory through the
public demonstration key or assume port 8876 is its operational host.
That setup defines `$ApiRoot`, `$AcceleratorRoot`,
`$Python = Join-Path $ApiRoot '.venv\Scripts\python.exe'`,
`PYTHONPATH` pointing to `environment_setup\azurefactory-cli\src`, and
`AIFACTORY_API_URL` / `AIFACTORY_API_KEY`. No console-script installation is assumed.

**Do not carry guide 18's empty-demo target into real work accidentally.** Choose
the actual existing catalog for B–F, or a separately approved new target for A.
All `folder`, `repo_root` and configuration import paths sent to the API refer to
the **API host**. Request files and receipts in this tutorial are **client-local**.
The two machines need not share a filesystem, although these privileged API
surfaces retain their local-host access restrictions. For A, the chosen new
`azurefactory` directory must already exist and satisfy empty-root requirements;
have the API-host operator create that directory first. For B-F select an
existing registered root, not the empty smoke-test directory.

Initialize these helpers once. They are tutorial-local PowerShell functions, not
additional SDK methods. Store reviews under private local application data,
outside Git checkouts, replaceable templates and temporary cleanup areas.
Receipts and raw responses may contain sensitive configuration. Inspect inherited
permissions before proceeding.

```powershell
$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Run guide 18 Window B setup.' }
if (!$env:AIFACTORY_API_URL -or !$env:AIFACTORY_API_KEY) { throw 'Connection/key missing.' }
$FactoryFolder = Read-Host 'Exact approved azurefactory folder on the API host'
if (![IO.Path]::IsPathRooted($FactoryFolder)) { throw 'Use an absolute API-host path.' }
$ReviewBase = Join-Path $env:LOCALAPPDATA 'AzureFactory\reviews'
New-Item -ItemType Directory -Path $ReviewBase -Force | Out-Null
$ReviewRoot = Join-Path $ReviewBase ('add-update-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $ReviewRoot -ErrorAction Stop | Out-Null

function Write-ReviewJson($Value, [string]$Label) {
    $Path = Join-Path $ReviewRoot ($Label + '-' + [guid]::NewGuid().ToString('N') + '.json')
    if (Test-Path -LiteralPath $Path) { throw 'Refusing to overwrite a review artifact.' }
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 100),
        [Text.UTF8Encoding]::new($false))
    return $Path
}
function Read-Catalog {
    $Text = & $Python -m azurefactory catalog list --folder $FactoryFolder
    if ($LASTEXITCODE -ne 0) { throw 'Catalog read failed.' }
    $Value = ($Text -join "`n") | ConvertFrom-Json
    if ($Value.contract_version -ne 1 -or $Value.mode -ne 'catalog') {
        throw 'Select a registered catalog, not a legacy root.'
    }
    return $Value
}
function Read-Target([switch]$Project, [switch]$RequirePlacement) {
    $Catalog = Read-Catalog
    $Catalog.factories | Select-Object id,key,region,version_ref | Format-Table | Out-Host
    $FactoryId = Read-Host 'Exact factory UUID from this catalog'
    $Factories = @($Catalog.factories | Where-Object { $_.id -eq $FactoryId })
    if ($Factories.Count -ne 1) { throw 'Factory selection is not exact.' }
    $Factory = $Factories[0]
    $Factory.scale_sets | Select-Object id,environment,suffix,tenant_id,subscription_id |
        Format-Table | Out-Host
    $ScaleId = Read-Host 'Exact target scale-set UUID from this factory'
    $Scales = @($Factory.scale_sets | Where-Object { $_.id -eq $ScaleId })
    if ($Scales.Count -ne 1) { throw 'Scale-set selection is not exact.' }
    $SelectedProject = $null
    if ($Project) {
        $Factory.projects | Select-Object id,number,display_name,placements | Format-List | Out-Host
        $ProjectId = Read-Host 'Exact project UUID from this factory'
        $Projects = @($Factory.projects | Where-Object { $_.id -eq $ProjectId })
        if ($Projects.Count -ne 1) { throw 'Project selection is not exact.' }
        $SelectedProject = $Projects[0]
        if ($RequirePlacement -and !@($SelectedProject.placements | Where-Object {
            $_.scale_set_id -eq $ScaleId -and $_.environment -eq $Scales[0].environment
        }).Count) { throw 'Project is not placed in this target scale set.' }
    }
    return @{ catalog=$Catalog; factory=$Factory; scale=$Scales[0]; project=$SelectedProject }
}
function Read-NewScale {
    $Environment = (Read-Host 'Environment: dev, stage or prod').Trim().ToLowerInvariant()
    if ($Environment -notin @('dev','stage','prod')) { throw 'Invalid environment.' }
    $Suffix = Read-Host 'Three-digit scale-set suffix, for example 001 or 002'
    if ($Suffix -notmatch '^(?!000)[0-9]{3}$') { throw 'Suffix must be 001 through 999.' }
    $Tenant = [guid](Read-Host 'Approved existing tenant UUID')
    $Subscription = [guid](Read-Host 'Approved existing subscription UUID')
    if ($Tenant -eq [guid]::Empty -or $Subscription -eq [guid]::Empty) { throw 'Nonzero UUIDs required.' }
    $Route = (Read-Host 'Orchestrator: ado or gha').Trim().ToLowerInvariant()
    if ($Route -notin @('ado','gha')) { throw 'Invalid orchestrator.' }
    $Cidr = Read-Host 'Approved non-overlapping VNet CIDR for this environment'
    $Capacity = [int](Read-Host 'Approved project capacity, 1 through 8')
    if ($Capacity -lt 1 -or $Capacity -gt 8) { throw 'Invalid capacity.' }
    return @{
        environment=$Environment; suffix=$Suffix; tenant_id=$Tenant.ToString()
        subscription_id=$Subscription.ToString(); orchestrator=$Route
        network=@{ vnet_cidr=$Cidr; max_projects=$Capacity }
    }
}
```

The `[0]` indexing above is **only after exact-ID filtering and a uniqueness
check**. Never select `catalog.factories[0]` as an implicit target. UUIDs identify
objects; `001` is a project number or scale-set suffix. `DEV/001`, `STAGE/001` and
`PROD/001` are different scale sets. Public environment values are `dev`, `stage`,
`prod`; some underlying Azure names use `test` for Stage.

## 2. Shared three-interface prepare → review → confirm

For each scenario below:

1. Run its input constructor, which sets `$Request` and `$Operation`.
2. Run **2.1** to create fresh local paths.
3. Choose **one** prepare alternative: that scenario's friendly CLI command,
   **2.2 SDK**, or **2.3 REST**.
4. **STOP** and review. Only after approval choose **one** confirmation in **2.4**.

Do not run all alternatives against the same target. They are equivalent choices,
not sequential steps. Refresh the catalog/revisions after every confirmed change.

### 2.1 Serialize the selected scenario

The supported operations here are `factory-create`, `factory-clone`,
`scaleset-add`, `project-add`, `project-add-placements`, `parameters` and
`runtime-deploy`. Generic settings writes and bootstrap have separate sections.

```powershell
$RequestPath = Write-ReviewJson $Request 'request'
$ReceiptPath = Join-Path $ReviewRoot ('receipt-' + [guid]::NewGuid().ToString('N') + '.json')
$PreviewPath = Join-Path $ReviewRoot ('preview-' + [guid]::NewGuid().ToString('N') + '.json')
$Purpose = 'catalog-confirm'
$Mode = 'configuration'
$PrepareEndpoint = '/api/v1/factory-catalog/prepare'
$ConfirmEndpoint = '/api/v1/factory-catalog/confirm'
if ($Operation -eq 'parameters') {
    $Purpose = 'parameters-confirm'
    $PrepareEndpoint = '/api/v1/factory-catalog/parameters/prepare'
    $ConfirmEndpoint = '/api/v1/factory-catalog/parameters/confirm'
}
if ($Operation -eq 'runtime-deploy') { $Mode = 'runtime' }
$env:AIF_GUIDE_REQUEST = $RequestPath
$env:AIF_GUIDE_RECEIPT = $ReceiptPath
$env:AIF_GUIDE_PREVIEW = $PreviewPath
$env:AIF_GUIDE_OPERATION = $Operation
$env:AIF_GUIDE_PURPOSE = $Purpose
$env:AIF_GUIDE_MODE = $Mode
```

### 2.2 SDK alternative — executable for A, B, C, D, E and runtime

This uses actual supported methods. `factory_create_prepare` and
`parameter_prepare` return transport-level previews; a returned dictionary alone
is not validation. `validate_preview` and the receipt helper enforce the review
contract. `review_catalog_prepare` also validates opt-in placement resolution.

```powershell
@'
import json, os
from pathlib import Path
from azurefactory import AzureFactoryClient
from azurefactory.client import redact_secrets
from azurefactory.review import validate_preview, write_receipt

c = AzureFactoryClient()
b = json.loads(Path(os.environ["AIF_GUIDE_REQUEST"]).read_text(encoding="utf-8"))
op = os.environ["AIF_GUIDE_OPERATION"]
if op == "factory-create":
    p = c.factory_create_prepare(
        b["folder"], prefix=b["target_prefix"], region=b["target_region"],
        scale_sets=b["scale_sets"], factory_key=b["factory_key"],
        kind=b["factory_kind"], aifactory_version=b["aifactory_version"],
        initial_project=b["initial_project"], settings=b["settings"],
        expected_revision=b["expected_revision"])
elif op == "parameters":
    p = c.parameter_prepare(b)
else:
    p = c.review_catalog_prepare(b)
print(json.dumps(redact_secrets(p, c.api_key), indent=2))
validate_preview(p)
write_receipt(os.environ["AIF_GUIDE_RECEIPT"], client=c,
              purpose=os.environ["AIF_GUIDE_PURPOSE"], operation=op,
              request_body=b, preview=p)
'@ | & $Python -
if ($LASTEXITCODE -ne 0) { throw 'Prepare/validation failed; do not confirm.' }
```

### 2.3 REST alternative — same JSON, no SDK dependency

Use `curl.exe`, not PowerShell's `curl` alias. These commands require a curl
version supporting `--fail-with-body`. There are no retries or redirects.
Do not publish raw error bodies or secret-bearing requests.

```powershell
if (Test-Path -LiteralPath $PreviewPath) { throw 'Preview path already exists.' }
curl.exe --fail-with-body --silent --show-error --noproxy "*" `
    --request POST "$env:AIFACTORY_API_URL$PrepareEndpoint" `
    --header "X-API-Key: $env:AIFACTORY_API_KEY" --header "Content-Type: application/json" `
    --data-binary "@$RequestPath" --output "$PreviewPath"
if ($LASTEXITCODE -ne 0) { throw 'REST prepare failed; inspect private response, do not confirm.' }
$Preview = Get-Content -LiteralPath $PreviewPath -Raw | ConvertFrom-Json
$Preview | ConvertTo-Json -Depth 100
if ($Preview.contract_version -ne 1 -or $Preview.can_execute -ne $true -or
    @($Preview.blockers).Count -ne 0 -or $Preview.operation_mode -ne $Mode -or
    $Preview.source_revision -ne $Request.expected_revision -or
    [DateTimeOffset]::Parse($Preview.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Blocked, incompatible or expired REST preview; do not confirm.'
}
```

This saves a **plain API preview**, not a CLI receipt. Use the REST confirmation
below, not `catalog confirm --receipt` on this file. The small local checks do not
replace the server's validation or your review of target/evidence. REST-only
integrators must implement their own review storage and binding rules; they do
not need the Python SDK merely to send HTTP requests.

**STOP — obtain approval of this exact preview.** Check contract 1, operation mode,
folder, factory/project/scale-set IDs, environment, tenant/subscription, version and
resolved source commit, changes, network ownership, warnings, blockers and expiry.
For automatic placement, also inspect resolved UUIDs and success evidence. A
`can_execute: true` response is not permission. Receipts are private, expiring,
scope-bound artifacts; checksums are not signatures or user authorization.

### 2.4 Confirm only after approval — choose one

**CLI:**

```powershell
if ($Operation -eq 'parameters') {
    & $Python -m azurefactory parameters confirm --receipt $ReceiptPath --yes
} elseif ($Operation -eq 'runtime-deploy') {
    & $Python -m azurefactory runtime confirm --receipt $ReceiptPath --yes
} else {
    & $Python -m azurefactory catalog confirm --receipt $ReceiptPath --yes
}
if ($LASTEXITCODE -ne 0) { throw 'Inspect server state; do not repeat confirmation.' }
```

**SDK, instead of CLI:**

```powershell
@'
import json, os
from azurefactory import AzureFactoryClient
from azurefactory.review import load_receipt

c = AzureFactoryClient()
r = load_receipt(os.environ["AIF_GUIDE_RECEIPT"], client=c,
                 purpose=os.environ["AIF_GUIDE_PURPOSE"],
                 operation_mode=os.environ["AIF_GUIDE_MODE"])
result = (c.parameter_confirm(r["folder"], r["confirmation_id"])
          if r["purpose"] == "parameters-confirm"
          else c.catalog_confirm(r["folder"], r["confirmation_id"]))
print(json.dumps(result, indent=2))
if result.get("contract_version") != 1:
    raise RuntimeError("Unknown confirmation contract; inspect state, do not retry.")
if r["operation_mode"] == "configuration":
    if not isinstance(result.get("catalog"), dict) or result.get("job") is not None:
        raise RuntimeError("Not a catalog-only result; inspect state.")
elif not isinstance(result.get("job"), dict):
    raise RuntimeError("Missing runtime job; inspect state, do not retry.")
'@ | & $Python -
if ($LASTEXITCODE -ne 0) { throw 'Inspect the outcome; never automatically retry a write.' }
```

**REST, following REST preparation:** review the original request and its saved
API preview. Only after approval, type the exact confirmation ID you reviewed.
The server rechecks the owner, revision, expiry, one-use authorization and frozen
evidence. This does not use a CLI receipt or a Python helper.

```powershell
$ReviewedRequest = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json
$Preview = Get-Content -LiteralPath $PreviewPath -Raw | ConvertFrom-Json
if ($Preview.contract_version -ne 1 -or $Preview.can_execute -ne $true -or
    @($Preview.blockers).Count -ne 0 -or $Preview.operation_mode -ne $Mode -or
    $Preview.source_revision -ne $ReviewedRequest.expected_revision -or
    [DateTimeOffset]::Parse($Preview.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Blocked, incompatible or expired REST review.'
}
$ApprovedId = Read-Host 'After reviewing and obtaining approval, paste this preview confirmation_id'
if ($ApprovedId -cne $Preview.confirmation_id) { throw 'Approval does not match this preview.' }
$ConfirmPath = Write-ReviewJson @{
    contract_version=1; folder=$ReviewedRequest.folder; confirmation_id=$ApprovedId
} 'confirm'
$ResultPath = Join-Path $ReviewRoot ('result-' + [guid]::NewGuid().ToString('N') + '.json')
curl.exe --fail-with-body --silent --show-error --noproxy "*" `
    --request POST "$env:AIFACTORY_API_URL$ConfirmEndpoint" `
    --header "X-API-Key: $env:AIFACTORY_API_KEY" --header "Content-Type: application/json" `
    --data-binary "@$ConfirmPath" --output "$ResultPath"
if ($LASTEXITCODE -ne 0) { throw 'Unknown/failed confirmation outcome; inspect state, do not resend.' }
$Result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
if ($Result.contract_version -ne 1) { throw 'Unknown result contract.' }
if ($Mode -eq 'configuration' -and (!$Result.catalog -or $null -ne $Result.job)) {
    throw 'Not a catalog-only confirmation; inspect state.'
}
if ($Mode -eq 'runtime' -and !$Result.job) { throw 'Missing runtime job; inspect state.' }
$Result | ConvertTo-Json -Depth 100
```

For configuration, read the catalog again and verify the **reviewed UUIDs and
changes**, not simply the number of entries. The catalog's revision property is
`revision`; parameter responses and previews use `source_revision`. Do not
interchange them by guessing. A failure, timeout or lost response is not permission
to re-prepare/re-confirm or switch interfaces.

## A. New factory + selected environments + project001

This constructor lets the operator explicitly choose **any nonempty subset** of
Dev/Stage/Prod, including all three, with one selected scale per environment.
It creates exactly one logical initial project001 with those placements.
The factory must have a fresh key/prefix/region combination. An occupied draft is
not an upsert; inspect it rather than reset/recreate it.

The own-hub setting below records intent only. It does **not** supply a complete
VPN pool, hub topology, identities, repository or runner configuration. Review
those separately under [registered Full bootstrap](#registered-full-bootstrap).
No tenant or subscription is created by these inputs.

```powershell
$Before = Read-Catalog
$FactoryKey = Read-Host 'New unique factory key'
$Prefix = Read-Host 'Approved new factory prefix'
$Region = Read-Host 'Approved Azure region from the API capabilities'
$Version = Read-Host 'Approved registered source version: main or supported 125+'
$SelectedEnvironments = @((Read-Host 'Selected environments, comma-separated: dev,stage,prod').
    Split(',') | ForEach-Object { $_.Trim().ToLowerInvariant() })
if (!$SelectedEnvironments.Count -or @($SelectedEnvironments | Where-Object {
    $_ -notin @('dev','stage','prod')
}).Count -or @($SelectedEnvironments | Select-Object -Unique).Count -ne $SelectedEnvironments.Count) {
    throw 'Select each intended environment exactly once.'
}
$Scales = @()
foreach ($Environment in $SelectedEnvironments) {
    Write-Host "Enter the approved scale for $Environment."
    $Scale = Read-NewScale
    if ($Scale.environment -ne $Environment) { throw 'Environment differs from the selection.' }
    $Scales += $Scale
}
$InitialProject = @{
    number='001'; display_name=(Read-Host 'Initial project display name')
    placements=@($Scales | ForEach-Object { @{ environment=$_.environment; suffix=$_.suffix } })
}
$Settings = @{ enableAIFactoryHub='true'; centralDnsZoneByPolicyInHub='false' }
$Request = @{
    contract_version=1; folder=$FactoryFolder; action='create-factory'
    expected_revision=$Before.revision; factory_kind='ai'; factory_key=$FactoryKey
    target_prefix=$Prefix; target_region=$Region; aifactory_version=$Version
    scale_sets=$Scales; initial_project=$InitialProject; settings=$Settings
}
$Operation = 'factory-create'
$ScalePath = Write-ReviewJson $Scales 'scales'
$InitialProjectPath = Write-ReviewJson $InitialProject 'initial-project'
$SettingsPath = Write-ReviewJson $Settings 'settings'
```

Run **2.1**, then choose this **CLI prepare**, **2.2 SDK** (uses
`factory_create_prepare`) or **2.3 REST** (same complete `CatalogPrepare` payload).

```powershell
& $Python -m azurefactory factory create --folder $FactoryFolder --factory-key $FactoryKey `
    --kind ai --prefix $Prefix --region $Region --aifactory-version $Version `
    --expected-revision $Before.revision --scale-set-json $ScalePath `
    --initial-project-json $InitialProjectPath --settings-json $SettingsPath `
    --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Review creation blockers; do not confirm.' }
```

**STOP.** Approve configuration only, then use one **2.4** confirmation. Re-read
the catalog and verify project001 and all selected environment/suffix placements.
Do not run `project add --number 001` afterward. Omitting the initial-project
object also defaults to project001 on supported APIs, but this tutorial chooses
its placements explicitly. `--common-only` is a different intent.

Creating Stage/Prod **configuration**, or GitHub environments named `Dev`, `Stage`,
`Prod`, does not deploy those environments. The registered bootstrap workflow
targets its exact initial Dev scope; do not claim this short request provisions
three complete environments in one transaction.

### Clone configuration to a new factory identity or region

**implemented** CLI/REST; SDK **generic-access only** through the shared catalog
method. This copies configuration, not deployed resources, data, credentials or
models. The helper displays an existing scale as context; this example clones
the whole factory configuration, not only that scale.

```powershell
$Scope = Read-Target
$FactoryId = $Scope.factory.id
$ClonePrefix = Read-Host 'Approved new factory prefix'
$CloneRegion = Read-Host 'Approved target Azure region'
$IncludeProjects = Read-Host 'Copy project configuration? Type none or all'
if ($IncludeProjects -notin @('none','all')) { throw 'Choose none or all.' }
if ($ClonePrefix -eq $Scope.factory.prefix -and $CloneRegion -eq $Scope.factory.region) {
    throw 'Clone requires a changed prefix or region, not the same physical identity.'
}
$Request = @{
    contract_version=1; folder=$FactoryFolder; action='clone'
    factory_id=$FactoryId; expected_revision=$Scope.catalog.revision
    target_prefix=$ClonePrefix; target_region=$CloneRegion; include_projects=$IncludeProjects
}
$Operation = 'factory-clone'
```

Run **2.1**, then choose the following CLI command, **2.2 SDK**, or **2.3 REST**:

```powershell
& $Python -m azurefactory factory clone --folder $FactoryFolder --factory-id $FactoryId `
    --prefix $ClonePrefix --region $CloneRegion --include-projects $IncludeProjects `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Clone configuration review is blocked.' }
```

**STOP**, obtain approval and use the corresponding **2.4** confirmation.
Read back the new UUIDs. Revisit addressing, inherited settings and provider
binding before a separate runtime review; a renamed/relocated draft is not ready
merely because its configuration was accepted.

## B. Add a scale set, then optionally a project

Choose an existing factory and inspect its current scales. The helper also asks
for an existing scale to make the context explicit; the **new** scale comes from
the separate inputs below and must not already exist in that environment/suffix.

```powershell
$Scope = Read-Target
$FactoryId = $Scope.factory.id
$Scale = Read-NewScale
if (@($Scope.factory.scale_sets | Where-Object {
    $_.environment -eq $Scale.environment -and $_.suffix -eq $Scale.suffix
}).Count) { throw 'This environment/suffix already exists.' }
$Request = @{
    contract_version=1; folder=$FactoryFolder; action='create-scale-set'
    factory_id=$FactoryId; expected_revision=$Scope.catalog.revision; scale_sets=@($Scale)
}
$Operation = 'scaleset-add'
$ScalePath = Write-ReviewJson @($Scale) 'new-scale'
```

Run **2.1**, then this CLI alternative or the shared SDK/REST alternative:

```powershell
& $Python -m azurefactory scaleset add --folder $FactoryFolder --factory-id $FactoryId `
    --expected-revision $Scope.catalog.revision --scale-set-json $ScalePath --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Scale-set preview blocked.' }
```

**STOP**, then approve and confirm using **2.4**. No VMSS, common infrastructure or
project is deployed by that write. Re-read the catalog and explicitly select the
new scale UUID before another operation. SDK uses `review_catalog_prepare` with
`action: "create-scale-set"`; there is no dedicated `scaleset_add` SDK method.

### Add a different project to an existing or newly saved scale

This is an independent configuration write. Do not reuse project001 from A.

```powershell
$Scope = Read-Target
$FactoryId = $Scope.factory.id
$Number = Read-Host 'Unused three-digit project number, 001 through 999'
if ($Number -notmatch '^(?!000)[0-9]{3}$') { throw 'Project number must be 001 through 999.' }
$DisplayName = Read-Host 'Project display name'
$Placement = $Scope.scale.environment + '=' + $Scope.scale.id
$Request = @{
    contract_version=1; folder=$FactoryFolder; action='add-project'
    factory_id=$FactoryId; expected_revision=$Scope.catalog.revision
    project=@{ number=$Number; display_name=$DisplayName
        placements=@(@{ environment=$Scope.scale.environment; scale_set_id=$Scope.scale.id }) }
}
$Operation = 'project-add'
```

Run **2.1**, then one prepare alternative:

```powershell
& $Python -m azurefactory project add --folder $FactoryFolder --factory-id $FactoryId `
    --number $Number --display-name $DisplayName --placement $Placement `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Project preview blocked.' }
```

**STOP**, then **2.4** after approval. For SDK/REST use the same constructed body
through **2.2/2.3**. Configuration of the scale and project is not atomic across
these two writes. Deployment is the separate runtime section below.
The server checks number collisions in the exact selected placements and
layout-2 project home. Do not impose a different factory-wide uniqueness rule.

## C. Explicit latest-successful placement

**Implemented opt-in; not default behavior.** Build the new-project request in B,
then, **before 2.1 or any prepare**, explicitly replace only its placement selector:

```powershell
$Environment = $Scope.scale.environment
$Request.project.placements = @(@{ environment=$Environment; scale_set_id='latest-successful' })
$Placement = $Environment + '=latest-successful'
```

Run **2.1**, then choose this complete CLI command or the shared **2.2 SDK /
2.3 REST** alternatives:

```powershell
& $Python -m azurefactory project add --folder $FactoryFolder --factory-id $FactoryId `
    --number $Number --display-name $DisplayName --placement $Placement `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Automatic placement is blocked; inspect its evidence requirements.' }
```

The chosen existing scale in the input helper identifies
the requested environment, **not** the final automatic target.

The API selects eligible recorded verified **common** deployment evidence in the
selected factory/environment/version and checks capacity/scope. It does not sort
suffixes client-side, probe all Azure resources anew, or regard drafts, inventory,
local zero exit or `submitted` as success. Review
`latest-successful-placement-v1` and `resolved_placements`: exact UUID, source
commit, job/completion and evidence hash. CLI/receipt validation and
`review_catalog_prepare` reject missing or contradictory resolution.

**STOP**, then approve the exact resolved target through **2.4**. Confirmation
never silently reselects a newer candidate. No eligible scale is a blocker, not
permission to create one or guess an ID. Omitting `--placement` fails; it does
not mean latest-successful. The same explicit selector is supported on
`project add-placements` by replacing D's placement value, but is not promotion.

## D. Explicit Stage/Prod placement is not captured promotion

**Not implemented:** a supported operation that captures Dev's successful
configuration/version/source receipt and promotes that immutable capture through
Stage and Prod. There is no `project promote` command or `project_promote` SDK
method. A runtime `--version-ref` selects code; it does not capture/copy resource
configuration, data, models or source-environment success.

The limited alternative is to create the target scale with B if absent, add the
logical project's missing target placement below, edit **target** parameters with
E, then separately deploy the target. Each step needs its own review.

```powershell
$Scope = Read-Target -Project
$FactoryId = $Scope.factory.id
$ProjectId = $Scope.project.id
$ScaleId = $Scope.scale.id
$Environment = $Scope.scale.environment
if ($Environment -notin @('stage','prod')) { throw 'Choose the intended Stage or Prod target.' }
if (@($Scope.project.placements | Where-Object { $_.environment -eq $Environment }).Count) {
    throw 'This project already has a placement in that environment; inspect it, do not move it implicitly.'
}
$Placement = $Environment + '=' + $ScaleId
$Request = @{
    contract_version=1; folder=$FactoryFolder; action='add-project-placements'
    factory_id=$FactoryId; project_id=$ProjectId; expected_revision=$Scope.catalog.revision
    placements=@(@{ environment=$Environment; scale_set_id=$ScaleId })
}
$Operation = 'project-add-placements'
```

Run **2.1**, then choose this CLI, **2.2 SDK** or **2.3 REST**:

```powershell
& $Python -m azurefactory project add-placements --folder $FactoryFolder `
    --factory-id $FactoryId --project-id $ProjectId --placement $Placement `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Target placement preview blocked.' }
```

**STOP**, then **2.4** after approval. For Prod, repeat target selection and review
explicitly; do not describe this repetition as a built-in Stage-success gate.
Do not route catalog roots through legacy deployment to bypass a blocker.

## E. Add/update a parameter, unset an override, or edit settings

### Typed resource parameters — all three interfaces

Read the actual target's published template schema. Do not guess resource flag
names from a slide, old template or another factory version. For common-only
parameters omit project selection and `--project-id`; this example targets a
project that is already placed in the selected scale.

```powershell
$Scope = Read-Target -Project -RequirePlacement
$FactoryId = $Scope.factory.id
$ScaleId = $Scope.scale.id
$ProjectId = $Scope.project.id
$Text = & $Python -m azurefactory parameters get --folder $FactoryFolder `
    --factory-id $FactoryId --scale-set-id $ScaleId --project-id $ProjectId
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the parameter schema.' }
$Parameters = ($Text -join "`n") | ConvertFrom-Json
$Parameters | ConvertTo-Json -Depth 100
if ($Parameters.requires_profile_reset) { throw 'Profile reset needs a separate explicit review; stop.' }
$TemplateName = Read-Host 'Exact template name from this response'
$Templates = @($Parameters.templates | Where-Object { $_.template -eq $TemplateName })
if ($Templates.Count -ne 1) { throw 'Select one published template.' }
$Field = Read-Host 'Exact editable parameter field name from this template'
if (!@($Templates[0].fields | Where-Object { $_.name -eq $Field }).Count) {
    throw 'Unknown field; do not fabricate a parameter.'
}
$Edit = (Read-Host 'Choose set or unset').Trim().ToLowerInvariant()
$Patch = @{ template=$TemplateName; parameters=@{}; unset=@() }
if ($Edit -eq 'set') {
    $Patch.parameters[$Field] = ConvertFrom-Json -InputObject (
        Read-Host 'Approved JSON value (string in quotes, boolean, number, object or array; no secrets)')
} elseif ($Edit -eq 'unset') {
    $Patch.unset = @($Field)
} else { throw 'Choose set or unset.' }
$Request = @{
    contract_version=1; folder=$FactoryFolder; factory_id=$FactoryId
    scale_set_id=$ScaleId; project_id=$ProjectId
    expected_revision=$Parameters.source_revision; schema_revision=$Parameters.schema_revision
    templates=@($Patch)
}
$Operation = 'parameters'
```

Run **2.1**, then this CLI or **2.2 SDK / 2.3 REST**. The latter use
`parameter_prepare` and `/factory-catalog/parameters/prepare`, respectively.

```powershell
& $Python -m azurefactory parameters prepare --request-json $RequestPath --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Parameter preview blocked.' }
```

**STOP**, then the matching parameter confirmation in **2.4** after approval.
This merges only selected changes and preserves other values. `unset` removes a
saved override; it is not `null`, resource deletion, or necessarily disabling the
effective resource. Inherited/default values and required schema fields still
matter. A disabled resource flag does not promise deletion of an existing Azure
resource. Follow the reviewed runtime plan for deployment and guide 20 for removal.
Do not silently use `--reset-profile` to make an incompatible schema pass.
An explicitly approved `reset_profile` discards **every old protected parameter
context in that scale set**, even when `project_id` selects one project; it is not
a project-only reset. Review that broader configuration loss separately.

SDK read equivalent: `client.catalog_parameters(folder, factory_id, scale_set_id,
project_id)`. REST read equivalent: `GET /api/v1/factory-catalog/parameters` with
those exact query names. Guide 18 shows read-request mechanics. The complete
prepare/confirm alternatives above share the parsed schema revisions; no helper
installation or hand-built JSON string is required.

### Catalog settings — generic-access only

`catalog settings` / `catalog_settings` is a **read**, not a setter. There is no
friendly `settings set` command. `action: "configure-settings"` uses the generic
catalog API. The specialized catalog receipt helper does not accept a settings
operation label; do not invent one.

Select an exact scope, read `field_keys` and `revision`, and send only intended
nonsecret scalar replacements. This example edits scale-level settings; add a
validated `project_id` only for project settings, or omit `scale_set_id` for
factory-only settings. Identity/network/version fields are separately managed.

```powershell
$Scope = Read-Target
$Text = & $Python -m azurefactory catalog settings --folder $FactoryFolder `
    --factory-id $Scope.factory.id --scale-set-id $Scope.scale.id
if ($LASTEXITCODE -ne 0) { throw 'Settings read failed.' }
$CurrentSettings = ($Text -join "`n") | ConvertFrom-Json
$CurrentSettings | ConvertTo-Json -Depth 100
$SettingName = Read-Host 'Exact editable field_key'
if ($SettingName -notin $CurrentSettings.field_keys) { throw 'Setting is not editable here.' }
$SettingValue = ConvertFrom-Json -InputObject (Read-Host 'Approved scalar JSON replacement, not a secret')
$Changes = @{}
$Changes[$SettingName] = $SettingValue
$SettingsRequest = @{
    contract_version=1; folder=$FactoryFolder; action='configure-settings'
    factory_id=$Scope.factory.id; scale_set_id=$Scope.scale.id
    expected_revision=$CurrentSettings.revision; settings=$Changes
}
$SettingsRequestPath = Write-ReviewJson $SettingsRequest 'settings-request'
$Text = & $Python -m azurefactory request POST /api/v1/factory-catalog/prepare `
    --body-json $SettingsRequestPath --write --yes
if ($LASTEXITCODE -ne 0) { throw 'Settings preview blocked.' }
$SettingsPreview = ($Text -join "`n") | ConvertFrom-Json
if (!$SettingsPreview.can_execute -or @($SettingsPreview.blockers).Count -or
    $SettingsPreview.operation_mode -ne 'configuration' -or
    $SettingsPreview.source_revision -ne $CurrentSettings.revision) { throw 'Invalid settings preview.' }
$SettingsPreviewPath = Write-ReviewJson $SettingsPreview 'settings-preview'
$SettingsPreview | ConvertTo-Json -Depth 100
```

The generic CLI `--write --yes` above acknowledges **only preparing** this request;
it is not confirmation. SDK equivalent is
`client.catalog_prepare(parsed_request)` followed by `validate_preview(preview)`;
REST is the same JSON to `POST /api/v1/factory-catalog/prepare`.

**STOP — review exact settings, scope, revision and expiry and obtain approval.**
The server binds and rechecks the protected preview. Do not edit the saved
preview or regenerate it silently. Only then:

```powershell
$SettingsPreview = Get-Content -LiteralPath $SettingsPreviewPath -Raw | ConvertFrom-Json
if ([DateTimeOffset]::Parse($SettingsPreview.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Settings preview expired; another review is required.'
}
$SettingsConfirmPath = Write-ReviewJson @{
    contract_version=1; folder=$FactoryFolder; confirmation_id=$SettingsPreview.confirmation_id
} 'settings-confirm'
& $Python -m azurefactory request POST /api/v1/factory-catalog/confirm `
    --body-json $SettingsConfirmPath --write --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect saved state; do not resend.' }
```

SDK confirmation is `catalog_confirm(folder, confirmation_id)`; REST confirmation
uses that same JSON and endpoint. Read settings again and check the exact value.
Settings currently merge scalar replacements: **`null` is not a general settings
unset operation**. Use typed parameter `unset` where supported; do not assume a
settings patch deletes a key or resource.

### Other existing catalog configuration actions

These are **generic-access only** SDK/CLI operations, not additional friendly
commands. They use `POST /api/v1/factory-catalog/prepare` with a closed
`CatalogPrepare` request, then the separately reviewed `/confirm`. Use plain
saved API previews, as in the settings workflow, not an invented specialized
`write_receipt` operation name. The model in the selected host's OpenAPI is
authoritative for required fields and forbidden combinations.

| Action | When to choose it | Scope / boundary |
| --- | --- | --- |
| `migrate` | Explicitly register legacy configuration, or copy it into a separate empty modern root | Same-root legacy registration uses `folder`; copy migration uses destination `folder` plus explicit `source_folder`. Preserve UUIDs/source files. Never run both roots as independent writers of the same Azure targets. No deployed ownership is inferred. |
| `correct-draft-scale-identity` | Correct a mistaken tenant/subscription on an eligible empty draft | Exact `factory_id`, `scale_set_id`, `expected_revision`, and `draft_identity` containing tenant/subscription UUIDs. Bound, owned, placed or previously executed targets are blocked; not a migration of deployed resources. |
| `configure-binding` | Save a separately reviewed provider execution binding | Exact factory and typed `RuntimeBinding`; use the enrollment candidate workflow below rather than guessing repository, runner, principal or lock coordinates. |

The SDK uses `catalog_prepare(parsed_body)` and `catalog_confirm(folder,
confirmation_id)`. The generic CLI uses `request POST` with `--body-json`,
`--write --yes`; these flags acknowledge that single HTTP request, not approval
for a later runtime operation. Generic transport does not relax server guards.

## Separate runtime deployment — after configuration approval

This is the closest supported target deployment for B/D/E, **not captured
promotion**. Runtime preparation uses `action: "deploy"` on the catalog API.
It can be blocked by binding, ownership, coordination, published source, host
identity, principal, runner, networking or provider capability checks. Common-only,
GHA and shared-remote execution require the compatible scoped implementation;
configuration acceptance alone never establishes that support.

```powershell
$Scope = Read-Target -Project -RequirePlacement
$FactoryId = $Scope.factory.id
$ScaleId = $Scope.scale.id
$ProjectId = $Scope.project.id
$VersionRef = Read-Host 'Explicit approved runtime code version/reference'
if (!$VersionRef) { throw 'Choose a version explicitly for this example.' }
$Request = @{
    contract_version=1; folder=$FactoryFolder; action='deploy'
    factory_id=$FactoryId; scale_set_id=$ScaleId; project_id=$ProjectId
    expected_revision=$Scope.catalog.revision; version_ref=$VersionRef
}
$Operation = 'runtime-deploy'
```

Run **2.1**, then choose this CLI, **2.2 SDK** (`review_catalog_prepare`) or
**2.3 REST** (`POST /api/v1/factory-catalog/prepare`):

```powershell
& $Python -m azurefactory runtime deploy --folder $FactoryFolder --factory-id $FactoryId `
    --scale-set-id $ScaleId --project-id $ProjectId --version-ref $VersionRef `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Runtime blocked; no legacy/bootstrap fallback.' }
```

For B's **common-only** scale-set deployment, use this constructor **instead of**
the project constructor above, then run **2.1** and the following CLI command
(or the same **2.2 SDK / 2.3 REST** alternatives). This is still conditional on
the reviewed runtime's common-only support:

```powershell
$Scope = Read-Target
$FactoryId = $Scope.factory.id
$ScaleId = $Scope.scale.id
$ProjectId = $null
$VersionRef = Read-Host 'Explicit approved runtime code version/reference'
if (!$VersionRef) { throw 'Choose a version explicitly.' }
$Request = @{
    contract_version=1; folder=$FactoryFolder; action='deploy'
    factory_id=$FactoryId; scale_set_id=$ScaleId
    expected_revision=$Scope.catalog.revision; version_ref=$VersionRef
}
$Operation = 'runtime-deploy'
```

After **2.1**, the common-only CLI prepare is:

```powershell
& $Python -m azurefactory runtime deploy --folder $FactoryFolder --factory-id $FactoryId `
    --scale-set-id $ScaleId --version-ref $VersionRef `
    --expected-revision $Scope.catalog.revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Common runtime blocked; do not switch routes to bypass it.' }
```

**STOP — this is a cloud/runtime approval, not another configuration save.**
Only after approval use **2.4**, whose CLI branch is `runtime confirm`. Omitting
`project_id` deliberately selects common-only deployment, not every project; use
that only with a separately reviewed supported common route.

Inspect the returned job, then observe its exact ID:

```powershell
$JobsText = & $Python -m azurefactory catalog jobs --folder $FactoryFolder
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect jobs.' }
$Jobs = ($JobsText -join "`n") | ConvertFrom-Json
$Jobs | ConvertTo-Json -Depth 100
$JobId = Read-Host 'Exact runtime job UUID returned by this confirmation'
if (!@($Jobs.jobs | Where-Object {
    $_.id -eq $JobId -and $_.factory_id -eq $FactoryId -and
    $_.scale_set_id -eq $ScaleId -and $_.project_id -eq $ProjectId
}).Count) { throw 'Job is not the selected scope; inspect the confirmation.' }
& $Python -m azurefactory runtime status --folder $FactoryFolder --job-id $JobId
if ($LASTEXITCODE -ne 0) { throw 'Inspect the reported job state, not a retry instruction.' }
& $Python -m azurefactory runtime poll --folder $FactoryFolder --job-id $JobId `
    --poll-timeout 300 --poll-interval 2
if ($LASTEXITCODE -ne 0) { throw 'Deadline/failure/uncertainty: inspect state; do not redispatch.' }
```

SDK observation is `catalog_job(folder, job_id)` / `catalog_terminal(folder,
job_id, cursor)`; REST is `GET /api/v1/factory-catalog/jobs/{job_id}?folder=...`
and `/api/v1/factory-catalog/terminal` with `folder`, `job_id`, `cursor`.
Timeout stops waiting; it does not cancel work. Verify provider/worker deployment
evidence, exact source/target and catalog lifecycle before claiming success.

## Registered Full bootstrap

**Conditional/blocked**, with complete operator-reviewed inputs. This is the staged
`bootstrap workflow ...` family, not the older launcher-based `bootstrap ...`
family. It can review and create its own prerequisites; do not impose advanced
manual enrollment as a universal prerequisite or use either route as a bypass.
It may provision identities, groups, network foundation, runners and common/project
resources, create repositories, commit/push and dispatch pipelines.

First save compatible registered configuration through A or the registered
creation API. The latter is **generic-access only** in CLI/SDK:
`POST /api/v1/creation/prepare`, then separately approved `/creation/confirm`.
It is not `bootstrap_prepare`, which targets the legacy launcher endpoint.
Do not recreate an occupied factory merely to switch routes.

### Discover and provide the complete bootstrap configuration

```powershell
& $Python -m azurefactory bootstrap capabilities
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect bootstrap capabilities.' }
& $Python -m azurefactory schema --openapi
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect bootstrap schema.' }
```

Read `bootstrap_fields` (including `required`), defaults and supported regions in
capabilities, `BootstrapConfig` / `WorkflowBootstrapConfig` and
`CreationWorkflowPrepare` in the live OpenAPI, and the canonical API guide in
`$ApiRoot\docs\API.md`. Mandatory BootstrapConfig keys include
`subscription_id`, `tenant_id`, `scale_set_number`, `repo_root`,
`team_member_email`, `team_group_name`; route validation adds the GHA repository
or ADO organization/project/repository/service connection and ADO connected tenant.
Use real approved values; a supplied existing team-group ID does not remove the
current API's required team name/member-email fields.

For A's **owned** hub/VPN, explicitly review `setup_hub_access: true`,
`access_hub_mode: "integrated"`, Dev VNet CIDR and `vpn_client_cidr`, DNS/network
ownership, region, subscription, project001, provider/repository, identity and runner
choices. Integrated mode is not an instruction to invent a second hub VNet.
External hub mode is different. The workflow does not install a VPN client or
prove workstation connectivity. Hosted runners need appropriate private access.

Choose `coordination_mode` explicitly. `single-writer` requires approved exclusive
writer/private-repository governance; `blob` has its own enrollment/network
prerequisites. Never change a bound factory's mode just to unblock deployment.
The configuration file below is **operator supplied** after this review, not a
hidden file shipped by this guide:

```powershell
$Scope = Read-Target -Project -RequirePlacement
if ($Scope.scale.environment -ne 'dev') { throw 'Choose the reviewed initial Dev bootstrap scope.' }
$BootstrapConfigPath = Read-Host 'Existing absolute CLIENT-local JSON file containing the reviewed complete bootstrap_config object'
if (!(Test-Path -LiteralPath $BootstrapConfigPath -PathType Leaf)) { throw 'Supply the real reviewed file.' }
$BootstrapConfig = Get-Content -LiteralPath $BootstrapConfigPath -Raw | ConvertFrom-Json
foreach ($Key in @('subscription_id','tenant_id','scale_set_number','repo_root','team_member_email','team_group_name')) {
    if (!$BootstrapConfig.$Key) { throw "Missing mandatory bootstrap field: $Key" }
}
if ($BootstrapConfig.subscription_id -ne $Scope.scale.subscription_id -or
    $BootstrapConfig.tenant_id -ne $Scope.scale.tenant_id -or
    $BootstrapConfig.scale_set_number -ne $Scope.scale.suffix -or
    $BootstrapConfig.project_number -ne $Scope.project.number) {
    throw 'Bootstrap configuration must match the saved target exactly.'
}
$WorkflowRequest = @{
    contract_version=1; operation='create-factory'; execution_mode='privileged-bootstrap'
    creation_mode='full-bootstrap'; approval_mode='per-stage'
    scope=@{ folder=$FactoryFolder; factory_id=$Scope.factory.id
        scale_set_id=$Scope.scale.id; project_id=$Scope.project.id }
    expected_revision=$Scope.catalog.revision; bootstrap_config=$BootstrapConfig
}
$WorkflowRequestPath = Write-ReviewJson $WorkflowRequest 'workflow-request'
$PreflightRequestPath = Write-ReviewJson @{
    contract_version=1; orchestrator=$Scope.scale.orchestrator
    bootstrap_config=$BootstrapConfig; scope=$WorkflowRequest.scope
    expected_revision=$Scope.catalog.revision
} 'preflight-request'
$PreflightReportPath = Join-Path $ReviewRoot ('preflight-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory preflight --request-json $PreflightRequestPath --save-report $PreflightReportPath
if ($LASTEXITCODE -ne 0) { throw 'Preflight blocked/incomplete; inspect it before preparing.' }
```

The local checks above are not full schema/Azure validation. Server preflight is
read-only, may query Azure/provider state, and creates no authorization. Its cost
estimate is advisory, possibly partial, not a spend cap or deployment receipt.
An equivalent CLI entry point accepts the workflow request itself; choose this
instead of the preceding `preflight` call, not as another approval step:

```powershell
$AlternateReportPath = Join-Path $ReviewRoot ('preflight-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory bootstrap workflow prepare --preflight `
    --request-json $WorkflowRequestPath --save-report $AlternateReportPath
if ($LASTEXITCODE -ne 0) { throw 'Readiness is blocked or incomplete; this created no workflow approval.' }
```

### Per-stage workflow: prepare, approve, observe, next

```powershell
$WorkflowReceiptPath = Join-Path $ReviewRoot ('stage-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory bootstrap workflow prepare --request-json $WorkflowRequestPath `
    --save-receipt $WorkflowReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Workflow preparation blocked.' }
```

**STOP — approve the exact stage, scope, source, commands, effects and expiry.**
Only then:

```powershell
& $Python -m azurefactory bootstrap workflow start --receipt $WorkflowReceiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect workflow state; do not repeat start.' }
$WorkflowReceipt = Get-Content -LiteralPath $WorkflowReceiptPath -Raw | ConvertFrom-Json
$WorkflowId = $WorkflowReceipt.preview.workflow_id
& $Python -m azurefactory bootstrap workflow status --folder $FactoryFolder --workflow-id $WorkflowId
if ($LASTEXITCODE -ne 0) { throw 'Inspect the reported workflow boundary.' }
```

Wait/observe until the server explicitly reports `requires_review: true`; do not
infer the next stage from a local command exit. Then prepare a fresh receipt:

```powershell
$WorkflowReceiptPath = Join-Path $ReviewRoot ('stage-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory bootstrap workflow next --folder $FactoryFolder `
    --workflow-id $WorkflowId --save-receipt $WorkflowReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'No confirmable next stage.' }
```

**STOP again.** Review this new stage before separately using the earlier `start`
command with this new receipt. Never automate a loop that approves every stage.
An individual stage or queued job is not the entire factory's deployment result.

### Optional bounded whole-workflow approval

Instead of the per-stage initial prepare, choose this explicitly:

```powershell
$WorkflowReceiptPath = Join-Path $ReviewRoot ('whole-workflow-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory bootstrap workflow prepare --whole-workflow `
    --request-json $WorkflowRequestPath --save-receipt $WorkflowReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Bounded approval unsupported/blocked; no silent fallback.' }
```

**STOP.** Review `review.workflow_authorization` with contract
`bounded-full-bootstrap-v1`, all stages/effects, exact scope/source/program and
template fingerprints, expiry and hash, plus advisory `review.cost_preview`.
Only after approval run the separate `bootstrap workflow start` above.
The **server**, not a client approval loop, owns continuation. Changed inputs,
expired approval, failed or uncertain stages require review/reconciliation.

Only if the server reports a **safely resumable boundary**, use the original
consumed authorization, not a new approval or a retry:

```powershell
$WorkflowReceipt = Get-Content -LiteralPath $WorkflowReceiptPath -Raw | ConvertFrom-Json
$WorkflowId = $WorkflowReceipt.preview.workflow_id
$AuthorizationHash = $WorkflowReceipt.preview.review.workflow_authorization.authorization_hash
if (!$AuthorizationHash) { throw 'This is not a whole-workflow receipt.' }
& $Python -m azurefactory bootstrap workflow continue --folder $FactoryFolder `
    --workflow-id $WorkflowId --authorization-hash $AuthorizationHash
if ($LASTEXITCODE -ne 0) { throw 'Inspect state; never loop continue on failure.' }
```

### Registered workflow SDK/REST mapping

These are real methods/routes; the same reviewed JSON and server responses apply.
For a custom SDK/REST worker, validate previews and use `write_receipt` /
`load_receipt` with purpose `creation-workflow-start`, operation
`creation-workflow`, before explicit approval/start. This also validates bounded
authorization hashes; `validate_preview` alone does not validate that contract.

| Step | Supported SDK | HTTP contract |
|---|---|---|
| Capabilities | `creation_capabilities()` | `GET /api/v1/creation/capabilities` |
| Read-only preflight | `preflight(parsed_preflight_request)` | `POST /api/v1/creation/preflight` |
| Prepare | `creation_workflow_prepare(parsed_workflow_request)` | `POST /api/v1/creation/workflows/prepare` |
| Start | `creation_workflow_start(folder, workflow_id, confirmation_id, authorization_hash=reviewed_hash)`; omit hash for per-stage | `POST /api/v1/creation/workflows/start`: `folder`, `workflow_id`, `confirmation_id`, optional `authorization_hash` |
| Status | `creation_workflow_status(folder, workflow_id)` | `GET /api/v1/creation/workflows/{id}` with `folder` query |
| Next review | `creation_workflow_next(folder, workflow_id)` | `POST /api/v1/creation/workflows/{id}/prepare-next`: `{"folder": ...}` |
| Safe continuation only | `creation_workflow_continue(folder, workflow_id, authorization_hash)` | `POST /api/v1/creation/workflows/{id}/continue`: `folder`, original `authorization_hash` |

## Advanced enrollment is a separate local-core workflow

`enrollment plan`, `ensure` and `plan-and-publish` call the **local enrollment core**
with explicitly authenticated Azure/provider tools. They are **not equivalent
REST/`AzureFactoryClient` enrollment contracts**. Plan can read cloud state;
ensure can provision billable resources and grant roles. Neither creates every
runner/network resource or deploys workloads.

Only use this advanced route deliberately, with a schema-2 consumer repository,
exact registered scope and administrator-established serialized/exclusive-writer
governance. Read the closed options schema and
[canonical enrollment reference](../../../environment_setup/azurefactory-cli/readme.md#enroll-a-registered-factory--scale-set)
for required repository/ref, writable/dependency RG IDs, roles, runner, ADO tenant,
identity and coordination options. Do not put credentials in options JSON.

```powershell
$Scope = Read-Target
$EnrollmentConsumerRoot = Read-Host 'Absolute schema-2 consumer root accessible to local CLI AND API host'
$OptionsPath = Read-Host 'Existing absolute local reviewed enrollment-options JSON file'
if (!(Test-Path -LiteralPath $OptionsPath -PathType Leaf)) { throw 'Provide reviewed options.' }
$PlanPath = Join-Path $ReviewRoot ('enrollment-plan-' + [guid]::NewGuid().ToString('N') + '.json')
$EnrollmentResultPath = Join-Path $ReviewRoot ('enrollment-result-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory enrollment plan --consumer-root $EnrollmentConsumerRoot `
    --factory-id $Scope.factory.id --scale-set-id $Scope.scale.id --environment $Scope.scale.environment `
    --options $OptionsPath --expected-orchestrator $Scope.scale.orchestrator `
    --acknowledge-exclusive-writer-governance --save-plan $PlanPath
if ($LASTEXITCODE -ne 0) { throw 'Enrollment plan blocked.' }
```

The governance flag is an **administrator attestation**, not a way to create
governance. Omit this route if that attestation is not true.

**STOP — independently approve the plan, role scopes, resource creation, hashes
and limitations.** Only then:

```powershell
& $Python -m azurefactory enrollment ensure --plan $PlanPath --yes `
    --acknowledge-exclusive-writer-governance --save-result $EnrollmentResultPath
if ($LASTEXITCODE -ne 0) { throw 'Inspect enrollment outcome; do not re-plan/retry automatically.' }
```

Ensure returns a **binding candidate**, not a deployment. For its independent
publication review:

```powershell
$Catalog = Read-Catalog
$BindingReceiptPath = Join-Path $ReviewRoot ('binding-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory enrollment prepare-binding --result $EnrollmentResultPath `
    --expected-revision $Catalog.revision --save-receipt $BindingReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Binding publication preview blocked.' }
```

**STOP — review the exact candidate, API target, derived consumer folder and
revision, then approve publication separately:**

```powershell
& $Python -m azurefactory enrollment publish --receipt $BindingReceiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect binding state; do not republish automatically.' }
```

This final binding portion is catalog `action: "configure-binding"` plus catalog
confirm; `catalog confirm` is an alternative to `enrollment publish`, not another
step. It does not imply SDK parity for provisioning.

`plan-and-publish` is an alternative bounded convenience path, **not an extra step
after the sequence above**. With the same explicit inputs and governance, first
review its nonmutating plan (exit 3 means approval required):

```powershell
$CombinedReviewDir = Join-Path $ReviewRoot ('combined-review-' + [guid]::NewGuid().ToString('N'))
& $Python -m azurefactory enrollment plan-and-publish --consumer-root $EnrollmentConsumerRoot `
    --factory-id $Scope.factory.id --scale-set-id $Scope.scale.id --environment $Scope.scale.environment `
    --options $OptionsPath --artifact-dir $CombinedReviewDir --expected-orchestrator $Scope.scale.orchestrator `
    --acknowledge-exclusive-writer-governance
if ($LASTEXITCODE -ne 3) { throw 'Inspect result; expected an approval-required review, not execution.' }
```

**STOP.** Approve enrollment **and binding publication**, not Full bootstrap or
workload deployment. Use a different, nonexistent artifact directory:

```powershell
$CombinedRunDir = Join-Path $ReviewRoot ('combined-run-' + [guid]::NewGuid().ToString('N'))
& $Python -m azurefactory enrollment plan-and-publish --consumer-root $EnrollmentConsumerRoot `
    --factory-id $Scope.factory.id --scale-set-id $Scope.scale.id --environment $Scope.scale.environment `
    --options $OptionsPath --artifact-dir $CombinedRunDir --expected-orchestrator $Scope.scale.orchestrator `
    --acknowledge-exclusive-writer-governance --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect saved artifacts and server state; no automatic retry.' }
```

The convenience flow's new-binding/no-Blob-options default can be single-writer;
original plan/ensure defaults differ. Saved factory mode must already agree.
It must not migrate an existing binding, rewrite the register to fit, infer an
Azure subscription from the current account, or weaken shared-hub governance.

## Legacy configuration and legacy deployment are separate contracts

Use this only for a real legacy `aifactory` root, not an `azurefactory` catalog.
Legacy configuration review/save requires an exact persistent JSON project and
preserves its opaque `_json_source` metadata. Do not construct a lossy full-state
replacement or edit identity/private fields.

```powershell
$LegacyFolder = Read-Host 'Exact legacy aifactory folder on the API host'
$LegacyProject = Read-Host 'Exact three-digit legacy project number'
if ($LegacyProject -notmatch '^(?!000)[0-9]{3}$') { throw 'Choose an exact project number.' }
& $Python -m azurefactory legacy list --folder $LegacyFolder
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect existing legacy deployment drafts.' }
& $Python -m azurefactory schema
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect editable wizard fields.' }
$ChangesSourcePath = Read-Host 'Existing local JSON object containing only reviewed editable field replacements'
if (!(Test-Path -LiteralPath $ChangesSourcePath -PathType Leaf)) { throw 'Provide the real changes file.' }
$LegacyChangesPath = Write-ReviewJson (Get-Content -LiteralPath $ChangesSourcePath -Raw | ConvertFrom-Json) 'legacy-changes'
& $Python -m azurefactory config review --folder $LegacyFolder `
    --project-number $LegacyProject --changes-json $LegacyChangesPath
if ($LASTEXITCODE -ne 0) { throw 'Legacy configuration review failed.' }
```

**STOP — inspect actual patch values, `review_id`, `can_save`, changed fields,
warnings, validation and write choice.** Only after approval:

```powershell
$ReviewId = Read-Host 'Exact approved review_id from config review'
& $Python -m azurefactory config save --folder $LegacyFolder --project-number $LegacyProject `
    --changes-json $LegacyChangesPath --expected-review $ReviewId --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect persistent state; never blindly repeat save.' }
```

This saves configuration, normally including pipeline variable files; use
`--snapshot-only` on **both** review and save only when that was the reviewed
intent. It does not deploy or commit/push. The supported SDK orchestration is
[`ConfigurationDraft.load/review/save`](../../../environment_setup/install_config_wizard/api-usage-examples/python/edit_configuration.py).
Its underlying HTTP mapping is `/api/v1/projects/load`, `/validation`,
`/export` without a path for review, then separately approved `/projects/save`.
`/startup/load` is a hint, not exact project selection; preserve `_json_source`.

For a separate legacy runtime update/deployment:

```powershell
$LegacySourceEnv = (Read-Host 'Source environment: dev, stage or prod').ToLowerInvariant()
$LegacyTargetEnv = (Read-Host 'Target environment: dev, stage or prod').ToLowerInvariant()
if ($LegacySourceEnv -notin @('dev','stage','prod') -or
    $LegacyTargetEnv -notin @('dev','stage','prod')) { throw 'Invalid environment.' }
$LegacyOperation = if ($LegacySourceEnv -eq $LegacyTargetEnv) { 'update' } else { 'deploy' }
& $Python -m azurefactory legacy plan --folder $LegacyFolder --project-number $LegacyProject `
    --operation $LegacyOperation --source-env $LegacySourceEnv --target-env $LegacyTargetEnv
if ($LASTEXITCODE -ne 0) { throw 'Legacy deployment plan failed.' }
$DraftId = Read-Host 'Exact draft ID returned by this plan'
$LegacyReceiptPath = Join-Path $ReviewRoot ('legacy-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory legacy prepare --folder $LegacyFolder --draft-id $DraftId `
    --save-receipt $LegacyReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Legacy deployment preview blocked.' }
```

**STOP — review deployment acknowledgement contract 2**, the exact saved draft,
project, source/target, patch choice and source version/ref. Only then:

```powershell
& $Python -m azurefactory legacy start --receipt $LegacyReceiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect the legacy execution result; do not repeat start.' }
$LegacyJobId = Read-Host 'Exact job ID returned by this start'
& $Python -m azurefactory legacy status --folder $LegacyFolder --job-id $LegacyJobId `
    --wait --poll-timeout 300 --poll-interval 2
if ($LASTEXITCODE -ne 0) { throw 'Inspect the result; timeout does not cancel the job.' }
```

| Legacy stage | SDK | REST |
|---|---|---|
| Plan | `project_deployment_plan(body)` | `POST /api/v1/operations/project-deployments/plan` |
| Prepare | `project_deployment_prepare(body)` | `POST /api/v1/operations/project-deployments/prepare` |
| Start | `project_deployment_start(folder, confirmation_id)` | `POST /api/v1/operations/project-deployments/start` |
| Observe | `project_deployment_terminal(folder, job_id, cursor)` | `GET /api/v1/operations/project-deployments/terminal` |

**`submitted` means local launcher completion, not verified provider deployment.**
Use `execution_result` and its reported evidence/limitations; `--wait` does not
upgrade this to Azure success. Legacy environment deployment is also not the
captured-success promotion contract requested in D.

### Older launcher-based Full bootstrap

`bootstrap prepare/start/status` maps to `/api/v1/creation/bootstrap/*`;
SDK methods are `bootstrap_prepare`, `bootstrap_start`, `bootstrap_job`.
It is distinct from registered `creation_workflow_*`. Select only a genuinely
supported legacy launcher/version from capabilities, never as a blocked registered
workflow fallback. Legacy 124 is not a registered version fallback.

For an intentionally selected launcher flow, obtain an **operator-reviewed full
BootstrapPrepare JSON file** with `launcher`, `orchestrator` and complete `config`
matching `BootstrapConfig` and the capabilities. Its API-host `repo_root` must
satisfy the new/empty destination constraints:

If you first need account/team defaults from an existing wizard state, the
following is an optional **mapping operation**, not a launcher request or
deployment. Supply an actual approved state JSON file; do not treat the output
as a complete reviewed bootstrap configuration:

```powershell
$WizardStatePath = Read-Host 'Existing local JSON object containing approved wizard state'
if (!(Test-Path -LiteralPath $WizardStatePath -PathType Leaf)) { throw 'Provide the actual state file.' }
& $Python -m azurefactory bootstrap config --state-json $WizardStatePath --mapping-mode common-details
if ($LASTEXITCODE -ne 0) { throw 'Configuration mapping failed.' }
```

Its SDK equivalent is `bootstrap_config(state, mapping_mode="common-details")`;
REST uses `POST /api/v1/creation/bootstrap/config`. Merge only reviewed account
defaults into the independent new-factory request.

Then prepare the complete, separately reviewed launcher request:

```powershell
$LauncherRequestPath = Read-Host 'Existing local reviewed legacy BootstrapPrepare JSON path'
if (!(Test-Path -LiteralPath $LauncherRequestPath -PathType Leaf)) { throw 'Provide the real request.' }
$LauncherReceiptPath = Join-Path $ReviewRoot ('launcher-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory bootstrap prepare --request-json $LauncherRequestPath `
    --save-receipt $LauncherReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Legacy bootstrap preview blocked.' }
```

**STOP — this can provision common infrastructure and the initial project, create
identities/repositories, commit/push and dispatch pipelines.** Only after approval:

```powershell
& $Python -m azurefactory bootstrap start --receipt $LauncherReceiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect bootstrap outcome; do not repeat start.' }
$LauncherJobId = Read-Host 'Exact returned bootstrap job ID'
& $Python -m azurefactory bootstrap status --job-id $LauncherJobId --wait --poll-timeout 300
if ($LASTEXITCODE -ne 0) { throw 'Inspect outcome; timeout is not cancellation.' }
```

## F. APIM, Kong, AI Gateway SKU and Application Gateway

Do not translate a conceptual gateway box into invented deployment commands.
There is **no first-class APIM-versus-Kong choice**, gateway endpoint, corresponding
SDK deployment method, or complete hub/gateway route implied by these examples.
Existing APIM-related resource configuration must be discovered in the selected
published schema and reviewed through E; it is not a Kong switch.

Published accelerator change `81ec23d6` originally added these exact flags as
configuration-only, with disabled defaults:

| JSON/YAML name | GHA environment name |
|---|---|
| `enableAIFactoryMCP` | `ENABLE_AI_FACTORY_MCP` |
| `enableAIGatewaySKU` | `ENABLE_AI_GATEWAY_SKU` |
| `addAIFactoryMCP2AIGatewaySKU` | `ADD_AI_FACTORY_MCP_2_AI_GATEWAY_SKU` |

**Publication-time update:** later main commit `cf8437af` adds dedicated legacy
`config review` / `config save` options and opt-in ADO/GHA project-pipeline steps.
That source can host the read-only Factory MCP, create/adopt an AI Gateway and
register the MCP tool server for **project001 Dev**, subject to explicit images,
identity, private networking and other prerequisites. See the
[component contract at that source revision](https://github.com/jostrm/azure-enterprise-scale-ml/blob/cf8437af/usecase_code/40-agent-factory/45-aifactory-mcp-gateway/readme.md)
and [CLI options](https://github.com/jostrm/azure-enterprise-scale-ml/blob/cf8437af/environment_setup/azurefactory-cli/readme.md#mcp--ai-gateway-options-project001-dev).
This is **conditional/blocked** component execution, not a unified APIM-versus-Kong
selection API, installed-host certification or permission to upgrade a pin.
Setting these flags still only changes configuration; running the corresponding
approved pipeline is separate. False skips the new component step, not deletion.
The earlier claim that these flags have no pipeline bindings applies only to the
older `81ec23d6` baseline, not to current main after `cf8437af`.

Neither the flags nor this newer pipeline implementation certify full REST/SDK
field parity or implement a Kong selection. If the live settings
`field_keys` or selected parameter schema does not expose a flag, it is **not
supported there**; do not force an unknown setting or add a made-up CLI flag.

**Azure Application Gateway is different from APIM/Kong/AI Gateway.**
The creation input `enable_application_gateway` exists, but the registered
workflow prerequisite stage rejects an enabled Application Gateway because that
resource is outside its supported registered prerequisites. Configuration
acceptance must not be described as an executable Application Gateway route.

For removal of settings versus deployed resources, retained hub/VPN/bootstrap
dependencies, mixed-retention blockers and recovery, continue with
[20](20-cli-and-api-and-usage.md). No setting change here bypasses those controls.

## Evidence, version boundaries and validation

Implementation authority is current source/tests plus the actual host's OpenAPI
and capability responses, not the graph, a slide, a saved catalog or this guide.
This documentation was checked against original API/accelerator sources and the
explicitly approved publication copies at API `d52463f` and accelerator
`eb077742` (including the earlier `81ec23d6` gateway configuration change).
The gateway section additionally records the later published `cf8437af` delta
found during documentation publication; other examples retain their stated
parity baseline and live capability checks.
The separate offline consumer harness is at `56a324b`. The frozen external accelerator
source pin was **not changed**. Installed packages and selected immutable runtime
releases can lag or differ; no live provisioning/installation was performed.

Key local evidence:

- [CLI parser and dispatch](../../../environment_setup/azurefactory-cli/src/azurefactory/cli.py),
  [supported client methods](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py),
  [receipt/placement validation](../../../environment_setup/azurefactory-cli/src/azurefactory/review.py),
  [CLI tests](../../../environment_setup/azurefactory-cli/tests) and
  [canonical reference](../../../environment_setup/azurefactory-cli/readme.md).
- [API request examples and contracts](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md),
  [scenario JSON](../../../environment_setup/install_config_wizard/api-usage-examples/scenarios.json)
  and [canonical factory scope contract](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/docs/API.md).
- In the separate API checkout (`$ApiRoot`): `docs\API.md`, `docs\openapi.json`,
  `src\factory_catalog_models.py` (`CatalogPrepare`, `CatalogSummary`),
  `src\catalog_parameter_models.py`, `src\catalog_settings.py`,
  `src\creation.py`, `src\creation_workflow_models.py`,
  `src\creation_workflows.py`, `src\creation_workflow_authorization.py`,
  and `src\project_deployments.py`. These repository-relative paths are not
  assumed to exist beneath the accelerator.
- API regression evidence: `tests\test_catalog_auto_placement.py`,
  `tests\test_catalog_parameters.py`, `tests\test_creation_workflows.py`,
  `tests\test_creation_workflow_authorization.py`,
  `tests\test_project_deployments.py`; architecture notes
  `docs\architecture\patterns\Review-and-authorization.md` and
  `docs\architecture\contracts\API-and-external-clients.md`.
- Published gateway evidence:
  `environment_setup\unit-tests\test-bicep\unit\test_mcp_ai_gateway_flags.py`,
  template variables and `documentation\gh-io\docs\parameters\advanced.md`
  in the approved published accelerator source. Older local checkouts may not
  contain that published delta.

Bounded graph navigation reported original API fingerprint `de669aa8…` (566 files)
and ESML snapshot `ae9853f9…` (1,653 files, 23 partial-syntax files), current/fresh
at retrieval. Static/resolved edges are navigation, not runtime verification;
unresolved/boundary/inferred edges and architecture review staleness remain gaps.
No full graph/vault or cloud connector was loaded. Source/model/parser checks
validate documentation shape only; they do not validate real customer values,
permissions, networking, installed versions or deployment outcomes.
