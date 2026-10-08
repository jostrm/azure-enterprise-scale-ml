# 20. Remove, observe and recover: CLI, REST and Python SDK

Continue from [18 — setup](18-cli-and-api-and-usage.md), in the **same PowerShell
Window B**. [19 — ADD and UPDATE](19-cli-and-api-and-usage.md) covers configuration
and deployment. [17 — overview](17-cli-and-api-and-usage.md) remains the general
guide. This chapter separates **removing configuration** from **deleting Azure
resources**; neither a saved setting nor a successful HTTP response proves that
Azure resources were deleted.
For users who prefer editing files, first read
[file-first versus wrapper-first configuration](18-cli-and-api-and-usage.md#choose-how-to-author-configuration-file-first-or-wrapper-first).
Deleting a JSON key or setting a service flag to false does **not** approve or
perform resource deletion.

## 1. Choose what you want to remove

These labels describe the available commands and API features. Your installed
version and factory still need to pass their own checks.

| What you want to do | Command or API action | Support and effect |
|---|---|---|
| Remove a custom parameter value | `parameters prepare --unset`; `ParameterPatch.unset` | **implemented**, settings only; confirm separately. Uses defaults or inherited values where available. No Azure deletion. |
| Reset a saved parameter profile | `parameters prepare --reset-profile`; `reset_profile` | **implemented**, settings only; review replacement settings against the current version. Not “reset Azure”. |
| Remove never-deployed local configuration | `draft remove`; `draft_remove_prepare` | **implemented**, checked local removal with an archive; no Azure deletion or pipeline start. |
| Finish local cleanup after a confirmed whole-factory deletion | Named `delete-aifactory reconcile` | **implemented**, uses saved, verified completion records. Does not restart pipelines or retry Azure deletion. |
| Delete one project's resources in selected environments | `project delete`; `project_delete_prepare`; action `delete-project` | **implemented** preparation; **conditional/blocked** execution until the layout, installed features, resource ownership, permissions and deployment setup pass checks. |
| Delete a selected scale set's Azure resources | `scaleset delete`; `scaleset_delete_prepare`; action `delete-scale-set` | **implemented** preparation; **conditional/blocked** execution. Review the exact list of resources to delete or keep; not every resource group is necessarily deleted. |
| Delete an entire factory's reviewed Azure resources | `delete-aifactory prepare/confirm/status/reconcile` and named API/SDK methods | **implemented** interface; **conditional/blocked** execution. Requires compatible software; all project deletion pipelines finish before shared resources are removed. |

The named project, scale-set and draft commands **prepare only**. A separate
confirmation needs approval. General request commands remain an alternative.

**not implemented:** automatic “disable flag = delete” behavior, keeping selected resources inside groups being
deleted by the whole-factory command, or a generic force/retry/cancel-on-timeout
workflow. Never switch to legacy deployment or direct Azure deletion to bypass
a blocker.

### Check compatibility before you start

A newer CLI does not automatically upgrade the API or deployment software.
Whole-factory deletion currently supports **Azure Blob storage coordination**;
single-writer support for other deletions does not make this command available.
The API checks compatibility and will block unsupported combinations. Do not
change coordination mode to work around a failed check.

Preparation can read real host, pipeline-provider and Azure information; it is
not an offline simulation. Preflight checks readiness without making changes,
but **does not approve deletion**. The optional offline tests in chapter 18 use
test data. You do not need to run them or start a demo API to use an already
approved host.

<details>
<summary>More info</summary>

#### Reviewed software versions and compatibility checks

This chapter uses the published API baseline at `d52463f`, the earlier accelerator
deletion-plan validator/reconcile methods, and named CLI/SDK preparation wrappers
at `0da0d85b`. A different local checkout or packaged sidecar may lack these methods.
The API's frozen accelerator pin
`3e9102ee07c959d91e5ac508432bd1545d258a15` is **not changed by this guide** and
does not supply the named ordered-pipeline execution contract. A publication of
new client code does not upgrade that pin or an operator's selected runtime.

The published accelerator source contains the ordered-pipeline implementation
and advertises `factory_deletion_pipeline_coordination_modes: ["blob"]`.
Generic single-writer whole-owned-group deletion support is **not** named ordered
pipeline support and is **not** selective project deletion. The API must check the
selected immutable source and the actual enrolled coordination mode. There is no
automatic switch from single-writer to Blob coordination.

</details>

## 2. Set up and select your factory

Chapter 18's mandatory Window B setup initializes `$ApiRoot`, `$AcceleratorRoot`,
`$Python = Join-Path $ApiRoot '.venv\Scripts\python.exe'`,
`$env:PYTHONPATH = Join-Path $AcceleratorRoot 'environment_setup\azurefactory-cli\src'`,
and `AIFACTORY_API_URL`/`AIFACTORY_API_KEY`. Do not assume that a global
`azurefactory` executable is installed.

The standalone demonstration uses loopback port `8876`; its empty demonstration
root and public example key are **not a real deletion environment**. Before this
chapter, set `AIFACTORY_API_URL` and `AIFACTORY_API_KEY` through your approved
mechanism to the real owning host and identity; do not reuse the demonstration key.
Connect only to that approved host and enter its actual registered folder.
Every API `folder` is a path **on the computer running the API**, not a file
upload. Check the tenant, subscription, factory, scale set and project carefully;
`DEV/001` and `STAGE/001` are different targets.

Run this local setup once per separately reviewed scenario. It creates a unique
review directory under your local application data, outside Git checkouts,
replaceable template folders and the operating-system temporary directory.
Keep it private: saved review files (receipts) and resource lists may contain
sensitive identifiers. If an operation's result is uncertain, keep its files
and results rather than cleaning them up automatically.

```powershell
$ErrorActionPreference = 'Stop'
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) { throw 'Complete chapter 18 Window B setup.' }
if (-not $env:AIFACTORY_API_URL -or -not $env:AIFACTORY_API_KEY) { throw 'Set the authorized API URL/key.' }
$BaseUrl = $env:AIFACTORY_API_URL.TrimEnd('/')
$Folder = Read-Host 'Exact registered factory folder on the API host (not the empty demo root)'
if ([string]::IsNullOrWhiteSpace($Folder)) { throw 'An explicit folder is required.' }
$ReviewBase = Join-Path $env:LOCALAPPDATA 'AzureFactory\reviews'
$null = New-Item -ItemType Directory -Path $ReviewBase -Force
$ReviewDir = Join-Path $ReviewBase ('remove-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $ReviewDir
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
function Write-NewJson([string]$Path, $Value) {
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite $Path" }
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 100), $Utf8NoBom)
}
$CatalogPath = Join-Path $ReviewDir 'catalog.json'
```

**Choose ONE way to list your factories**, not all three.

### CLI

```powershell
$Raw = & $Python -m azurefactory catalog list --folder $Folder
if ($LASTEXITCODE -ne 0) { throw 'Catalog read failed.' }
$Catalog = ($Raw -join "`n") | ConvertFrom-Json
Write-NewJson $CatalogPath $Catalog
$Catalog | ConvertTo-Json -Depth 100
```

### REST

```powershell
$Raw = & curl.exe --silent --show-error --fail-with-body --noproxy "*" --get `
    "$BaseUrl/api/v1/factory-catalog" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    --data-urlencode "folder=$Folder"
if ($LASTEXITCODE -ne 0) { throw 'Catalog read failed.' }
$Catalog = ($Raw -join "`n") | ConvertFrom-Json
Write-NewJson $CatalogPath $Catalog
$Catalog | ConvertTo-Json -Depth 100
```

### Python SDK

```powershell
@'
import json, sys
from azurefactory import AzureFactoryClient
result = AzureFactoryClient().catalog_list(sys.argv[1])
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, indent=2))
'@ | & $Python - $Folder $CatalogPath
if ($LASTEXITCODE -ne 0) { throw 'Catalog read failed.' }
$Catalog = Get-Content -Raw -LiteralPath $CatalogPath | ConvertFrom-Json
```

Now explicitly select the intended factory from that response:

```powershell
$FactoryId = Read-Host 'Exact factory UUID from the catalog above'
$Matches = @($Catalog.factories | Where-Object { $_.id -eq $FactoryId })
if ($Matches.Count -ne 1) { throw 'Select exactly one returned factory UUID.' }
$Factory = $Matches[0] # Exact UUID match, never an implicit first catalog item.
$Revision = $Catalog.revision
$Factory | ConvertTo-Json -Depth 100
$Kind = 'catalog'
$ExpectedMode = 'configuration'
$PrepareRoute = '/api/v1/factory-catalog/prepare'
$ConfirmRoute = '/api/v1/factory-catalog/confirm'
$RequestPath = Join-Path $ReviewDir 'prepare-request.json'
$PreviewPath = Join-Path $ReviewDir 'preview.json'
$ConfirmPath = Join-Path $ReviewDir 'confirm-request.json'
$ResultPath = Join-Path $ReviewDir 'confirmation-result.json'
```

## 3. Build ONE removal request

Choose **one** subsection below, then use section 4's named preparation for B–D
or its generic alternative for A–D. For another operation, start again with a new workspace
and a fresh factory list. Do not reuse an old review after saving a change.

### A. Remove a custom parameter value, or reset saved settings — no Azure deletion

Select a scale set's unique ID (UUID) and optionally a project's ID from the
displayed factory:

```powershell
$ScaleSetId = Read-Host 'Exact scale-set UUID for this parameter scope'
$ProjectId = Read-Host 'Exact project UUID, or leave blank for common parameters'
$Kind = 'parameters'
$PrepareRoute = '/api/v1/factory-catalog/parameters/prepare'
$ConfirmRoute = '/api/v1/factory-catalog/parameters/confirm'
$ParametersPath = Join-Path $ReviewDir 'parameters.json'
```

**Choose ONE way to read the settings.** Check the returned template names and
parameter fields before choosing what to remove.

CLI:

```powershell
$ArgsForRead = @('parameters', 'get', '--folder', $Folder, '--factory-id', $FactoryId,
    '--scale-set-id', $ScaleSetId)
