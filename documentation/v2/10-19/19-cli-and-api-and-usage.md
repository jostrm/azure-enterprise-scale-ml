# 19. Add and update: choose the intent, then the interface

Start with [18 — connection, smoke checks and routing](18-cli-and-api-and-usage.md).
For removal and uncertain outcomes, use
[20 — removal and recovery](20-cli-and-api-and-usage.md).
Decide first between
[file-first variables.json editing and wrapper-first operations](18-cli-and-api-and-usage.md#choose-how-to-author-configuration-file-first-or-wrapper-first).
This chapter uses commands and API calls to save changes. You can supply JSON
request files, but do not edit the generated catalog files directly.
[17 — earlier overview](17-cli-and-api-and-usage.md) remains historical context;
use this chapter's limits on promotion and deployment success.

**Saved configuration is not deployed infrastructure.** A successful configuration
confirmation saves settings only (`job: null`). Deployment needs a separate
review and approval. Its confirmation can start pipelines, create billable
resources and publish Git changes. An accepted request or finished local command
does not by itself mean Azure deployment succeeded.

## Choose the intent

These labels describe the checked source version. **Your installed tools may
differ.** Run guide 18's compatibility checks; do not bypass a blocked operation.

| Scenario / intent | Support and boundary |
|---|---|
| **A. New AI factory, own hub/VPN, project001, selected Dev/Stage/Prod** | **implemented**: save selected scale sets and an initial project. **conditional/blocked**: deploying the hub/VPN and resources needs complete network settings and separate approval. The short example saves only part of that configuration. |
| **B. Add an AI Factory scale set** | **implemented**: `scaleset add` saves configuration. Adding a project and deploying are separate steps. An AI Factory scale set groups an environment, network and subscription; it is **not Azure Virtual Machine Scale Sets (VMSS)**. |
| **C. Put a project on the latest successful scale set** | **implemented**, opt-in: request `environment=latest-successful`. **not implemented**: choosing it automatically when placement is omitted. |
| **D. Promote captured successful Dev configuration/version to Stage, then Prod** | **not implemented**. You can choose a target, edit its settings and deploy separately. This does not copy a successful Dev deployment or require each environment to succeed before the next. |
| **E. Add/update settings or typed parameters; unset an override** | **implemented**: review and save parameters or legacy configuration. Catalog settings writes are **generic-access only**: use a general API request rather than a dedicated command. None of these deletes Azure resources. |
| **F. Choose APIM versus Kong for an AI gateway** | **not implemented** as one deployment choice. Newer source has **conditional/blocked** MCP/AI Gateway pipeline support. Application Gateway is a different product; its registered deployment workflow is blocked. |

Choose **CLI** for terminal commands, the **`AzureFactoryClient` SDK** for Python
helpers, or **REST** for direct HTTP requests from your application. All call the
same API and follow the same approval rules; see [18](18-cli-and-api-and-usage.md).
**Keep the API key out of browser code.**

<details>
<summary>More info</summary>

Use a trusted backend or automation worker for API calls. There are no SDK
methods named `scaleset_add`, `project_promote` or `gateway_deploy`.

</details>

## 1. Connection and exact target selection

Use Windows PowerShell **5.1+ or 7**. Run **guide 18's Window B setup in this same
shell** to set up the client tools. Before real-factory operations,
replace its demonstration URL/key through your approved secret mechanism with
the **actual owning API host and key**. Do not operate a real factory through the
public demonstration key or assume port 8876 is its real API address.
That setup defines `$ApiRoot`, `$AcceleratorRoot`,
`$Python = Join-Path $ApiRoot '.venv\Scripts\python.exe'`,
`PYTHONPATH` pointing to `environment_setup\azurefactory-cli\src`, and
`AIFACTORY_API_URL` / `AIFACTORY_API_KEY`. No console-script installation is assumed.

**Do not carry guide 18's empty-demo target into real work accidentally.** Choose
the actual existing catalog for B–F, or a separately approved new target for A.
All `folder`, `repo_root` and configuration import paths sent to the API refer to
the **API host**. Request files and receipts in this tutorial are **client-local**.
The API still restricts these administrative calls to local-host access.
For A, the chosen new `azurefactory` directory must already exist and be empty;
have the API-host operator create that directory first. For B-F select an
existing registered root, not the empty smoke-test directory.

Run these helper definitions once. They are PowerShell functions for this guide,
not extra SDK methods. Store reviews under private local application data,
outside Git checkouts, replaceable templates and temporary cleanup areas.
Saved reviews and responses may contain sensitive settings. Check that only
authorized people can read the folder.

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

Choose the exact IDs displayed by the API, not the first item in a list.
`DEV/001`, `STAGE/001` and `PROD/001` are different scale sets.

<details>
<summary>More info</summary>

The helper uses `[0]` only after matching the requested ID and checking there is
exactly one result. UUIDs identify objects; `001` is a project number or scale-set
suffix. API environment values are `dev`, `stage`, `prod`; some Azure names use
`test` for Stage.

</details>

## 2. Shared three-interface prepare → review → confirm

For each scenario below:

1. Run its input example to set `$Request` and `$Operation`.
2. Run **2.1** to create new local request and review files.
3. Choose **one** prepare alternative: that scenario's friendly CLI command,
   **2.2 SDK**, or **2.3 REST**.
4. **STOP** and review. Only after approval choose **one** confirmation in **2.4**.

Do not run all alternatives against the same target. They are equivalent choices,
not sequential steps. Read the catalog again after every saved change.

### 2.1 Serialize the selected scenario

This step saves the selected request as JSON. Supported operations are `factory-create`, `factory-clone`,
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

The example prepares a change, checks the preview and saves a review file.
It does **not** approve or start the change.

<details>
<summary>More info</summary>

`factory_create_prepare` and `parameter_prepare` return previews that still need
checking. `validate_preview` and the receipt helper perform those checks.
`review_catalog_prepare` also checks the selected target for automatic placement.

</details>

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
below, not `catalog confirm --receipt` on this file. Check the target and recorded
results yourself; the script's checks do not replace your review or the API's checks.

<details>
<summary>More info</summary>

A REST-only application must keep its saved review tied to the exact request and
API host. It does not need the Python SDK to send HTTP requests.

</details>

**STOP — review and approve this exact preview.** Check the target folder, IDs,
environment, tenant/subscription, version, changes, network ownership, warnings
and expiry. For automatic placement, check the chosen scale and its successful
deployment records. **`can_execute: true` is not approval.** Keep review files private.

<details>
<summary>More info</summary>

Also check contract 1, configuration versus runtime mode and the resolved source
commit. Receipts expire and apply only to the reviewed target. Their checksums
detect changes to the file; they are not signatures or user approval.

</details>

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
The server rechecks who prepared the change, whether anything changed, the expiry
and the saved plan. Approval can be used only once. No CLI receipt or Python
helper is needed.

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

After saving configuration, read the catalog again and check the **exact IDs and
changes**. **If a write fails, times out or loses its response, inspect the saved
state before doing anything else. Do not repeat it or switch tools to retry it.**

<details>
<summary>More info</summary>

Catalog responses use `revision`; parameter responses and previews use
`source_revision`. Use the matching field, not a guessed or old value.

</details>

## A. New factory + selected environments + project001

Choose one or more of **Dev, Stage and Prod**, with one scale set per environment.
This saves one initial project001 and its selected locations. Use a new factory
key/prefix/region combination. If a draft already exists, inspect it; creation
does not update or reopen it.

The own-hub setting below saves your choice only. It does **not** supply all
VPN, network, identity, repository or runner settings. Review
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

Run **2.1**, then choose this **CLI prepare**, **2.2 SDK** or **2.3 REST**.

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
Do not run `project add --number 001` afterward.

Creating Stage/Prod **configuration**, or GitHub environments named `Dev`, `Stage`,
`Prod`, does not deploy those environments. The registered bootstrap workflow
deploys its selected initial Dev target. This short request does not deploy three
complete environments at once.

<details>
<summary>More info</summary>

The SDK example uses `factory_create_prepare`; REST sends a `CatalogPrepare`
request. On supported APIs, omitting the initial-project object also defaults to
project001. This example chooses its locations explicitly. `--common-only` instead
requests configuration without an initial project.

</details>

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
Check the new IDs, network addresses, copied settings and pipeline connection
before a separate deployment review. A saved clone is not a deployed factory.

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

**STOP**, then approve and confirm using **2.4**. This saves settings only; it does
not deploy VMSS, shared infrastructure or a project. Read the catalog again and
select the new scale UUID before another operation.

<details>
<summary>More info</summary>

The SDK uses `review_catalog_prepare` with `action: "create-scale-set"`.
There is no dedicated `scaleset_add` SDK method.

</details>

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

**STOP**, then **2.4** after approval. For SDK/REST, send the same request through
**2.2/2.3**. Saving the scale and saving the project are separate changes, not one
all-or-nothing step. Deployment comes later.

<details>
<summary>More info</summary>

The server checks project-number conflicts in the selected locations and layout-2
project home. Do not add a different factory-wide uniqueness rule.

</details>

## C. Explicit latest-successful placement

**Implemented opt-in; not default behavior.** Build the new-project request in B.
Then, **before 2.1 or any prepare**, change its placement choice:

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
if ($LASTEXITCODE -ne 0) { throw 'Automatic placement is blocked; review the reported deployment checks.' }
```

The chosen existing scale in the input helper identifies
the requested environment, **not** the final automatic target.

The API chooses a scale with recorded successful **common** deployment results
for the requested factory, environment and version, with room for the project.
It does not simply choose the highest suffix. Saved drafts, a list of resources,
a finished local command or `submitted` do not count as deployment success.

<details>
<summary>More info</summary>

Selection uses recorded deployments, not a fresh scan of all Azure resources.
Review `latest-successful-placement-v1` and `resolved_placements`, including the
exact UUID, source commit, completed job and `evidence_hash`. The CLI, receipt
checks and `review_catalog_prepare` reject missing or conflicting selection details.

</details>

**STOP**, then approve the chosen target through **2.4**. Confirmation does not
silently switch to a newer scale. If no scale qualifies, stop; that is not
permission to create one or guess an ID. Omitting `--placement` fails; it does
not mean latest-successful. The same explicit selector is supported on
`project add-placements` by replacing D's placement value, but is not promotion.

## D. Explicit Stage/Prod placement is not captured promotion

**Not implemented:** copying a saved snapshot of a successful Dev deployment,
including its settings and version, through Stage and Prod. There is no
`project promote` command or `project_promote` SDK method. `--version-ref` chooses
code; it does not copy settings, data, models or a previous deployment's success.

Instead, create the target scale with B if needed, add the project's target
location below, edit **target** parameters with E, then deploy separately.
Each step needs its own review.

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

**STOP**, then **2.4** after approval. For Prod, choose and review the target again.
This does not automatically require Stage to have succeeded.
Do not use legacy deployment to bypass a blocked catalog operation.

## E. Add/update a parameter, unset an override, or edit settings

### Typed resource parameters — all three interfaces

Read the available parameters for the actual target and version. Do not guess
names from a slide or old template. For common-only
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

**STOP**, then use the parameter confirmation in **2.4** after approval.
Only the chosen values change. `unset` removes a saved override, so an inherited
or default value may apply instead. It is not the same as `null`.
**Neither `unset` nor a disabled resource flag promises to delete an Azure
resource.** Use a separate deployment review, or guide 20 for removal.

**Do not use `--reset-profile` just to get past an error.** `reset_profile`
discards **all old protected parameter settings in that scale set**, even when
`project_id` selects one project. Review that wider loss of settings separately.

<details>
<summary>More info</summary>

SDK read equivalent: `client.catalog_parameters(folder, factory_id, scale_set_id,
project_id)`. REST read equivalent: `GET /api/v1/factory-catalog/parameters` with
those exact query names. Guide 18 shows read-request mechanics. The complete
prepare/confirm alternatives above share the parsed schema revisions; no helper
installation or hand-built JSON string is required.

</details>

### Catalog settings — generic-access only

`catalog settings` / `catalog_settings` only **reads** settings. There is no
`settings set` command; use a general API request with
`action: "configure-settings"`. This flow saves a plain preview, **not a receipt
you can pass to CLI `catalog confirm`**.

Choose the target, read `field_keys` and `revision`, and send only the values you
want to replace. Do not include secrets. This example changes scale-level
settings; factory identity, network addresses and version use separate operations.

<details>
<summary>More info</summary>

Settings accept individual scalar values, not arbitrary nested objects. For
project settings, add a checked `project_id`; for factory settings, omit
`scale_set_id`. The specialized catalog receipt helper has no settings operation
label, so do not invent one.

</details>

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

**STOP — review the settings, target, revision and expiry, then obtain approval.**
The server checks that the saved preview still applies. Do not edit or silently
replace that preview. Only after approval:

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

These advanced actions are **generic-access only**: use general API requests,
not dedicated CLI commands. They need the same separate review and confirmation
as settings changes.

<details>
<summary>More info</summary>

Use `POST /api/v1/factory-catalog/prepare` with a `CatalogPrepare` request,
then separately approve `/confirm`. Save plain API previews, as above; do not
invent a specialized `write_receipt` operation. Check the selected host's OpenAPI
for required fields and allowed combinations.

| Action | When to choose it | Scope / boundary |
| --- | --- | --- |
| `migrate` | Register legacy configuration, or copy it into a separate empty modern folder | Same-folder registration uses `folder`; copying uses destination `folder` plus `source_folder`. Preserve UUIDs/source files. Never let both copies independently change the same Azure targets. This does not prove ownership of deployed resources. |
| `correct-draft-scale-identity` | Fix a tenant/subscription on an eligible empty draft | Supply `factory_id`, `scale_set_id`, `expected_revision` and `draft_identity` with tenant/subscription UUIDs. Targets with bindings, ownership, project placements or previous execution are blocked. This does not move deployed resources. |
| `configure-binding` | Save a reviewed pipeline connection | Supply the exact factory and a `RuntimeBinding`. Use the enrollment steps below rather than guessing repository, runner, identity or coordination settings. |

The SDK uses `catalog_prepare(parsed_body)` and `catalog_confirm(folder,
confirmation_id)`. The generic CLI uses `request POST` with `--body-json`,
`--write --yes`; these flags acknowledge that single HTTP request, not approval
for a later deployment. General API requests still follow the server's safety checks.

</details>

## Separate runtime deployment — after configuration approval

Use this to deploy the selected target after B/D/E. **It is not captured
promotion.** The API checks the pipeline connection, permissions, ownership,
version, runner and networking. A saved configuration does not mean those checks
will pass.

<details>
<summary>More info</summary>

Runtime preparation uses `action: "deploy"`. Common-only, GHA and shared-remote
deployment need compatible runtime support, including coordination and exact
deployment identity checks. Do not switch routes to bypass a blocker.

</details>

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

For B's **common-only** scale-set deployment, use these inputs **instead of**
the project inputs above, then run **2.1** and the following CLI command
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

**STOP — this approval starts deployment, not just a configuration save.**
Only after approval use **2.4**, whose CLI branch is `runtime confirm`. Omitting
`project_id` deliberately selects common-only deployment, not every project; use
that only with a separately reviewed supported common route.

Check the returned job, then follow its exact ID:

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

**A timeout stops waiting; it does not cancel deployment.** Check the pipeline's
deployment results, exact version/target and catalog status before claiming success.

<details>
<summary>More info</summary>

SDK status calls are `catalog_job(folder, job_id)` / `catalog_terminal(folder,
job_id, cursor)`; REST is `GET /api/v1/factory-catalog/jobs/{job_id}?folder=...`
and `/api/v1/factory-catalog/terminal` with `folder`, `job_id`, `cursor`.

</details>

## Registered Full bootstrap

**Conditional/blocked**: provide complete settings reviewed by the operator.
Use `bootstrap workflow ...`, not the older `bootstrap ...` launcher commands.
This workflow can set up its own prerequisites; advanced manual enrollment is
not always needed. **It can create billable resources, identities, groups,
networks and runners, create repositories, commit/push and start pipelines.**
Do not use another route to bypass a blocker.

First save the factory configuration through A or the registered creation API.
**Do not recreate an existing factory to switch routes.**

<details>
<summary>More info</summary>

The registered creation API is **generic-access only** in CLI/SDK:
`POST /api/v1/creation/prepare`, then separately approved `/creation/confirm`.
It is not `bootstrap_prepare`, which calls the legacy launcher API.

</details>

### Discover and provide the complete bootstrap configuration

```powershell
& $Python -m azurefactory bootstrap capabilities
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect bootstrap capabilities.' }
& $Python -m azurefactory schema --openapi
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect bootstrap schema.' }
```

Use the commands above to check required fields, defaults and supported regions.
Provide a real, complete JSON configuration file reviewed by the operator—not a
sample with placeholder accounts or network addresses.

<details>
<summary>More info</summary>

Read `bootstrap_fields` (including `required`) in capabilities and
`BootstrapConfig` / `WorkflowBootstrapConfig` / `CreationWorkflowPrepare` in the
live OpenAPI. The API reference is `$ApiRoot\docs\API.md`. Required keys include
`subscription_id`, `tenant_id`, `scale_set_number`, `repo_root`,
`team_member_email`, `team_group_name`; route validation adds the GHA repository
or ADO organization/project/repository/service connection and ADO connected tenant.
A supplied existing team-group ID does not remove the current API's required
team name/member-email fields.

</details>

For A's **owned** hub/VPN, explicitly review `setup_hub_access: true`,
`access_hub_mode: "integrated"`, Dev VNet CIDR and `vpn_client_cidr`, DNS/network
ownership, region, subscription, project001, repository, identity and runner.
Integrated mode does not need an invented second hub VNet. External hub mode is
different. **This does not install a VPN client or check your workstation's
connection.** Hosted runners need suitable private-network access.

Choose `coordination_mode` deliberately. `single-writer` requires a private
repository and an approved setup where only one writer changes the factory;
`blob` has separate coordination/network requirements. **Do not change an existing
binding's mode just to unblock deployment.** The file below is supplied by your
operator after review; it is not included with this guide.

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

The script's local checks are not a full Azure check. Server preflight reads
Azure/provider state but **does not approve or start deployment**. Its cost
estimate may be incomplete; it is not a spending limit.

<details>
<summary>More info</summary>

An equivalent CLI entry point accepts the workflow request itself; choose this
instead of the preceding `preflight` call, not as another approval step:

```powershell
$AlternateReportPath = Join-Path $ReviewRoot ('preflight-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory bootstrap workflow prepare --preflight `
    --request-json $WorkflowRequestPath --save-report $AlternateReportPath
if ($LASTEXITCODE -ne 0) { throw 'Readiness is blocked or incomplete; this created no workflow approval.' }
```

</details>

### Per-stage workflow: prepare, approve, observe, next

```powershell
$WorkflowReceiptPath = Join-Path $ReviewRoot ('stage-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory bootstrap workflow prepare --request-json $WorkflowRequestPath `
    --save-receipt $WorkflowReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Workflow preparation blocked.' }
```

**STOP — review and approve this stage's target, version, commands, changes and expiry.**
Only then:

```powershell
& $Python -m azurefactory bootstrap workflow start --receipt $WorkflowReceiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect workflow state; do not repeat start.' }
$WorkflowReceipt = Get-Content -LiteralPath $WorkflowReceiptPath -Raw | ConvertFrom-Json
$WorkflowId = $WorkflowReceipt.preview.workflow_id
& $Python -m azurefactory bootstrap workflow status --folder $FactoryFolder --workflow-id $WorkflowId
if ($LASTEXITCODE -ne 0) { throw 'Inspect the reported workflow boundary.' }
```

Check status until the server reports `requires_review: true`. A finished local
command does not mean the next stage is ready. Then prepare a new review:

```powershell
$WorkflowReceiptPath = Join-Path $ReviewRoot ('stage-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory bootstrap workflow next --folder $FactoryFolder `
    --workflow-id $WorkflowId --save-receipt $WorkflowReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'No confirmable next stage.' }
```

**STOP again.** Review this new stage before separately using the earlier `start`
command with this new receipt. Never automate a loop that approves every stage.
One completed stage or queued job does not mean the entire factory is deployed.

### Optional bounded whole-workflow approval

Optionally approve the listed workflow stages together, instead of one at a time.
This is a separate choice—not an extra step after per-stage preparation:

```powershell
$WorkflowReceiptPath = Join-Path $ReviewRoot ('whole-workflow-' + [guid]::NewGuid().ToString('N') + '.json')
& $Python -m azurefactory bootstrap workflow prepare --whole-workflow `
    --request-json $WorkflowRequestPath --save-receipt $WorkflowReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Bounded approval unsupported/blocked; no silent fallback.' }
```

**STOP.** Review all listed stages, targets, changes, expiry and the cost estimate.
Only after approval run `bootstrap workflow start` above. The server then manages
the approved stages; do not build a script that blindly approves later steps.
**Changed inputs, expired approval, failure or an uncertain result mean stop and
review the state.**

<details>
<summary>More info</summary>

Check `review.workflow_authorization`, contract `bounded-full-bootstrap-v1`,
the source/program/template fingerprints, expiry and hash.
`review.cost_preview` is an estimate, not a spending limit.

</details>

Use the following command **only when the server says the workflow can safely
continue**. It resumes the existing approval; it is not a retry for a failed or
running stage:

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

For an application using SDK or REST, the equivalent calls are below.

<details>
<summary>More info</summary>

Use the same reviewed JSON. For SDK receipt handling, use `write_receipt` /
`load_receipt` with purpose `creation-workflow-start`, operation
`creation-workflow` before approval/start. This also checks whole-workflow
approval hashes; `validate_preview` alone does not perform that check.

| Step | Supported SDK | HTTP contract |
|---|---|---|
| Capabilities | `creation_capabilities()` | `GET /api/v1/creation/capabilities` |
| Read-only preflight | `preflight(parsed_preflight_request)` | `POST /api/v1/creation/preflight` |
| Prepare | `creation_workflow_prepare(parsed_workflow_request)` | `POST /api/v1/creation/workflows/prepare` |
| Start | `creation_workflow_start(folder, workflow_id, confirmation_id, authorization_hash=reviewed_hash)`; omit hash for per-stage | `POST /api/v1/creation/workflows/start`: `folder`, `workflow_id`, `confirmation_id`, optional `authorization_hash` |
| Status | `creation_workflow_status(folder, workflow_id)` | `GET /api/v1/creation/workflows/{id}` with `folder` query |
| Next review | `creation_workflow_next(folder, workflow_id)` | `POST /api/v1/creation/workflows/{id}/prepare-next`: `{"folder": ...}` |
| Safe continuation only | `creation_workflow_continue(folder, workflow_id, authorization_hash)` | `POST /api/v1/creation/workflows/{id}/continue`: `folder`, original `authorization_hash` |

</details>

## Advanced enrollment is a separate local-core workflow

These optional commands set up a pipeline connection using local Azure/provider
tools. **They are not a replacement for Full bootstrap or workload deployment,
and there is no matching REST/`AzureFactoryClient` enrollment flow.**
`plan` reads cloud state; **`ensure` can create billable resources and grant roles**.
An administrator must first arrange that writers do not make conflicting changes.

<details>
<summary>More info</summary>

Use `enrollment plan`, `ensure` and `plan-and-publish` only with explicitly
authenticated tools, a schema-2 consumer repository and the exact registered
target. They do not create every runner/network resource. Read the options schema and
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

The governance flag confirms that an administrator has already arranged safe,
nonconflicting writes. It does not set that up. Do not use it if that is untrue.

**STOP — independently approve the plan, role scopes, resource creation, hashes
and limitations.** Only then:

```powershell
& $Python -m azurefactory enrollment ensure --plan $PlanPath --yes `
    --acknowledge-exclusive-writer-governance --save-result $EnrollmentResultPath
if ($LASTEXITCODE -ne 0) { throw 'Inspect enrollment outcome; do not re-plan/retry automatically.' }
```

Ensure returns a proposed pipeline connection (**binding candidate**), not a
deployment. Review saving that connection separately:

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

`plan-and-publish` combines enrollment and saving the connection. It is an
alternative, **not an extra step after the sequence above**. With the same inputs
and safe-writer setup, first review its read-only plan (exit 3 means approval required):

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
It must not change an existing binding's mode, rewrite the register to fit, guess
the subscription from the current account, or bypass shared-hub safety rules.

</details>

## Legacy configuration and legacy deployment are separate contracts

Use this only for a real legacy `aifactory` root, not an `azurefactory` catalog.
Choose the exact saved JSON project. Let the tools preserve its `_json_source`
metadata; do not edit that metadata, identity fields or private fields yourself.

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

**STOP — check the changed values, `review_id`, `can_save`, warnings and what will
be saved.** Only after approval:

```powershell
$ReviewId = Read-Host 'Exact approved review_id from config review'
& $Python -m azurefactory config save --folder $LegacyFolder --project-number $LegacyProject `
    --changes-json $LegacyChangesPath --expected-review $ReviewId --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect persistent state; never blindly repeat save.' }
```

**This saves configuration; it does not deploy or commit/push.** Normally it also
writes pipeline variable files. If you want only a snapshot, review that choice
and use `--snapshot-only` on **both** review and save.

<details>
<summary>More info</summary>

The supported SDK helper is
[`ConfigurationDraft.load/review/save`](../../../environment_setup/install_config_wizard/api-usage-examples/python/edit_configuration.py).
Its HTTP calls are `/api/v1/projects/load`, `/validation`,
`/export` without a path for review, then separately approved `/projects/save`.
`/startup/load` is a hint, not exact project selection; preserve `_json_source`.

</details>

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

**STOP — review the deployment preview (contract 2)**, including the saved draft,
project, source/target, patch choice and version. Only after approval:

```powershell
& $Python -m azurefactory legacy start --receipt $LegacyReceiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect the legacy execution result; do not repeat start.' }
$LegacyJobId = Read-Host 'Exact job ID returned by this start'
& $Python -m azurefactory legacy status --folder $LegacyFolder --job-id $LegacyJobId `
    --wait --poll-timeout 300 --poll-interval 2
if ($LASTEXITCODE -ne 0) { throw 'Inspect the result; timeout does not cancel the job.' }
```

**`submitted` means the local launcher finished, not that Azure deployment
succeeded.** Check `execution_result` for recorded results and limitations.
`--wait` does not change that meaning. This is also not the captured-success
promotion requested in D.

<details>
<summary>More info</summary>

| Legacy stage | SDK | REST |
|---|---|---|
| Plan | `project_deployment_plan(body)` | `POST /api/v1/operations/project-deployments/plan` |
| Prepare | `project_deployment_prepare(body)` | `POST /api/v1/operations/project-deployments/prepare` |
| Start | `project_deployment_start(folder, confirmation_id)` | `POST /api/v1/operations/project-deployments/start` |
| Observe | `project_deployment_terminal(folder, job_id, cursor)` | `GET /api/v1/operations/project-deployments/terminal` |

</details>

### Older launcher-based Full bootstrap

Use this older flow only when you deliberately need a supported legacy launcher.
**Do not use it to bypass a blocked registered workflow.** Check capabilities for
the supported launcher/version; legacy 124 is not a registered-version fallback.
It can create resources, commit/push and start pipelines.

<details>
<summary>More info</summary>

`bootstrap prepare/start/status` uses `/api/v1/creation/bootstrap/*`;
SDK methods are `bootstrap_prepare`, `bootstrap_start`, `bootstrap_job`.
These are separate from registered `creation_workflow_*`.

Get an **operator-reviewed full BootstrapPrepare JSON file** with `launcher`,
`orchestrator` and complete `config` matching `BootstrapConfig` and capabilities.
Its API-host `repo_root` must be a permitted new/empty destination.

If you first need account/team defaults from an existing wizard state, the
following optional step copies those defaults only; it does not deploy anything.
Supply a real approved state JSON file. Its output is not a complete bootstrap
configuration:

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

</details>

## F. APIM, Kong, AI Gateway SKU and Application Gateway

**Not implemented:** one command or API option to choose APIM versus Kong.
These examples do not provide a gateway deployment method or a complete
hub/gateway setup. For existing APIM settings, check the selected version's
available parameters and follow E; that is not a Kong switch.

These gateway settings default to disabled:

| JSON/YAML name | GHA environment name |
|---|---|
| `enableAIFactoryMCP` | `ENABLE_AI_FACTORY_MCP` |
| `enableAIGatewaySKU` | `ENABLE_AI_GATEWAY_SKU` |
| `addAIFactoryMCP2AIGatewaySKU` | `ADD_AI_FACTORY_MCP_2_AI_GATEWAY_SKU` |

**Conditional/blocked:** newer source adds legacy `config review` / `config save`
options and optional ADO/GHA pipeline steps for **project001 Dev**. With the
required images, identity and private networking, these can host the read-only
Factory MCP, create/adopt an AI Gateway and register its MCP tool server.
**Saving the flags only changes configuration. Starting the approved pipeline is
separate. Setting a flag to false skips the new step; it does not delete resources.**

This still does not add an APIM-versus-Kong choice. If the live `field_keys` or
parameter schema does not list a flag, it is **not supported there**. Do not force
unknown settings or invent CLI options.

<details>
<summary>More info</summary>

The original `81ec23d6` change added configuration-only flags. The later
`cf8437af` commit added the component pipeline support described above. See the
[component contract at that source revision](https://github.com/jostrm/azure-enterprise-scale-ml/blob/cf8437af/usecase_code/40-agent-factory/45-aifactory-mcp-gateway/readme.md)
and [CLI options](https://github.com/jostrm/azure-enterprise-scale-ml/blob/cf8437af/environment_setup/azurefactory-cli/readme.md#mcp--ai-gateway-options-project001-dev).
The earlier claim that these flags have no pipeline bindings applies only to the
older `81ec23d6` version, not to main after `cf8437af`.

This does not prove your installed API supports every REST/SDK field, implement
Kong selection or give permission to change a source pin.

</details>

**Azure Application Gateway is different from APIM/Kong/AI Gateway.**
The creation input `enable_application_gateway` exists, but the registered
workflow blocks it: that workflow does not implement its deployment.
Accepting the setting does not mean Application Gateway can be deployed this way.

For deleting resources, keeping shared hub/VPN resources and recovering from
uncertain results, continue with [20](20-cli-and-api-and-usage.md).
Changing a setting does not bypass deletion safety checks.

<a id="evidence-version-boundaries-and-validation"></a>

## Sources, versions and checks

**Check your installed version before using an example.** The actual API's
capabilities and supported request fields matter. Documentation checks do not
prove that your permissions, networking or deployment will work.

<details>
<summary>More info</summary>

Current source/tests and the actual host's OpenAPI and capabilities define
supported behavior. A graph, slide or saved catalog cannot prove deployment.
This guide was checked against original API/accelerator sources and the
explicitly approved publication copies at API `d52463f` and accelerator
`eb077742` (including the earlier `81ec23d6` gateway configuration change).
The gateway section also covers the later published `cf8437af` changes.
Other examples keep their stated version checks.
The separate offline consumer harness is at `56a324b`. The frozen external accelerator
source pin was **not changed**. Installed packages and selected immutable runtime
releases can lag or differ; no live provisioning/installation was performed.

Source and test references:

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
- API tests: `tests\test_catalog_auto_placement.py`,
  `tests\test_catalog_parameters.py`, `tests\test_creation_workflows.py`,
  `tests\test_creation_workflow_authorization.py`,
  `tests\test_project_deployments.py`; architecture notes
  `docs\architecture\patterns\Review-and-authorization.md` and
  `docs\architecture\contracts\API-and-external-clients.md`.
- Published gateway references:
  `environment_setup\unit-tests\test-bicep\unit\test_mcp_ai_gateway_flags.py`,
  template variables and `documentation\gh-io\docs\parameters\advanced.md`
  in the approved published accelerator source. Older local checkouts may not
  contain that published delta.

The limited graph lookup reported original API fingerprint `de669aa8…` (566 files)
and ESML snapshot `ae9853f9…` (1,653 files, 23 partial-syntax files), current/fresh
at retrieval. Graph links help find source files; they do not verify running
deployments. Some links and older architecture notes remain incomplete or uncertain.
No full graph/vault or cloud connector was loaded. Source/model/parser checks
validate documentation shape only; they do not validate real customer values,
permissions, networking, installed versions or deployment outcomes.

</details>
