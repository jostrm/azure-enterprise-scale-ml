# 20. Remove, observe and recover: CLI, REST and Python SDK

Continue from [18 — setup](18-cli-and-api-and-usage.md), in the **same PowerShell
Window B**. [19 — ADD and UPDATE](19-cli-and-api-and-usage.md) covers configuration
and deployment. [17 — overview](17-cli-and-api-and-usage.md) remains the general
guide. This chapter separates **removing configuration** from **deleting Azure
resources**; neither a saved setting nor a successful HTTP response proves that
Azure resources were deleted.
For users who prefer editing files, first read
[file-first versus wrapper-first configuration](18-cli-and-api-and-usage.md#choose-how-to-author-configuration-file-first-or-wrapper-first).
Deleting a JSON key or setting a service flag to false is not an alternative
authorization path for the resource-deletion operations below.

## 1. Choose the removal intent, not just a command containing “delete”

Labels below describe source contracts, **not an installed binary or a live
factory's readiness**.

| Intent | Exact surface | Support and effect |
|---|---|---|
| Remove an explicit parameter override | `parameters prepare --unset`; `ParameterPatch.unset` | **implemented**, configuration only; separate parameter confirmation. Reverts to resolution/default behavior, not Azure deletion. |
| Reset an incompatible parameter profile | `parameters prepare --reset-profile`; `reset_profile` | **implemented**, configuration only; requires reviewed template patches and current schema/source revisions. Not “reset Azure”. |
| Remove never-deployed local configuration | Catalog actions `delete-draft-project`, `delete-draft-scale-set`, `delete-draft-factory` | **generic-access only**, guarded local configuration removal/archive; no Azure deletion or dispatch. |
| Delete one project's resources in selected environments | Catalog action `delete-project` and explicit `deletion_options` | **generic-access only; conditional/blocked** by modern layout, source capabilities, ownership, inventory, bindings and coordination. |
| Delete a selected scale set's reviewed runtime resources | Catalog action `delete-scale-set` | **generic-access only; conditional/blocked**. Review exact delete/retain inventory; do not assume every resource group is deleted. |
| Delete an entire factory's reviewed Azure scope | `delete-aifactory prepare/confirm/status/reconcile` and named API/SDK methods | **implemented** interface; **conditional/blocked** execution. Requires compatible ordered project-pipeline runtime; projects finish before common teardown. |
| Reconcile a previously confirmed whole-factory job | Named `delete-aifactory reconcile` | **implemented**, local completion from existing verified receipts, not redispatch or an Azure retry. |

**not implemented:** friendly `project delete` or `scaleset delete` CLI commands,
dedicated `AzureFactoryClient` project/scale-set/draft deletion methods, automatic
“disable flag = delete” semantics, named whole-factory selective retention within
owned groups, or a generic force/retry/cancel-on-timeout workflow. Use the exact
generic catalog action where documented; never substitute legacy deployment or
direct Azure deletion to bypass a blocker.

### Source and runtime boundaries

This chapter checks the published API source at `d52463f` and accelerator CLI/SDK
source at `eb077742`, including its deletion-plan validator and reconcile
method. A different local checkout or packaged sidecar may lack these methods.
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

Preparation may inspect real host/provider/Azure state; it is not an offline
simulation. Preflight is read-only readiness inspection, not consent and not
deletion authorization. Offline regression tests use fixtures; see the optional
test section in chapter 18. Neither running those tests nor starting a demo API
is a prerequisite for operating an already authorized host.

## 2. Shared setup and exact catalog selection

Chapter 18's mandatory Window B setup initializes `$ApiRoot`, `$AcceleratorRoot`,
`$Python = Join-Path $ApiRoot '.venv\Scripts\python.exe'`,
`$env:PYTHONPATH = Join-Path $AcceleratorRoot 'environment_setup\azurefactory-cli\src'`,
and `AIFACTORY_API_URL`/`AIFACTORY_API_KEY`. Do not assume that a global
`azurefactory` executable is installed.

The standalone demonstration uses loopback port `8876`; its empty demonstration
root and public example key are **not a real deletion environment**. Before this
chapter, set `AIFACTORY_API_URL` and `AIFACTORY_API_KEY` through your approved
mechanism to the real owning host and identity; do not reuse the demonstration key.
Connect only to that authorized host and enter its actual registered folder.
Every API `folder` is a path **on the API
host**, not a client-side upload. Preserve tenant, subscription, factory, scale-set
and project identities; `DEV/001` and `STAGE/001` are different scopes.

Run this local setup once per separately reviewed scenario. It creates a unique
review directory under your local application data, outside Git checkouts,
replaceable template folders and the operating-system temporary directory.
Keep it private; receipts
and inventory may contain sensitive infrastructure identifiers. Retain uncertain
operation evidence rather than cleaning it up automatically.

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

**Choose ONE discovery interface**, not all three.

### CLI discovery

```powershell
$Raw = & $Python -m azurefactory catalog list --folder $Folder
if ($LASTEXITCODE -ne 0) { throw 'Catalog read failed.' }
$Catalog = ($Raw -join "`n") | ConvertFrom-Json
Write-NewJson $CatalogPath $Catalog
$Catalog | ConvertTo-Json -Depth 100
```

### REST discovery

```powershell
$Raw = & curl.exe --silent --show-error --fail-with-body --noproxy "*" --get `
    "$BaseUrl/api/v1/factory-catalog" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    --data-urlencode "folder=$Folder"
if ($LASTEXITCODE -ne 0) { throw 'Catalog read failed.' }
$Catalog = ($Raw -join "`n") | ConvertFrom-Json
Write-NewJson $CatalogPath $Catalog
$Catalog | ConvertTo-Json -Depth 100
```

### Python SDK discovery

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

Choose **one** subsection below, then use the shared prepare/review/confirm
walkthrough in section 4. For another operation, start again with a new workspace
and refreshed catalog. Do not reuse revisions or receipts after a confirmed write.

### A. Remove an override, or reset a parameter profile — no Azure deletion

Select a scale-set UUID and optionally a project UUID from the displayed factory:

```powershell
$ScaleSetId = Read-Host 'Exact scale-set UUID for this parameter scope'
$ProjectId = Read-Host 'Exact project UUID, or leave blank for common parameters'
$Kind = 'parameters'
$PrepareRoute = '/api/v1/factory-catalog/parameters/prepare'
$ConfirmRoute = '/api/v1/factory-catalog/parameters/confirm'
$ParametersPath = Join-Path $ReviewDir 'parameters.json'
```

**Choose ONE parameter read**; inspect template names and parameter fields before
entering a removal. This read resolves the selected published schemas.

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

Build the exact `CatalogParameterPrepare` body. `reset_profile` does not permit
omitting `templates`: this example resets the profile while supplying a reviewed
empty patch for one actual template. Required unresolved fields can still block
preparation; use chapter 19 for additional typed patches rather than guessing.
**Reset discards every old parameter-profile context in the selected scale set,
even when a project is selected**, before saving the reviewed replacements.
It is broader than unsetting one field; review that scope explicitly.

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

The shared generic CLI transport below is intentional. Friendly equivalents also
exist: `parameters prepare --request-json` with a saved receipt, then a separate
`parameters confirm --receipt ... --yes`. Do not mix a raw API preview with the
CLI's typed receipt format. None of these configuration confirmations deploys.

### B. Delete a draft project, scale set or factory — guarded local removal

Draft deletion requires the exact revision and verified `deployment_state:
draft`. Deployed, unknown, interrupted or conflicting evidence is not a draft.
Protected profiles, retained ownership, enrolled bindings, saved bootstrap
references, and a logical project shared with another scale set can block
removal. Confirmation rechecks evidence and file trees and archives only reviewed
local configuration under the catalog's internal `draft-removals` area. It does
not delete subscriptions, repositories, pipelines or Azure resources.

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
routes are not substitutes for this runtime deletion contract.

### C. Remove project resources — explicit environments and independent options

The exact model is `deletion_options: { environments,
include_project_subnets, include_keyvault_and_resource_group }`. The two options
are required **JSON booleans**, not `"true"`/`"false"` strings. Environments are a
nonempty, unique subset of `dev`, `stage`, `prod`.

* `include_project_subnets: false` retains the project's scoped subnets; `true`
  explicitly includes their cleanup. It does not authorize common-group deletion.
* `include_keyvault_and_resource_group: false` retains the Key Vault/resource
  group; `true` includes them in the reviewed project teardown. This is independent
  of the subnet choice. Normal Azure soft-delete/retention still applies.
* The exact delete/retain resource IDs, not these descriptions alone, govern
  review. Unselected environments and other projects remain outside scope.

This requires modern schema version 2 (`layout_version: 2` in catalog output),
one exact registered placement for every selected environment, complete inventory
and ownership, enrolled deletion permission, and selected-source
`selective-project-resources-v1` support. The current API blocks selective project
deletion in single-writer mode. It uses the selective lifecycle path, **not** the
named whole-factory ordered project-pipeline path.

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

No source scale-set UUID is needed here: the server resolves each exact placement
from the project plus requested environments. An optional `scale_set_id` merely
identifies an existing project placement; it must not expand or replace the
environment selection. These controls do not consume or set legacy destructive
flags. After verified group deletion, the API reconciles the selected placement
and binding; removing all placements can remove the logical project's local
configuration. Services-only deletion retains configuration. Neither removes the
factory or its scale sets.

### D. Delete scale-set runtime resources

Use an exact scale-set UUID and review the complete resulting inventory. This is
not `delete-draft-scale-set`, and the project deletion options do not apply.
Dependency closure, retained resources, runtime capabilities and active project
placements can block it. A resource-group row in the preview is not by itself
authorization to delete that group: inspect its `delete` and `retain` arrays.

```powershell
$ScaleSetId = Read-Host 'Exact scale-set UUID whose runtime resources are to be reviewed'
$ExpectedMode = 'runtime'
$Body = @{
    contract_version=1; folder=$Folder; action='delete-scale-set'
    factory_id=$FactoryId; scale_set_id=$ScaleSetId; expected_revision=$Revision
}
Write-NewJson $RequestPath $Body
```

## 4. Shared transport for A–D: prepare, STOP, then confirm once

The request above is complete. **Choose ONE interface** for preparation and use
its corresponding confirmation later. All generic unsafe CLI methods, including
read-like POSTs and **prepare**, require `--write --yes`. These are transport
acknowledgements, **not deployment consent** and not permission to skip review.

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

### REST — explicit JSON file, UTF-8 without BOM

```powershell
$Raw = & curl.exe --silent --show-error --fail-with-body --noproxy "*" `
    --request POST "$BaseUrl$PrepareRoute" -H "X-API-Key: $env:AIFACTORY_API_KEY" `
    -H "Content-Type: application/json" --data-binary "@$RequestPath"
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed; do not confirm.' }
$Preview = ($Raw -join "`n") | ConvertFrom-Json
Write-NewJson $PreviewPath $Preview
$Preview | ConvertTo-Json -Depth 100
```

### Python SDK — actual generic methods

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

Do **not** paste confirmation immediately after preparation. Review the saved
request and full preview, including target UUIDs, all environment/tenant/
subscription identities, resolved source version, `source_revision`, expiry,
`operation_mode`, effects, warnings, blockers and exact deletion targets. For
project deletion, compare `deletion_options` and every delete/retain resource ID
with the intended scope. A blocked/partial/unknown result is not approval.

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

For these ordinary catalog project/scale/draft actions, the implemented
confirmation body is **folder + contract_version + confirmation_id**. The server
binds the request, exact options, owner, revision, expiry and frozen runtime
evidence to that ID. It does **not** require the named factory deletion phrase
and hash. Parameter edits use their separate confirmation endpoint. Confirmation
remains single-use; a lost response does not authorize another call.

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

A configuration result can contain `catalog` and no runtime `job`. A runtime
result contains `job.id`; preserve it and observe that job below.

## 5. Named whole-factory deletion — separate, capability-gated workflow

Start section 2 again for a new review workspace and fresh revision. **Do not use
the ordinary confirmation in section 4 for this operation.** Named
`delete-aifactory` is whole-factory scope, with no environment narrowing or
project deletion options.

The review must expose and bind the following `deletion_retention_policy` to
`deletion_plan.retention_policy`:

| Field | Required value |
|---|---|
| `mode` | `preserve-reusable-infrastructure` |
| `required_execution_contract` | `ordered-project-pipelines-v1` |
| `execution_scope` | `whole-resource-groups` |
| `selective_retention_supported` | `false` |
| `limitations` | Nonempty server-provided limitations, reviewed verbatim |

This policy states requirements, not proof of runtime support. **Mixed retained
resources inside groups being deleted block preparation.** Configuration
references can exclude protected resources but cannot manufacture protected
inventory or prove preservation.

The frozen plan requires every registered project's configured **GHA or ADO**
pipeline, in every environment, before any common group teardown. Each project
stage has all four explicit flags true: `enableDeleteForDisabledResources`,
`deleteAllServicesForProject`, `deleteKeyvaultAlso`, `deleteAllForProject`.
The required project order is capability hosts, target-project Search shared
private links, service-managed lifecycle, project resources, then project network.
Successful provider completion **and exact absence evidence** are required;
dispatch alone is insufficient.

Entra security groups and Git repositories/history are retained. Reusable
hub/VPN/connectivity/platform/bootstrap resources, coordination storage, the
executing identity and private runners must remain outside deleted groups.
Provider runners/environments/federated credentials, subscription metadata and
subscription-level roles require independent review; this is not “delete all
external dependencies”. Key Vault purge is not performed. Only verified success
removes the factory registration and local catalog configuration.

Build the named request without changing the selected source pin:

```powershell
$WholeRequest = @{ contract_version=1; folder=$Folder; factory_id=$FactoryId; expected_revision=$Revision }
Write-NewJson $RequestPath $WholeRequest
$ReceiptPath = Join-Path $ReviewDir 'whole-factory.receipt.json'
```

**Choose ONE prepare interface.** The CLI saves a validated, typed receipt only
for a compatible executable review; the REST/SDK examples preserve a raw preview.
Neither is an approval.

### CLI named prepare

```powershell
& $Python -m azurefactory delete-aifactory prepare --folder $Folder `
    --factory-id $FactoryId --expected-revision $Revision --save-receipt $ReceiptPath
if ($LASTEXITCODE -ne 0) { throw 'Blocked or failed. Do not confirm or bypass the capability gate.' }
```

### REST named prepare

```powershell
$Raw = & curl.exe --silent --show-error --fail-with-body --noproxy "*" `
    --request POST "$BaseUrl/api/v1/operations/delete-aifactory/prepare" `
    -H "X-API-Key: $env:AIFACTORY_API_KEY" -H "Content-Type: application/json" `
    --data-binary "@$RequestPath"
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed.' }
Write-NewJson $PreviewPath (($Raw -join "`n") | ConvertFrom-Json)
Get-Content -Raw -LiteralPath $PreviewPath
```

### SDK named prepare

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

### STOP — review the named plan, retention and exact phrase

Review all section 4 checks **plus** the complete ordered plan, source commit,
pipeline repositories/definitions/refs, dependencies, plan hash, retained IDs,
retention limitations and `confirmation_phrase`. No missing/old plan, broad
inventory label or `can_execute` flag alone can replace that review.

For REST/SDK raw previews, this **offline client validation** additionally checks
the named source contract; it sends no request. Use the chapter's reviewed SDK
version, not an older validator from another checkout:

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

Do not run that raw-preview block for the CLI receipt: the CLI validates its own
typed receipt. The SDK's dedicated prepare/confirm transport methods do not
themselves substitute for the full human/client review.

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

The named REST/SDK contract requires **both** the server's `preview_hash` and
exact `confirmation_phrase`, in addition to the confirmation ID. A generic
catalog route cannot bypass the server's whole-factory proof requirement.

## 6. Observe and recover without repeating a write

### First find the exact job

A lost confirm response is **unknown**, not “nothing happened”. Keep the request,
preview/receipt, source version, owner/API identity, times and any result.
Read catalog jobs for the same folder and authenticated owner; correlate the
exact action/factory/project/scale/source revision and time. Never choose the
first job. If correlation is ambiguous, stop and have the operator reconcile
server/provider evidence; do not create a new confirmation as a diagnostic.

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

### Catalog/runtime status, logs and bounded polling

```powershell
$JobId = Read-Host 'Exact correlated job UUID from the confirmation or owner-bound job list'
& $Python -m azurefactory catalog job --folder $Folder --job-id $JobId
& $Python -m azurefactory catalog logs --folder $Folder --job-id $JobId --cursor 0
& $Python -m azurefactory catalog poll --folder $Folder --job-id $JobId `
    --poll-timeout 120 --poll-interval 5
```

The `runtime` aliases read the **same catalog jobs**, not another execution
engine. Use them instead if that matches your deployment workflow:

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

SDK status/logs and local bounded polling (there is no dedicated SDK
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
`reconciliation_required`. A provider event or a catalog configuration entry is
not a substitute for the deletion job's verified scope/evidence.

Legacy status is different: **`submitted` means the local script exited zero**,
not “the pipeline was submitted”, pipeline success or verified Azure deployment.
Its `deployment_verified` remains false. A completed `--wait`, local exit code
zero, missing logs, timeout, denied inventory or failed lookup cannot prove
deletion or resource absence. Poll/watch deadlines stop observation only.

### Named whole-factory status and reconciliation

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

If execution finished but local completion was interrupted, the named reconcile
operation can apply **existing verified exact pipeline/cohort receipts** and
complete local catalog cleanup. It does not call Azure, redispatch, retry failed
pipelines, invent absence evidence, or repair arbitrary partial deletion.
Missing/incomplete receipts remain blocked. Preserve claims and receipts; never
clear locks, re-enroll or force source changes as a recovery shortcut.

After reviewing that existing job's evidence, choose ONE reconciliation interface:

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
if ($LASTEXITCODE -ne 0) { throw 'Reconciliation unavailable or incomplete; retain evidence.' }
```

```powershell
# SDK
@'
import json, sys
from azurefactory import AzureFactoryClient
print(json.dumps(AzureFactoryClient().delete_aifactory_reconcile(sys.argv[1], sys.argv[2]), indent=2))
'@ | & $Python - $Folder $JobId
```

There is no corresponding friendly universal project/scale-set reconciliation
command in this SDK/CLI. Observe their original jobs and use operator-supported
receipt reconciliation; do not route them through the named factory reconciler.
An expired **unused** review can be prepared again after refreshing scope. An
uncertain **confirmed** operation must first be observed/reconciled.

## 7. Optional operational observers — not deletion prerequisites

Health/doctor/schema/auth checks establish host/API information, not live
deployment success. Catalog inventory is registered configuration and recorded
evidence; runtime prepare obtains its separate exact inventory. The following
read-only probes are optional against an authorized real host:

```powershell
& $Python -m azurefactory health
& $Python -m azurefactory doctor
& $Python -m azurefactory schema --openapi
& $Python -m azurefactory bootstrap capabilities
$ObservedScaleSetId = Read-Host 'Exact scale-set UUID for the scoped Azure auth check'
& $Python -m azurefactory auth status --folder $Folder --factory-id $FactoryId `
    --scale-set-id $ObservedScaleSetId
```

### GitHub Actions status/watch — not an ADO watcher

Use the exact repository and run ID from a reviewed operation/provider receipt:

```powershell
$Repository = Read-Host 'Exact GitHub OWNER/REPO from the execution receipt'
$RunId = Read-Host 'Exact GitHub Actions numeric run ID'
& $Python -m azurefactory workflow status --repository $Repository --run-id $RunId --json
& $Python -m azurefactory workflow watch --repository $Repository --run-id $RunId `
    --timeout 120 --json
```

Watch uses the read-only event feed; reconnecting that feed does not retry a
workflow. Its `after` cursor resumes observations. Closing a watch does not
cancel the provider run. These commands do not dispatch and do not monitor ADO.
Use provider-specific operator evidence for ADO and the original catalog job.

### Sample reports, saved evidence and actual Azure billing are different

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

`sample` is explicitly synthetic, not live cost or deployment evidence.
`monitoring saved` reads existing authorized saved evidence and projects it
through report calculations without collection/import/jobs. Unavailable,
partial, stale or empty evidence must not be relabeled healthy or zero.
The report source label `live` means supplied observation evidence; it does not
silently start an Azure collector.

Actual resource-group costs make an **Azure Cost Management read** for explicitly
selected subscriptions; run only with authorization for that read:

```powershell
$CostSubscription = Read-Host 'Exact authorized subscription UUID for Azure billing reads'
$CostMonth = Read-Host 'Billing month YYYY-MM'
& $Python -m azurefactory monitoring resource-group-costs --subscription $CostSubscription `
    --month $CostMonth --folder $Folder
```

Do not use billing lag or a zero/missing charge as proof of resource absence.

### Verified REST and SDK observer mappings

`AzureFactoryClient()` uses the URL/key environment variables from chapter 18.
All query/body paths are API-host paths. POST observers are read-only in purpose;
generic CLI transport still requires `--write --yes` for them.

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
| `monitoring saved summary/report` | Read saved evidence, then POST `/api/v1/monitoring/summary` or `/report` only for available evidence; not `/saved/summary` | `monitoring_saved_summary(context)` / `monitoring_saved_report(context, report_id="showback")` |
| `monitoring resource-group-costs` | `POST /api/v1/monitoring/resource-group-costs`; `subscription_ids`, optional `month`, `aifactory_folder`, `refresh` | `resource_group_costs(body)` |

## 8. Contract evidence and limitations

Canonical API source and tests (external repository, not duplicated schemas):

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

Accelerator client and runtime evidence:

* [CLI parser/handlers](../../../environment_setup/azurefactory-cli/src/azurefactory/cli.py),
  [SDK methods](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py),
  [named deletion validator](../../../environment_setup/azurefactory-cli/src/azurefactory/factory_deletion.py),
  [saved evidence adapter](../../../environment_setup/azurefactory-cli/src/azurefactory/monitoring_saved.py),
  and [workflow event observer](../../../environment_setup/azurefactory-cli/src/azurefactory/workflow_events.py).
* [Named deletion client tests](../../../environment_setup/azurefactory-cli/tests/test_factory_deletion.py),
  [operation-result tests](../../../environment_setup/azurefactory-cli/tests/test_operation_results.py),
  [lifecycle engine](../../../bootstrap/lib/factory_lifecycle.py),
  and [lifecycle execution and recovery contract](../../../bootstrap/lib/factory_lifecycle_contract.txt).

Bounded graph navigation was checked before writing: the API graph was current
(`de669aa8…`, 566 indexed files); accelerator graph was fresh (`ae9853f9…`, 1,653
files, 23 partial-syntax files). Static/resolved symbols and observed architecture
notes guided direct source/test reads; graphs did not establish installed or
Azure state. Published client additions were checked directly because original
dirty-checkout graph/HEAD evidence alone did not cover every newer addition.
Architecture notes are observations, not authorization or accepted deployment
decisions. No cloud operation, dispatch, deletion, installation, source-pin
change or live execution verification was performed to write this chapter.