if ($ProjectId) { $ArgsForRead += @('--project-id', $ProjectId) }
$Raw = & $Python -m azurefactory @ArgsForRead
if ($LASTEXITCODE -ne 0) { throw 'Parameter read failed.' }
$Parameters = ($Raw -join "`n") | ConvertFrom-Json
Write-NewJson $ParametersPath $Parameters
$Parameters | ConvertTo-Json -Depth 100
```

REST:

```powershell
$CurlArgs = @('--silent', '--show-error', '--fail-with-body', '--noproxy', '*', '--get',
    "$BaseUrl/api/v1/factory-catalog/parameters", '-H', "X-API-Key: $env:AIFACTORY_API_KEY",
    '--data-urlencode', "folder=$Folder", '--data-urlencode', "factory_id=$FactoryId",
    '--data-urlencode', "scale_set_id=$ScaleSetId")
if ($ProjectId) { $CurlArgs += @('--data-urlencode', "project_id=$ProjectId") }
$Raw = & curl.exe @CurlArgs
if ($LASTEXITCODE -ne 0) { throw 'Parameter read failed.' }
$Parameters = ($Raw -join "`n") | ConvertFrom-Json
Write-NewJson $ParametersPath $Parameters
$Parameters | ConvertTo-Json -Depth 100
```

SDK:

```powershell
# Use a JSON context so an optional blank project does not become a missing process argument.
$ContextPath = Join-Path $ReviewDir 'parameter-context.json'
Write-NewJson $ContextPath @{ folder=$Folder; factory_id=$FactoryId; scale_set_id=$ScaleSetId; project_id=$ProjectId }
@'
import json, sys
from azurefactory import AzureFactoryClient
with open(sys.argv[1], encoding="utf-8") as stream:
    scope = json.load(stream)
scope["project_id"] = scope["project_id"] or None
result = AzureFactoryClient().catalog_parameters(**scope)
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, indent=2))
'@ | & $Python - $ContextPath $ParametersPath
if ($LASTEXITCODE -ne 0) { throw 'Parameter read failed.' }
$Parameters = Get-Content -Raw -LiteralPath $ParametersPath | ConvertFrom-Json
```

Build the request below using the names returned by your settings read.
**Reset discards all old saved parameter settings in the selected scale set,
even when a project is selected**, before saving the reviewed replacements.
It is broader than removing one custom value; review that choice carefully.

<details>
<summary>More info</summary>

The request model is `CatalogParameterPrepare`. `reset_profile` still requires
`templates`: this example supplies an empty change for one real template.
Missing required values can block preparation. Use chapter 19 to supply
additional settings rather than guessing.

</details>

```powershell
$Edit = Read-Host 'Choose unset or reset-profile'
if ($Edit -notin @('unset', 'reset-profile')) { throw 'Choose an exact operation.' }
$Template = Read-Host 'Exact template name returned by the parameter read'
if ($Template -notin @($Parameters.templates.template)) { throw 'Unknown template.' }
$Unset = @()
if ($Edit -eq 'unset') {
    $Field = Read-Host 'Exact configured parameter name to unset in that template'
    if ([string]::IsNullOrWhiteSpace($Field)) { throw 'A parameter name is required.' }
    $Unset = @($Field)
}
$Body = @{
    contract_version=1; folder=$Folder; factory_id=$FactoryId; scale_set_id=$ScaleSetId
    expected_revision=$Parameters.source_revision; schema_revision=$Parameters.schema_revision
    reset_profile=($Edit -eq 'reset-profile')
    templates=@(@{ template=$Template; parameters=@{}; unset=$Unset })
}
if ($ProjectId) { $Body.project_id = $ProjectId }
Write-NewJson $RequestPath $Body
```

The shared CLI request below is intentional. Dedicated parameter commands also
exist: `parameters prepare --request-json` with a saved receipt, then a separate
`parameters confirm --receipt ... --yes`. Do not mix a raw API preview with the
CLI's saved receipt format. **These confirmations save settings only; they do
not deploy or delete Azure resources.**

### B. Delete a draft project, scale set or factory — local files only

The API must confirm that the item is still a draft (`deployment_state:
draft`) and has not changed since review. Deployed, unknown, interrupted or
conflicting deployment records are **not** treated as a draft.
Removal can be blocked if deployment settings or other projects still use it.
Confirmation checks the records and files again, then archives the reviewed
local configuration in `draft-removals`. It does **not** delete subscriptions,
repositories, pipelines or Azure resources.

<details>
<summary>More info</summary>

Checks include the current revision, protected parameter profiles, retained
resource ownership, registered pipeline connections, saved bootstrap references,
and projects shared with other scale sets. These prevent draft removal from
discarding settings still needed elsewhere.

</details>

```powershell
$Action = Read-Host 'Choose delete-draft-project, delete-draft-scale-set, or delete-draft-factory'
if ($Action -notin @('delete-draft-project','delete-draft-scale-set','delete-draft-factory')) {
    throw 'Choose one exact draft action.'
}
$Body = @{ contract_version=1; folder=$Folder; factory_id=$FactoryId
    action=$Action; expected_revision=$Revision }
if ($Action -eq 'delete-draft-project') {
    $Body.project_id = Read-Host 'Exact draft project UUID in this factory'
}
if ($Action -eq 'delete-draft-scale-set') {
    $Body.scale_set_id = Read-Host 'Exact draft scale-set UUID in this factory'
}
Write-NewJson $RequestPath $Body
```

This is not the same as deleting an Azure project. The separate saved-creation
configuration removal routes and legacy `/projects/delete` or `/scale-sets/delete`
routes cannot replace the Azure resource-deletion steps below.

### C. Delete project resources — choose environments and what to keep

Choose one or more environments: `dev`, `stage`, `prod`. Select each only once.
Then make two separate choices:

* `include_project_subnets: false` keeps the project's subnets; `true` includes
  their deletion. It does **not** approve deletion of the shared resource group.
* `include_keyvault_and_resource_group: false` keeps the Key Vault and resource
  group; `true` includes them in deletion. This is independent of the subnet
  choice. Normal Azure soft-delete and retention rules still apply.
* Review the exact resource IDs in the delete/keep lists. Other projects and
  unselected environments are not included.

**This operation can be blocked by the layout, installed features, resource
ownership or permissions. It is not supported in single-writer mode.**
Project deletion follows its own process; do not assume it runs the same
ordered pipelines as whole-factory deletion.

<details>
<summary>More info</summary>

The exact request model is `deletion_options: { environments,
include_project_subnets, include_keyvault_and_resource_group }`. Both options
must be **JSON booleans**, not `"true"`/`"false"` strings.

This requires modern schema version 2 (`layout_version: 2` in catalog output),
one exact registered placement for every selected environment, complete inventory
and ownership, enrolled deletion permission, and selected-source
`selective-project-resources-v1` support. The current API blocks selective project
deletion in single-writer mode. It uses the selective lifecycle path, **not** the
named whole-factory ordered project-pipeline path.

</details>

```powershell
if ($Catalog.layout_version -ne 2) { throw 'Selective project deletion requires modern layout version 2.' }
$ProjectId = Read-Host 'Exact project UUID to remove resources from'
$EnvironmentText = Read-Host 'Exact selected environments, comma-separated: dev, stage, prod'
$Environments = @($EnvironmentText.Split(',') | ForEach-Object { $_.Trim() })
if ($Environments.Count -lt 1 -or $Environments.Count -gt 3 -or
    @($Environments | Where-Object { $_ -notin @('dev','stage','prod') }).Count -gt 0 -or
    @($Environments | Select-Object -Unique).Count -ne $Environments.Count) {
    throw 'Select each valid environment once.'
}
$SubnetChoice = Read-Host 'Include project subnet deletion? Type true or false'
$GroupChoice = Read-Host 'Include project Key Vault and resource-group deletion? Type true or false'
if ($SubnetChoice -notin @('true','false') -or $GroupChoice -notin @('true','false')) {
    throw 'Explicit true/false choices are required.'
}
$ExpectedMode = 'runtime'
$Body = @{
    contract_version=1; folder=$Folder; action='delete-project'
    factory_id=$FactoryId; project_id=$ProjectId; expected_revision=$Revision
    deletion_options=@{
        environments=$Environments
        include_project_subnets=($SubnetChoice -eq 'true')
        include_keyvault_and_resource_group=($GroupChoice -eq 'true')
    }
}
Write-NewJson $RequestPath $Body
```

You do not need to enter a scale-set ID here: the server finds it from the
project and selected environments. These choices do not read or change legacy
deletion flags.

After confirmed group deletion, the API updates the affected project's saved
deployment settings. Removing the project from every environment can also remove
its local configuration. Services-only deletion keeps that configuration.
**Neither choice removes the factory or its scale sets.**

<details>
<summary>More info</summary>

An optional `scale_set_id` identifies an existing project placement; it does not
expand or replace `deletion_options.environments`. After verified deletion, the
API updates the selected placement and pipeline binding.

</details>

### D. Delete a scale set's Azure resources

Use the exact scale-set UUID and review the full resource list. This is
not `delete-draft-scale-set`, and the project deletion options do not apply.
Resources needed elsewhere, resources to keep, unsupported software or active
projects can block deletion. A resource-group row in the preview does not by
itself approve that group's deletion: check its `delete` and `retain` lists.

```powershell
$ScaleSetId = Read-Host 'Exact scale-set UUID whose runtime resources are to be reviewed'
$ExpectedMode = 'runtime'
$Body = @{
    contract_version=1; folder=$Folder; action='delete-scale-set'
    factory_id=$FactoryId; scale_set_id=$ScaleSetId; expected_revision=$Revision
}
Write-NewJson $RequestPath $Body
```

## 4. For A–D: prepare, STOP, then confirm once

For **B–D**, the named CLI/SDK helpers below prepare the request built in section
3 and save a typed receipt. Choose **one** preparation, not both. For **A**, or
direct REST requests, use the generic alternative under **More info** below.
Do not mix its plain preview files with these typed receipts.

```powershell
$ReceiptPath = Join-Path $ReviewDir ('removal-receipt-' + [guid]::NewGuid().ToString('N') + '.json')
```

### Named CLI preparation — B, C or D

This uses the exact IDs, environments, revision and independent deletion choices
you already selected. The project command repeats `--environment` for each choice
and requires both retention flags as `yes` or `no`.

```powershell
switch ($Body.action) {
    'delete-project' {
        $EnvironmentArgs = @()
        foreach ($Environment in $Body.deletion_options.environments) {
            $EnvironmentArgs += @('--environment', $Environment)
        }
        $SubnetFlag = if ($Body.deletion_options.include_project_subnets) { 'yes' } else { 'no' }
        $GroupFlag = if ($Body.deletion_options.include_keyvault_and_resource_group) { 'yes' } else { 'no' }
        & $Python -m azurefactory project delete --folder $Folder `
            --factory-id $FactoryId --project-id $Body.project_id @EnvironmentArgs `
            --include-project-subnets $SubnetFlag --include-keyvault-and-resource-group $GroupFlag `
            --expected-revision $Revision --save-receipt $ReceiptPath
    }
    'delete-scale-set' {
        & $Python -m azurefactory scaleset delete --folder $Folder `
            --factory-id $FactoryId --scale-set-id $Body.scale_set_id `
            --expected-revision $Revision --save-receipt $ReceiptPath
    }
    { $_ -in @('delete-draft-factory','delete-draft-scale-set','delete-draft-project') } {
        $DraftKind = $Body.action.Substring('delete-draft-'.Length)
        $TargetArgs = @()
        if ($Body.scale_set_id) { $TargetArgs += @('--scale-set-id', $Body.scale_set_id) }
        if ($Body.project_id) { $TargetArgs += @('--project-id', $Body.project_id) }
        & $Python -m azurefactory draft remove --folder $Folder `
            --factory-id $FactoryId --kind $DraftKind @TargetArgs `
            --expected-revision $Revision --save-receipt $ReceiptPath
    }
    default { throw 'Use a B, C or D request, or choose the generic alternative.' }
}
if ($LASTEXITCODE -ne 0) { throw 'Preparation blocked or failed; do not confirm.' }
```

### Named SDK preparation — same B, C or D request

```powershell
@'
import json, sys
from azurefactory import AzureFactoryClient
from azurefactory.client import redact_secrets
from azurefactory.review import validate_preview, write_receipt

with open(sys.argv[1], encoding="utf-8") as stream:
    body = json.load(stream)
client = AzureFactoryClient()
scope = dict(folder=body["folder"], factory_id=body["factory_id"],
             expected_revision=body["expected_revision"])
action = body["action"]
if action == "delete-project":
    preview = client.project_delete_prepare(
        **scope, project_id=body["project_id"], **body["deletion_options"])
    operation = "project-delete"
elif action == "delete-scale-set":
    preview = client.scaleset_delete_prepare(**scope, scale_set_id=body["scale_set_id"])
    operation = "scaleset-delete"
elif action in {"delete-draft-factory", "delete-draft-scale-set", "delete-draft-project"}:
    kind = action.removeprefix("delete-draft-")
    preview = client.draft_remove_prepare(
        **scope, kind=kind, scale_set_id=body.get("scale_set_id"),
        project_id=body.get("project_id"))
    operation = "draft-remove-" + kind
else:
    raise SystemExit("Use a B, C or D request, or choose the generic alternative.")
print(json.dumps(redact_secrets(preview, client.api_key), indent=2))
validate_preview(preview)
write_receipt(sys.argv[2], client=client, purpose="catalog-confirm",
              operation=operation, request_body=body, preview=preview)
'@ | & $Python - $RequestPath $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Preparation blocked or failed; do not confirm.' }
```

### STOP — review, then separately confirm the typed receipt

For either named preparation, review the full preview: exact factory and project
or scale set, environments, tenants/subscriptions, settings or resource IDs,
delete/retain lists, both project deletion choices, warnings, blockers and expiry.
**An available helper does not unblock Azure deletion.** The mode, ownership,
retention and installed-runtime checks in section 3 still apply.

After approval, choose **only the matching command**. For **B (local draft
removal)**, this archives/removes local configuration without deleting Azure resources:

```powershell
& $Python -m azurefactory catalog confirm --receipt $ReceiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect saved state; do not retry confirmation.' }
```

For **C or D (Azure project/scale-set deletion)**, confirmation can start deletion;
keep the returned `job.id` and observe it in section 6:

```powershell
& $Python -m azurefactory runtime confirm --receipt $ReceiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Outcome uncertain; inspect the job, do not retry.' }
```

<details>
<summary>More info</summary>

Both named paths use receipt purpose `catalog-confirm`, not `runtime-confirm`.
The action/operation pairing and mode are checked strictly: `project-delete` and
`scaleset-delete` require `runtime`; `draft-remove-factory`,
`draft-remove-scale-set` and `draft-remove-project` require `configuration`.
Draft `kind` is exactly `factory`, `scale-set` or `project`.
`catalog confirm` rejects runtime receipts; `runtime confirm` rejects
configuration receipts. Neither accepts a raw preview. Both use the shared
catalog confirmation API after validation.

### Generic alternative — CLI, REST or SDK for A–D

Use this **instead of** the named preparation/confirmation above. It keeps the
existing plain-preview flow; there is no typed receipt in this alternative.

The request above is complete. **Choose ONE interface** for preparation and use
its matching confirmation later. The generic CLI requires `--write --yes` for
all POST requests, including **prepare** and POSTs that only read information.
These flags allow the request to be sent; **they do not approve deployment or
replace your review**.

### CLI — generic catalog/parameter access

```powershell
$Raw = & $Python -m azurefactory request POST $PrepareRoute `
    --body-json $RequestPath --write --yes
$PrepareExit = $LASTEXITCODE
if (-not $Raw) { throw 'No preview returned; inspect the error.' }
$Preview = ($Raw -join "`n") | ConvertFrom-Json
Write-NewJson $PreviewPath $Preview
$Preview | ConvertTo-Json -Depth 100
if ($PrepareExit -ne 0) { throw 'Preparation blocked or failed; do not confirm.' }
```

### REST — send the saved JSON request

```powershell
$Raw = & curl.exe --silent --show-error --fail-with-body --noproxy "*" `
    --request POST "$BaseUrl$PrepareRoute" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    -H "Content-Type: application/json" --data-binary "@$RequestPath"
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed; do not confirm.' }
$Preview = ($Raw -join "`n") | ConvertFrom-Json
Write-NewJson $PreviewPath $Preview
$Preview | ConvertTo-Json -Depth 100
```

### Python SDK

```powershell
@'
import json, sys
from azurefactory import AzureFactoryClient
with open(sys.argv[1], encoding="utf-8") as stream:
    body = json.load(stream)
api = AzureFactoryClient()
preview = api.parameter_prepare(body) if sys.argv[3] == "parameters" else api.catalog_prepare(body)
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(preview, stream, indent=2)
print(json.dumps(preview, indent=2))
'@ | & $Python - $RequestPath $PreviewPath $Kind
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed; do not confirm.' }
$Preview = Get-Content -Raw -LiteralPath $PreviewPath | ConvertFrom-Json
```

### STOP — separate human review

Do **not** paste confirmation immediately after preparation. Review the request
and full preview:

* Is this the right factory, project or scale set, in the right environments,
  tenants and subscriptions?
* Is it a settings-only change or an Azure deletion? Check `operation_mode`.
* Are the listed changes, warnings and resources to delete or keep correct?
  For project deletion, check `deletion_options` too.
* Is the review still current and unexpired, with no blockers?

**A blocked, incomplete or unknown result is not approval.**

<details>
<summary>More info</summary>

Also check the exact target UUIDs, resolved software version, `source_revision`
and expiry. These connect your approval to the specific settings and software
that were reviewed.

</details>

Only after obtaining approval for that exact, unexpired review, run:

```powershell
$Preview = Get-Content -Raw -LiteralPath $PreviewPath | ConvertFrom-Json
if ($Preview.can_execute -ne $true -or @($Preview.blockers).Count -ne 0 -or
    $Preview.operation_mode -ne $ExpectedMode -or
    [DateTimeOffset]::Parse($Preview.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Blocked, incompatible or expired review; do not confirm.'
}
if ((Read-Host 'After reviewing exact scope and obtaining approval, type CONFIRM-ONCE') -cne 'CONFIRM-ONCE') {
    throw 'Stopped without confirmation.'
}
Write-NewJson $ConfirmPath @{
    contract_version=1; folder=$Folder; confirmation_id=$Preview.confirmation_id
}
```

**Confirm only once. If the response is lost, check the job instead of sending
another confirmation.** Parameter edits use a separate confirmation endpoint,
already selected by the example.

<details>
<summary>More info</summary>

For these catalog project/scale/draft actions, the confirmation body is
**folder + contract_version + confirmation_id**. The server associates that ID
with the exact request, choices, owner, revision, expiry and saved deployment
checks. It does not require the phrase and hash used for whole-factory deletion.

</details>

**Choose only the corresponding confirmation block; each can perform a write.**

CLI:

```powershell
$Raw = & $Python -m azurefactory request POST $ConfirmRoute `
    --body-json $ConfirmPath --write --yes
if ($LASTEXITCODE -ne 0) { throw 'Confirmation failed or outcome uncertain. Observe; do not retry.' }
Write-NewJson $ResultPath (($Raw -join "`n") | ConvertFrom-Json)
Get-Content -Raw -LiteralPath $ResultPath
```

REST:

```powershell
$Raw = & curl.exe --silent --show-error --fail-with-body --noproxy "*" `
    --request POST "$BaseUrl$ConfirmRoute" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    -H "Content-Type: application/json" --data-binary "@$ConfirmPath"
if ($LASTEXITCODE -ne 0) { throw 'Confirmation failed or outcome uncertain. Observe; do not retry.' }
Write-NewJson $ResultPath (($Raw -join "`n") | ConvertFrom-Json)
Get-Content -Raw -LiteralPath $ResultPath
```

SDK:

```powershell
@'
import json, sys
from azurefactory import AzureFactoryClient
with open(sys.argv[1], encoding="utf-8") as stream:
    body = json.load(stream)
api = AzureFactoryClient()
confirm = api.parameter_confirm if sys.argv[3] == "parameters" else api.catalog_confirm
result = confirm(body["folder"], body["confirmation_id"])  # One call; no retry.
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, indent=2))
'@ | & $Python - $ConfirmPath $ResultPath $Kind
if ($LASTEXITCODE -ne 0) { throw 'Confirmation failed or outcome uncertain. Observe; do not retry.' }
```

A settings-only result can contain `catalog` with no `job`. An Azure operation
returns `job.id`; keep that ID and check its progress below.

</details>

## 5. Delete a whole factory — separate compatibility checks and approval

Start section 2 again for a new review folder and a fresh factory list. **Do not
use the confirmation in section 4 for this operation.** `delete-aifactory`
applies to the whole factory, not a chosen environment or project.

**This operation deletes whole resource groups. If a group contains a resource
that must be kept, preparation is blocked.** It cannot mix deletion and retention
within those groups. Listing a resource in configuration does not prove that it
exists or that it will be preserved.

Every registered project's configured **GitHub Actions (GHA) or Azure DevOps
(ADO)** deletion pipeline must finish in every environment **before shared
resource groups are removed**. Successful pipeline results and checks confirming
that the exact resources are gone are both required. Starting a pipeline is not
enough.

**What stays:** Entra security groups and Git repositories/history. Reusable
hub, VPN, connectivity, platform and bootstrap resources, coordination storage,
the executing identity and private runners must stay outside deleted groups.
Runners, environments, federated credentials, subscription metadata and
subscription-level roles need separate review; this does not remove every
external dependency. Key Vault purge is not performed. The factory registration
and local configuration are removed only after verified success.

<details>
<summary>More info</summary>

#### Required retention settings and pipeline order

The review's `deletion_retention_policy` must match
`deletion_plan.retention_policy`:

| Field | Required value |
|---|---|
| `mode` | `preserve-reusable-infrastructure` |
| `required_execution_contract` | `ordered-project-pipelines-v1` |
| `execution_scope` | `whole-resource-groups` |
| `selective_retention_supported` | `false` |
| `limitations` | Nonempty server-provided limitations, reviewed verbatim |

These fields describe the required behavior, not proof that the installed
software supports it. Configuration references can exclude protected resources
from deletion, but cannot establish the actual resource list or preservation.

Each project stage has all four explicit flags true: `enableDeleteForDisabledResources`,
`deleteAllServicesForProject`, `deleteKeyvaultAlso`, `deleteAllForProject`.
The required project order is capability hosts, target-project Search shared
private links, service-managed lifecycle, project resources, then project network.

</details>

Build the whole-factory request without changing the selected software version:

```powershell
$WholeRequest = @{ contract_version=1; folder=$Folder; factory_id=$FactoryId; expected_revision=$Revision }
Write-NewJson $RequestPath $WholeRequest
$ReceiptPath = Join-Path $ReviewDir 'whole-factory.receipt.json'
```

**Choose ONE way to prepare.** The CLI saves its review file only when
compatibility and preparation checks pass. REST and SDK save the returned preview.
**Neither file is an approval.**

### CLI prepare

```powershell
& $Python -m azurefactory delete-aifactory prepare --folder $Folder `
    --factory-id $FactoryId --expected-revision $Revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Blocked or failed. Do not confirm or bypass the capability gate.' }
```

### REST prepare

```powershell
$Raw = & curl.exe --silent --show-error --fail-with-body --noproxy "*" `
    --request POST "$BaseUrl/api/v1/operations/delete-aifactory/prepare" `
    -H "X-API-Key: $env:AIFACTORY_API_KEY" -H "Content-Type: application/json" `
    --data-binary "@$RequestPath"
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed.' }
Write-NewJson $PreviewPath (($Raw -join "`n") | ConvertFrom-Json)
Get-Content -Raw -LiteralPath $PreviewPath
```

### SDK prepare

```powershell
@'
import json, sys
from azurefactory import AzureFactoryClient
with open(sys.argv[1], encoding="utf-8") as stream:
    body = json.load(stream)
preview = AzureFactoryClient().delete_aifactory_prepare(body)
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(preview, stream, indent=2)
print(json.dumps(preview, indent=2))
'@ | & $Python - $RequestPath $PreviewPath
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed.' }
```

### STOP — review what will be deleted and kept

Complete the section 4 checks. Also review the full deletion plan, its order,
the exact resources to keep, any limits on what can be preserved, and
`confirmation_phrase`. **Do not proceed with a missing or outdated plan.**
`can_execute` alone does not replace review or approval.

<details>
<summary>More info</summary>

Check the selected source commit, pipeline repositories/definitions/refs,
dependencies and plan hash. These identify the exact software, pipeline steps
and saved plan being approved.

</details>

For a REST/SDK preview, run this additional **local check**. It does not send an
API request. Use the SDK version described in this chapter, not an older copy:

```powershell
@'
import json, sys
from azurefactory.factory_deletion import validate_deletion_preview
with open(sys.argv[1], encoding="utf-8") as stream:
    request = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    preview = json.load(stream)
validate_deletion_preview(request, preview)
print("Client contract checks passed; human approval and server revalidation are still required.")
'@ | & $Python - $RequestPath $PreviewPath
if ($LASTEXITCODE -ne 0) { throw 'Named review is blocked, expired or incompatible.' }
```

Do not run that preview check on a CLI receipt: the CLI checks its own file format.
Calling the SDK's prepare/confirm methods does not replace these checks or
human approval.

### Separate confirmation — choose ONE interface only after approval

CLI (the interactive command also presents its own approval/phrase prompts):

```powershell
$Phrase = Read-Host 'After approval, type the exact server confirmation_phrase from the saved CLI review'
$Raw = & $Python -m azurefactory delete-aifactory confirm --receipt $ReceiptPath `
    --yes --confirmation-phrase $Phrase
if ($Raw) { Write-NewJson $ResultPath (($Raw -join "`n") | ConvertFrom-Json) }
if ($LASTEXITCODE -ne 0) { throw 'Inspect saved result/server state; never blindly confirm again.' }
Get-Content -Raw -LiteralPath $ResultPath
```

For **REST or SDK only**, create the named confirmation body after approval:

```powershell
$Preview = Get-Content -Raw -LiteralPath $PreviewPath | ConvertFrom-Json
$Phrase = Read-Host 'After approval, type the exact server confirmation_phrase from this raw preview'
if ($Phrase -cne $Preview.confirmation_phrase -or $Preview.can_execute -ne $true -or
    @($Preview.blockers).Count -ne 0 -or
    [DateTimeOffset]::Parse($Preview.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Phrase mismatch, blocked or expired; do not confirm.'
}
Write-NewJson $ConfirmPath @{
    contract_version=1; folder=$Folder; confirmation_id=$Preview.confirmation_id
    preview_hash=$Preview.preview_hash; confirmation_phrase=$Phrase
}
```

REST:

```powershell
$Raw = & curl.exe --silent --show-error --fail-with-body --noproxy "*" `
    --request POST "$BaseUrl/api/v1/operations/delete-aifactory/confirm" `
    -H "X-API-Key: $env:AIFACTORY_API_KEY" -H "Content-Type: application/json" `
    --data-binary "@$ConfirmPath"
if ($LASTEXITCODE -ne 0) { throw 'Outcome may be uncertain. Observe; do not resend.' }
Write-NewJson $ResultPath (($Raw -join "`n") | ConvertFrom-Json)
Get-Content -Raw -LiteralPath $ResultPath
```

SDK:

```powershell
@'
import json, sys
from azurefactory import AzureFactoryClient
with open(sys.argv[1], encoding="utf-8") as stream:
    body = json.load(stream)
body.pop("contract_version")
result = AzureFactoryClient().delete_aifactory_confirm(**body)  # Exactly once.
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, indent=2))
'@ | & $Python - $ConfirmPath $ResultPath
if ($LASTEXITCODE -ne 0) { throw 'Outcome may be uncertain. Observe; do not resend.' }
```

The whole-factory REST/SDK request requires **both** the server's `preview_hash`
and exact `confirmation_phrase`, as well as the confirmation ID. You cannot
bypass these checks by sending the request through a generic catalog route.

## 6. Check progress and recover without repeating deletion

### First find the exact job

A lost confirm response is **unknown**, not “nothing happened”. Keep the request,
preview or receipt, software version, account details, times and any result.
List jobs for the same folder using the same API identity. Match the action,
factory, project, scale set, version and time carefully. **Never choose the
first job or confirm again just to see what happens.** If you cannot identify
the job with confidence, stop and ask the operator to check the server and
pipeline results.

Choose ONE interface to discover jobs:

```powershell
# CLI
& $Python -m azurefactory catalog jobs --folder $Folder
```

```powershell
# REST
curl.exe --silent --show-error --fail-with-body --noproxy "*" --get `
    "$BaseUrl/api/v1/factory-catalog/jobs" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    --data-urlencode "folder=$Folder"
if ($LASTEXITCODE -ne 0) { throw 'Job discovery failed; outcome is not inferred.' }
```

```powershell
# SDK
@'
import json, sys
from azurefactory import AzureFactoryClient
print(json.dumps(AzureFactoryClient().catalog_jobs(sys.argv[1]), indent=2))
'@ | & $Python - $Folder
if ($LASTEXITCODE -ne 0) { throw 'Job discovery failed; outcome is not inferred.' }
```

### Read status and logs, or wait for progress

```powershell
$JobId = Read-Host 'Exact correlated job UUID from the confirmation or owner-bound job list'
& $Python -m azurefactory catalog job --folder $Folder --job-id $JobId
& $Python -m azurefactory catalog logs --folder $Folder --job-id $JobId --cursor 0
& $Python -m azurefactory catalog poll --folder $Folder --job-id $JobId `
    --poll-timeout 120 --poll-interval 5
```

The `runtime` commands below read the **same jobs**. They are an alternative
spelling, not a separate deployment system:

```powershell
& $Python -m azurefactory runtime status --folder $Folder --job-id $JobId
& $Python -m azurefactory runtime logs --folder $Folder --job-id $JobId --cursor 0
& $Python -m azurefactory runtime poll --folder $Folder --job-id $JobId `
    --poll-timeout 120 --poll-interval 5
```

REST status/log equivalents:

```powershell
curl.exe --silent --show-error --fail-with-body --noproxy "*" --get `
    "$BaseUrl/api/v1/factory-catalog/jobs/$JobId" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    --data-urlencode "folder=$Folder"
if ($LASTEXITCODE -ne 0) { throw 'Status unavailable.' }
curl.exe --silent --show-error --fail-with-body --noproxy "*" --get `
    "$BaseUrl/api/v1/factory-catalog/terminal" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    --data-urlencode "folder=$Folder" --data-urlencode "job_id=$JobId" --data-urlencode "cursor=0"
if ($LASTEXITCODE -ne 0) { throw 'Logs unavailable.' }
```

SDK status/logs and repeated checks with a time limit (there is no dedicated SDK
`runtime_poll` method):

```powershell
@'
import json, sys, time
from azurefactory import AzureFactoryClient
api = AzureFactoryClient()
folder, job_id = sys.argv[1:3]
print(json.dumps(api.catalog_terminal(folder, job_id, cursor=0), indent=2))
deadline = time.monotonic() + 120
while True:
    job = api.catalog_job(folder, job_id)
    print(json.dumps(job, indent=2))
    if job["status"] in {"succeeded", "failed", "interrupted"}:
        break
    if time.monotonic() >= deadline:
        raise SystemExit("Observation deadline reached; job was NOT cancelled or retried.")
    time.sleep(5)
'@ | & $Python - $Folder $JobId
```

Catalog statuses are `queued`, `running`, `succeeded`, `failed`, `interrupted`.
For whole-factory jobs also inspect `pipeline_runs`, `deletion_plan` and
`reconciliation_required`. A pipeline event or saved configuration entry does
not replace the deletion job's results and checks.

Legacy status is different: **`submitted` means the local script exited zero**,
not “the pipeline was submitted”, pipeline success or verified Azure deployment.
Its `deployment_verified` remains false. A completed `--wait`, local exit code
zero, missing logs, timeout, access-denied response or failed lookup cannot prove
that resources were deleted. **A polling or watch timeout only stops waiting;
it does not cancel the job or make it safe to retry deletion.**

### Whole-factory status and finishing local cleanup

Use only a job whose action is `delete-factory`. Choose ONE status interface:

```powershell
# CLI
& $Python -m azurefactory delete-aifactory status --folder $Folder --job-id $JobId
```

```powershell
# REST
curl.exe --silent --show-error --fail-with-body --noproxy "*" --get `
    "$BaseUrl/api/v1/operations/delete-aifactory/status" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    --data-urlencode "folder=$Folder" --data-urlencode "job_id=$JobId"
if ($LASTEXITCODE -ne 0) { throw 'Status read failed; do not retry confirmation.' }
```

```powershell
# SDK
@'
import json, sys
from azurefactory import AzureFactoryClient
print(json.dumps(AzureFactoryClient().delete_aifactory_status(sys.argv[1], sys.argv[2]), indent=2))
'@ | & $Python - $Folder $JobId
```

If Azure deletion finished but local cleanup was interrupted, `reconcile` can
use **saved, verified completion records for that exact job** to finish local
catalog cleanup. **It does not call Azure, restart pipelines, retry failed
deletions or assume missing resources are gone.** It cannot repair every partial
deletion. Missing or incomplete records keep the operation blocked.
Keep the job records and locks; never clear locks, register the setup again or
force software changes as a recovery shortcut.

After reviewing that job's results, choose ONE way to finish local cleanup:

```powershell
# CLI: local reconciliation, not another deletion approval.
& $Python -m azurefactory delete-aifactory reconcile --folder $Folder --job-id $JobId
```

```powershell
# REST
$ReconcilePath = Join-Path $ReviewDir ('reconcile-' + [guid]::NewGuid().ToString('N') + '.json')
Write-NewJson $ReconcilePath @{ contract_version=1; folder=$Folder; job_id=$JobId }
curl.exe --silent --show-error --fail-with-body --noproxy "*" --request POST `
    "$BaseUrl/api/v1/operations/delete-aifactory/reconcile" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    -H "Content-Type: application/json" --data-binary "@$ReconcilePath"
if ($LASTEXITCODE -ne 0) { throw 'Cleanup could not finish; keep the saved results.' }
```

```powershell
# SDK
@'
import json, sys
from azurefactory import AzureFactoryClient
print(json.dumps(AzureFactoryClient().delete_aifactory_reconcile(sys.argv[1], sys.argv[2]), indent=2))
'@ | & $Python - $Folder $JobId
```

There is no equivalent general-purpose recovery command for projects or scale
sets in this SDK/CLI. Check their original jobs and ask the operator to review
the completion records; do not send them to the whole-factory reconciler.
An expired **unused** review can be prepared again with current settings.
An uncertain **confirmed** operation must be checked and resolved first.

## 7. Optional status and report commands

These commands are not required for deletion. Health, compatibility and sign-in
checks tell you about the host and API, not whether deployment succeeded.
The catalog lists saved configuration and deployment records; preparation for
an Azure operation checks the actual resource list separately.
Run these optional read-only checks only against an approved real host:

```powershell
& $Python -m azurefactory health
& $Python -m azurefactory doctor
& $Python -m azurefactory schema --openapi
& $Python -m azurefactory bootstrap capabilities
$ObservedScaleSetId = Read-Host 'Exact scale-set UUID for the scoped Azure auth check'
& $Python -m azurefactory auth status --folder $Folder --factory-id $FactoryId `
    --scale-set-id $ObservedScaleSetId
```

### GitHub Actions status/watch — not Azure DevOps

Use the exact repository and run ID recorded for your operation:

```powershell
$Repository = Read-Host 'Exact GitHub OWNER/REPO from the execution receipt'
$RunId = Read-Host 'Exact GitHub Actions numeric run ID'
& $Python -m azurefactory workflow status --repository $Repository --run-id $RunId --json
& $Python -m azurefactory workflow watch --repository $Repository --run-id $RunId `
    --timeout 120 --json
```

Watch follows a read-only stream of updates; reconnecting does not restart the
workflow. Its `after` cursor resumes from an earlier update. Closing a watch
does not cancel the run. These commands do not start pipelines and do not monitor
ADO. For ADO, use Azure DevOps results and the original catalog job.

### Sample reports, saved results and actual Azure billing are different

```powershell
& $Python -m azurefactory monitoring catalog
& $Python -m azurefactory monitoring report --source sample --report showback
& $Python -m azurefactory monitoring saved read --folder $Folder --factory-id $FactoryId
& $Python -m azurefactory monitoring saved summary --folder $Folder --factory-id $FactoryId
```

Additional complete CLI examples (same initialized shell):

```powershell
& $Python -m azurefactory monitoring summary --source sample
& $Python -m azurefactory monitoring export --source sample --report showback --format csv
& $Python -m azurefactory monitoring saved report --folder $Folder --factory-id $FactoryId --report showback
```

`sample` uses demonstration data, not real costs or deployment results.
`monitoring saved` reads saved results you are permitted to view and calculates
reports; it does not collect or import new data or start jobs. Missing, incomplete,
outdated or empty results do **not** mean everything is healthy or costs are zero.
The report source label `live` means supplied observations, not an automatic
Azure data collection.

Actual resource-group costs make an **Azure Cost Management read** for explicitly
selected subscriptions; run only with approval and permission to read those costs:

```powershell
$CostSubscription = Read-Host 'Exact authorized subscription UUID for Azure billing reads'
$CostMonth = Read-Host 'Billing month YYYY-MM'
& $Python -m azurefactory monitoring resource-group-costs --subscription $CostSubscription `
    --month $CostMonth --folder $Folder
```

Billing can arrive late. A zero or missing charge does not prove a resource is gone.

<details>
<summary>More info</summary>

### Matching REST endpoints and SDK methods

`AzureFactoryClient()` uses the URL/key environment variables from chapter 18.
All folder paths refer to the computer running the API. The POST status/report
requests below only read information, but the generic CLI still requires
`--write --yes` to send them.

| CLI surface | REST | Actual SDK method |
|---|---|---|
| `health` | `GET /health` | `health()` |
| `schema` / `schema --openapi` | `GET /api/v1/schema` / `GET /openapi.json` | `schema()` / `openapi()` |
| `doctor` | Client compatibility checks over health and OpenAPI paths/schemas/contracts; not `/doctor` | No dedicated `doctor()` method |
| `bootstrap capabilities` | `GET /api/v1/creation/capabilities` | `creation_capabilities()` |
| `auth status` | `POST /api/v1/azure/auth/status`; scoped body includes `aifactory_folder`, `factory_id`, `scale_set_id` | `auth_status(aifactory_folder=..., factory_id=..., scale_set_id=...)` |
| `catalog list` | `GET /api/v1/factory-catalog?folder=...` | `catalog_list(folder)` |
| `catalog jobs` | `GET /api/v1/factory-catalog/jobs?folder=...` | `catalog_jobs(folder)` |
| `catalog job` / `runtime status` | `GET /api/v1/factory-catalog/jobs/{job_id}?folder=...` | `catalog_job(folder, job_id)` |
| `catalog logs` / `runtime logs` | `GET /api/v1/factory-catalog/terminal`; query `folder`, `job_id`, `cursor` | `catalog_terminal(folder, job_id, cursor=0)` |
| `catalog poll` / `runtime poll` | Repeated existing job reads; no poll endpoint | Bounded loop over `catalog_job` |
| `workflow status` | `GET /api/v1/workflow-runs/status`; query `repository`, `run_id` | `get_workflow_run_status(repository, run_id)` |
| `workflow watch` | `GET /api/v1/workflow-runs/events` SSE; scope plus `after`, `follow` | `watch_workflow_run(repository, run_id, after=None, follow=True, timeout=120)` |
| `monitoring catalog` | `GET /api/v1/monitoring/catalog` | `monitoring_catalog()` |
| `monitoring report` | `POST /api/v1/monitoring/report`; e.g. `source: sample`, `report_id: showback` | `monitoring_report(body)` |
| `monitoring summary` / `monitoring export` | `POST /api/v1/monitoring/summary` / `/api/v1/monitoring/export`; explicit source and required report/format fields | `monitoring_summary(body)` / `monitoring_export(body)`; CSV export returns text |
| `monitoring saved read` | `POST /api/v1/monitoring/evidence/read`; `folder` plus exact optional scope IDs/date bounds | `monitoring_evidence_read(context)` |
| `monitoring saved summary/report` | Read saved results, then POST `/api/v1/monitoring/summary` or `/report` only when results are available; not `/saved/summary` | `monitoring_saved_summary(context)` / `monitoring_saved_report(context, report_id="showback")` |
| `monitoring resource-group-costs` | `POST /api/v1/monitoring/resource-group-costs`; `subscription_ids`, optional `month`, `aifactory_folder`, `refresh` | `resource_group_costs(body)` |

</details>

## 8. Reference

The examples describe supported commands, not a verified live deployment.
No cloud operation, pipeline start, deletion, installation or version change
was performed to write this chapter.

<details>
<summary>More info</summary>

### Source references and review notes

API source and tests (in the separate API repository):

* [API guide](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/docs/API.md)
  and [OpenAPI](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/docs/openapi.json).
* [Catalog request/preview/job models](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/factory_catalog_models.py),
  [parameter models](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_parameter_models.py),
  and [owner-bound confirmation](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/factory_catalog.py).
* [Draft deletion guards/archive](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_draft_deletion.py),
  [project scope](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_project_deletion.py),
  [source capability gates](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_frozen_plan.py),
  and [project deletion regression coverage](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/tests/test_catalog_project_deletion.py).
* [Named routes](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/factory_deletion.py),
  [ordered plan/retention requirements](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_factory_deletion.py),
  [runtime reconciliation](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_runtime.py),
  and [retention/reconciliation tests](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/tests/test_factory_deletion.py).

Accelerator client and deployment implementation:

* [CLI parser/handlers](../../../environment_setup/azurefactory-cli/src/azurefactory/cli.py),
  [SDK methods](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py),
  [named deletion validator](../../../environment_setup/azurefactory-cli/src/azurefactory/factory_deletion.py),
  [saved results adapter](../../../environment_setup/azurefactory-cli/src/azurefactory/monitoring_saved.py),
  and [workflow event observer](../../../environment_setup/azurefactory-cli/src/azurefactory/workflow_events.py).
* [Named deletion client tests](../../../environment_setup/azurefactory-cli/tests/test_factory_deletion.py),
  [operation-result tests](../../../environment_setup/azurefactory-cli/tests/test_operation_results.py),
  [lifecycle engine](../../../bootstrap/lib/factory_lifecycle.py),
  and [lifecycle execution and recovery contract](../../../bootstrap/lib/factory_lifecycle_contract.txt).

Bounded graph navigation was checked before writing: the API graph was current
(`de669aa8…`, 566 indexed files); accelerator graph was fresh (`ae9853f9…`, 1,653
files, 23 partial-syntax files). Static/resolved symbols and observed architecture
notes guided direct source/test reads; graphs did not establish installed or
Azure state. Published client additions were checked directly because the
original working-checkout graph and Git revision did not cover every newer
addition. Architecture notes describe findings, not approval to deploy.

</details>
