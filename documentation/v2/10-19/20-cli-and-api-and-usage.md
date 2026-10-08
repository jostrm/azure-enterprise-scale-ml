# 20. Remove, observe and recover

Use this page to remove saved settings, remove a draft, or review resource deletion.
Complete the core installation in [18 — setup](18-cli-and-api-and-usage.md) first.
[19 — ADD and UPDATE](19-cli-and-api-and-usage.md) covers configuration and deployment.
Choose **one tab** and stay in it: each has its own setup, review, confirmation and observation steps.
On GitHub, expand the matching tool section. The documentation website presents
the same content as a single linked tab selector.

!!! warning "Resource deletion is destructive"

    Removing configuration is **not** deleting Azure resources. Preparation is
    **not approval** and can read real Azure and pipeline information.
    **STOP and review before confirming.** Confirm once only; a lost response or
    timeout means **unknown outcome**, not permission to retry. Use an approved
    real host and identity, never chapter 18's empty demo folder or example key.
    API folder paths refer to the **API host**, not your client computer.

## Choose your tool

<details markdown="1" data-factory-tool="CLI (PowerShell)">
<summary>CLI (PowerShell)</summary>

## 1. Connect and select the exact factory

Use PowerShell with the interpreter and accelerator checkout installed in
chapter 18. This setup does not depend on variables from another window or
a global `azurefactory` executable. Start a **new review directory and fresh
catalog read for each operation**. Keep review files private, outside Git,
template folders and temporary directories; on Windows use a parent with
approved private NTFS permissions.

```powershell
$ErrorActionPreference = 'Stop'
$Python = Read-Host 'Full path to the chapter 18 Python interpreter'
$AcceleratorRoot = Read-Host 'Full path to the installed accelerator checkout'
$SdkSource = Join-Path $AcceleratorRoot 'environment_setup\azurefactory-cli\src'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $SdkSource -PathType Container)) {
    throw 'Complete the core installation in chapter 18.'
}
$env:PYTHONPATH = $SdkSource
$env:AIFACTORY_API_URL = Read-Host 'Approved real API base URL (HTTPS, or approved loopback HTTP)'
if (-not $env:AIFACTORY_API_KEY) {
    $Secret = Read-Host 'API key for that host' -AsSecureString
    $env:AIFACTORY_API_KEY = [System.Net.NetworkCredential]::new('', $Secret).Password
    Remove-Variable Secret
}
if (-not $env:AIFACTORY_API_URL -or -not $env:AIFACTORY_API_KEY) { throw 'URL and key are required.' }
$Folder = Read-Host 'Exact registered factory folder on the API host'
if ([string]::IsNullOrWhiteSpace($Folder)) { throw 'An explicit folder is required.' }
$ReviewBase = Read-Host 'Existing private local review directory, outside Git and temp'
if (-not (Test-Path -LiteralPath $ReviewBase -PathType Container)) { throw 'Choose an existing private directory.' }
$ReviewDir = Join-Path $ReviewBase ('remove-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $ReviewDir
$Utf8 = [System.Text.UTF8Encoding]::new($false)
function Write-NewText([string]$Path, [string]$Text) {
    $Stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try { $Bytes = $Utf8.GetBytes($Text); $Stream.Write($Bytes, 0, $Bytes.Length) }
    finally { $Stream.Dispose() }
}
function Invoke-FactoryJson([string[]]$Arguments, [string]$Name) {
    $Path = Join-Path $ReviewDir $Name
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite $Path" }
    $Raw = & $Python -m azurefactory @Arguments
    $Code = $LASTEXITCODE
    Write-NewText $Path ($Raw -join "`n")
    if ($Code -ne 0) {
        Get-Content -Raw -LiteralPath $Path | Write-Host
        throw "Command exited $Code. Keep its output; do not retry a confirmation."
    }
    return (($Raw -join "`n") | ConvertFrom-Json)
}
$Catalog = Invoke-FactoryJson @('catalog', 'list', '--folder', $Folder) 'catalog.json'
$Catalog | ConvertTo-Json -Depth 100
$FactoryId = Read-Host 'Exact factory UUID from this catalog'
$Matches = @($Catalog.factories | Where-Object { $_.id -ceq $FactoryId })
if ($Matches.Count -ne 1) { throw 'Select exactly one returned factory UUID.' }
$Factory = $Matches[0]
$Revision = $Catalog.revision
$ReceiptPath = Join-Path $ReviewDir 'review.receipt.json'
$Settings = Invoke-FactoryJson @('catalog', 'settings', '--folder', $Folder,
    '--factory-id', $FactoryId) 'settings.json'
$Settings | ConvertTo-Json -Depth 100
```

## 2. Prepare ONE change

Named preparation commands are **implemented**; they do not execute deletion.
Azure execution is **conditional** and can be **blocked** by source/runtime
capabilities, ownership, retention, permissions or deployment records. Never
bypass a blocker with legacy commands, direct Azure deletion or a mode change.

### A. Unset an override or reset a parameter profile — no Azure deletion

Unset returns to a default or inherited value where available. **Reset removes
all old saved parameter settings in the selected scale set, even when a
project is selected**, before saving reviewed replacements. Missing required
values can block preparation; use chapter 19 to supply them.

```powershell
$ScaleSetId = Read-Host 'Exact scale-set UUID for parameter settings'
$ProjectId = Read-Host 'Exact project UUID, or blank for common parameters'
$ScopeArgs = @('--folder', $Folder, '--factory-id', $FactoryId, '--scale-set-id', $ScaleSetId)
if ($ProjectId) { $ScopeArgs += @('--project-id', $ProjectId) }
$Parameters = Invoke-FactoryJson (@('parameters', 'get') + $ScopeArgs) 'parameters.json'
$Parameters | ConvertTo-Json -Depth 100
$Template = Read-Host 'Exact template name from this read'
if ($Template -cnotin @($Parameters.templates.template)) { throw 'Unknown template.' }
$Edit = Read-Host 'Choose unset or reset-profile'
$EditArgs = @()
if ($Edit -ceq 'unset') {
    $Field = Read-Host 'Exact configured parameter name to unset'
    if ([string]::IsNullOrWhiteSpace($Field)) { throw 'A parameter name is required.' }
    $EditArgs = @('--unset', $Field)
} elseif ($Edit -ceq 'reset-profile') {
    $EditArgs = @('--reset-profile')
} else { throw 'Choose unset or reset-profile.' }
$ConfirmFamily = 'parameters'
$ExpectedMode = 'configuration'
$Preview = Invoke-FactoryJson (@('parameters', 'prepare') + $ScopeArgs + @(
    '--template', $Template, '--expected-revision', $Parameters.source_revision,
    '--schema-revision', $Parameters.schema_revision, '--save-receipt', $ReceiptPath
) + $EditArgs) 'preview.json'
$Preview | ConvertTo-Json -Depth 100
```

### B. Remove a draft factory, scale set or project — local configuration only

The server must prove `deployment_state: draft`. Deployed, unknown,
interrupted or conflicting records do not qualify. Confirmation archives
reviewed local files in `draft-removals`; it neither starts pipelines nor
deletes Azure resources, repositories or subscriptions.

```powershell
$Kind = Read-Host 'Draft kind: factory, scale-set, or project'
if ($Kind -cnotin @('factory', 'scale-set', 'project')) { throw 'Invalid draft kind.' }
$TargetArgs = @()
if ($Kind -ceq 'scale-set') { $TargetArgs = @('--scale-set-id', (Read-Host 'Exact draft scale-set UUID')) }
if ($Kind -ceq 'project') { $TargetArgs = @('--project-id', (Read-Host 'Exact draft project UUID')) }
$ConfirmFamily = 'catalog'
$ExpectedMode = 'configuration'
$Preview = Invoke-FactoryJson (@('draft', 'remove', '--folder', $Folder,
    '--factory-id', $FactoryId, '--kind', $Kind, '--expected-revision', $Revision,
    '--save-receipt', $ReceiptPath) + $TargetArgs) 'preview.json'
$Preview | ConvertTo-Json -Depth 100
```

### C. Delete project resources in selected environments

Choose each environment once, in any order. The two required `yes|no` flags
are independent: `no` keeps the named resources; `yes` includes them in the
deletion review. Subnet approval does not approve shared-group deletion.
Check every exact delete/retain resource ID.

**Modern layout version 2 is required. Single-writer selective project deletion
is blocked.** The selected source must support `selective-project-resources-v1`
and the server must resolve one registered placement per environment.
This is the ordinary selective lifecycle path, **not automatically a GitHub
Actions or whole-factory ordered-pipeline operation**.

```powershell
if ($Catalog.layout_version -ne 2) { throw 'Modern layout version 2 is required.' }
$ProjectId = Read-Host 'Exact project UUID to review'
$Environments = @((Read-Host 'Environments, comma-separated: dev, stage, prod').Split(',') |
    ForEach-Object { $_.Trim() })
if ($Environments.Count -lt 1 -or $Environments.Count -gt 3 -or
    @($Environments | Where-Object { $_ -cnotin @('dev', 'stage', 'prod') }).Count -ne 0 -or
    @($Environments | Select-Object -Unique).Count -ne $Environments.Count) {
    throw 'Choose valid, unique environments.'
}
$SubnetFlag = Read-Host 'Include project subnets? yes or no'
$GroupFlag = Read-Host 'Include Key Vault and project resource group? yes or no'
if ($SubnetFlag -cnotin @('yes', 'no') -or $GroupFlag -cnotin @('yes', 'no')) {
    throw 'Both independent yes/no choices are required.'
}
$EnvironmentArgs = @()
foreach ($Environment in $Environments) { $EnvironmentArgs += @('--environment', $Environment) }
$ConfirmFamily = 'runtime'
$ExpectedMode = 'runtime'
$Preview = Invoke-FactoryJson (@('project', 'delete', '--folder', $Folder,
    '--factory-id', $FactoryId, '--project-id', $ProjectId,
    '--include-project-subnets', $SubnetFlag, '--include-keyvault-and-resource-group', $GroupFlag,
    '--expected-revision', $Revision, '--save-receipt', $ReceiptPath) + $EnvironmentArgs) 'preview.json'
$Preview | ConvertTo-Json -Depth 100
```

Verified group deletion updates affected deployment settings. Removing every
placement can also remove local project configuration; services-only deletion
keeps it. Neither removes the factory or its scale sets. Azure soft-delete
and retention rules still apply.

### D. Delete a scale set's runtime resources

This is not draft removal. Shared dependencies, active projects or retained
resources can block it. A group appearing in the preview is not itself
approval to delete the whole group: inspect its `delete` and `retain` lists.

```powershell
$ScaleSetId = Read-Host 'Exact scale-set UUID whose Azure resources you want to review'
$ConfirmFamily = 'runtime'
$ExpectedMode = 'runtime'
$Preview = Invoke-FactoryJson @('scaleset', 'delete', '--folder', $Folder,
    '--factory-id', $FactoryId, '--scale-set-id', $ScaleSetId,
    '--expected-revision', $Revision, '--save-receipt', $ReceiptPath) 'preview.json'
$Preview | ConvertTo-Json -Depth 100
```

### E. Delete the whole factory — separate named operation

**Whole resource groups are deleted. Selective retention inside them is not
implemented.** Protected hub/VPN/platform/bootstrap resources, coordination
storage, the executing identity and private runners must be outside them.
Entra security groups and Git repositories/history stay. Key Vault purge is
not performed; other external dependencies need separate review.

Execution is **conditional** on named ordered-pipeline support and **Blob**
coordination. The API's frozen accelerator pin does not provide that ordered
runtime contract; updating this client does not update the pin or your runtime.
No automatic mode change occurs. All registered project GHA **or ADO**
deletion pipelines must finish in every environment before shared groups are
removed; starting a pipeline is not success. Local configuration is removed
only after verified completion.

```powershell
$ConfirmFamily = 'delete-aifactory'
$ExpectedMode = 'runtime'
$Preview = Invoke-FactoryJson @('delete-aifactory', 'prepare', '--folder', $Folder,
    '--factory-id', $FactoryId, '--expected-revision', $Revision,
    '--save-receipt', $ReceiptPath) 'preview.json'
$Preview | ConvertTo-Json -Depth 100
```

The CLI validates the ordered plan before writing its typed receipt. Review
exact pipelines, source commit, dependencies, plan hash, limitations and
retained-resource lists, not just `can_execute`.

## 3. STOP — review, then separately confirm once

Review the full request and preview: factory, project/scale set, environments,
tenant/subscription, mode, revision, expiry, both project choices, settings,
resource IDs to delete/keep, warnings and blockers. Obtain approval for that
exact scope. A blocked or expired review is not approval.

Run this **separate block only after approval**. It chooses `parameters confirm`
for A, `catalog confirm` for B, `runtime confirm` for C/D, and the named
whole-factory confirm for E. The CLI rechecks its **typed receipt**; a raw REST
preview is not a receipt. The local marker prevents this example from sending
the confirmation twice from the same workspace.

```powershell
$Review = Get-Content -Raw -LiteralPath $ReceiptPath | ConvertFrom-Json
if ($Review.can_execute -ne $true -or $Review.operation_mode -cne $ExpectedMode -or
    @($Review.preview.blockers).Count -ne 0 -or
    [DateTimeOffset]::Parse($Review.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Blocked, incompatible or expired review.'
}
if ((Read-Host 'After reviewing the scope, retype the exact factory UUID') -cne $FactoryId) {
    throw 'Scope was not approved.'
}
if ((Read-Host 'Type CONFIRM-ONCE only after approval') -cne 'CONFIRM-ONCE') { throw 'Stopped.' }
$ConfirmArgs = @($ConfirmFamily, 'confirm', '--receipt', $ReceiptPath, '--yes')
if ($ConfirmFamily -ceq 'delete-aifactory') {
    $Phrase = Read-Host 'Type the exact server confirmation_phrase from the review'
    if ($Phrase -cne $Review.preview.confirmation_phrase) { throw 'Phrase mismatch.' }
    $ConfirmArgs += @('--confirmation-phrase', $Phrase)
}
Write-NewText (Join-Path $ReviewDir 'confirmation-attempted.txt') $Review.confirmation_id
$Result = Invoke-FactoryJson $ConfirmArgs 'confirmation-result.json'
if ($Result.job.id) { Write-NewText (Join-Path $ReviewDir 'job-id.txt') $Result.job.id }
$Result | ConvertTo-Json -Depth 100
```

Interactive whole-factory confirmation also presents the CLI's own approval
and phrase prompts. A settings-only result can contain `catalog` without a
job. A resource operation returns `job.id`; the result is saved before
observation. If any command fails, keep the saved response and errors.

## 4. Observe or recover — never repeat deletion to check it

If a response was lost, correlate jobs by action, exact scope, source and time
using the same API identity. **Never select the first job automatically.**
If correlation is uncertain, stop and ask the owning operator to inspect it.

```powershell
$Jobs = Invoke-FactoryJson @('catalog', 'jobs', '--folder', $Folder) ('jobs-' + [guid]::NewGuid() + '.json')
$Jobs | ConvertTo-Json -Depth 100
$JobId = Read-Host 'Exact correlated job UUID from the saved result or job list'
$Status = Invoke-FactoryJson @('runtime', 'status', '--folder', $Folder, '--job-id', $JobId) ('status-' + [guid]::NewGuid() + '.json')
$Status | ConvertTo-Json -Depth 100
$Logs = Invoke-FactoryJson @('runtime', 'logs', '--folder', $Folder, '--job-id', $JobId, '--cursor', '0') ('logs-' + [guid]::NewGuid() + '.json')
$Logs | ConvertTo-Json -Depth 100
$Status = Invoke-FactoryJson @('runtime', 'poll', '--folder', $Folder, '--job-id', $JobId,
    '--poll-timeout', '120', '--poll-interval', '5') ('poll-' + [guid]::NewGuid() + '.json')
$Status | ConvertTo-Json -Depth 100
```

Statuses are `queued`, `running`, `succeeded`, `failed`, `interrupted`.
Timeout only stops waiting; it neither cancels nor retries the operation.
Missing logs or a successful local process exit do not prove deletion.

For a job whose action is exactly `delete-factory`, read named status:

```powershell
$WholeStatus = Invoke-FactoryJson @('delete-aifactory', 'status', '--folder', $Folder,
    '--job-id', $JobId) ('whole-status-' + [guid]::NewGuid() + '.json')
$WholeStatus | ConvertTo-Json -Depth 100
```

Inspect `pipeline_runs`, `deletion_plan` and `reconciliation_required`. If
verified Azure completion is recorded but local cleanup was interrupted,
review those records, then run the following **separately**:

```powershell
if ((Read-Host 'Retype the reviewed delete-factory job UUID for local cleanup') -cne $JobId) { throw 'Stopped.' }
$Cleanup = Invoke-FactoryJson @('delete-aifactory', 'reconcile', '--folder', $Folder,
    '--job-id', $JobId) ('reconcile-' + [guid]::NewGuid() + '.json')
$Cleanup | ConvertTo-Json -Depth 100
```

Reconcile uses saved, verified completion records. It does not call Azure,
restart pipelines or retry deletion. Missing records keep it blocked.
General project/scale-set recovery is **not implemented** here. Keep locks and
job records; do not clear them or re-register the factory as a shortcut.

## 5. Optional read-only checks and reports

These **implemented** reads do not prove deletion. Run each independently;
check its exit code and displayed diagnostics.

```powershell
& $Python -m azurefactory health
if ($LASTEXITCODE -ne 0) { throw 'Health read failed.' }
& $Python -m azurefactory doctor
if ($LASTEXITCODE -ne 0) { throw 'Compatibility checks failed.' }
& $Python -m azurefactory schema --openapi
if ($LASTEXITCODE -ne 0) { throw 'Schema read failed.' }
& $Python -m azurefactory bootstrap capabilities
if ($LASTEXITCODE -ne 0) { throw 'Capability read failed.' }
$ObservedScaleSetId = Read-Host 'Exact scale-set UUID for an authorized Azure sign-in check'
& $Python -m azurefactory auth status --folder $Folder --factory-id $FactoryId --scale-set-id $ObservedScaleSetId
if ($LASTEXITCODE -ne 0) { throw 'Scoped sign-in check failed.' }
```

### GitHub Actions status and watch — not Azure DevOps

Use the exact repository/run recorded for the operation. These commands
observe; they do not start a pipeline. For ADO use its provider results and
the original catalog job.

```powershell
$Repository = Read-Host 'Exact GitHub OWNER/REPO from the operation record'
$RunId = Read-Host 'Exact GitHub Actions numeric run ID'
& $Python -m azurefactory workflow status --repository $Repository --run-id $RunId --json
if ($LASTEXITCODE -ne 0) { throw 'Workflow status unavailable or unsuccessful.' }
& $Python -m azurefactory workflow watch --repository $Repository --run-id $RunId --timeout 120 --json
if ($LASTEXITCODE -ne 0) { throw 'Inspect workflow diagnostics; timeout is not cancellation.' }
```

Reconnecting a read-only watch does not restart the workflow. The `after`
cursor can resume observation; closing the watch does not cancel the run.

### Sample metrics, saved metrics and Azure costs are different

```powershell
& $Python -m azurefactory monitoring catalog
if ($LASTEXITCODE -ne 0) { throw 'Monitoring catalog unavailable.' }
& $Python -m azurefactory monitoring report --source sample --report showback
if ($LASTEXITCODE -ne 0) { throw 'Sample report failed.' }
& $Python -m azurefactory monitoring summary --source sample
if ($LASTEXITCODE -ne 0) { throw 'Sample summary failed.' }
& $Python -m azurefactory monitoring export --source sample --report showback --format csv
if ($LASTEXITCODE -ne 0) { throw 'Sample export failed.' }
& $Python -m azurefactory monitoring saved read --folder $Folder --factory-id $FactoryId
if ($LASTEXITCODE -ne 0) { throw 'Saved results unavailable or incompatible.' }
& $Python -m azurefactory monitoring saved summary --folder $Folder --factory-id $FactoryId
if ($LASTEXITCODE -ne 0) { throw 'Saved summary failed.' }
& $Python -m azurefactory monitoring saved report --folder $Folder --factory-id $FactoryId --report showback
if ($LASTEXITCODE -ne 0) { throw 'Saved report failed.' }
```

`sample` is demonstration data. Saved metrics read authorized stored results,
without collection, imports or job starts. `live` means supplied observations,
not automatic Azure collection. Missing, stale, incomplete or empty results
are not healthy/zero-cost results.

The next command makes an **Azure Cost Management read**. Run only with
permission for that explicit subscription; billing can arrive late.

```powershell
$CostSubscription = Read-Host 'Exact authorized subscription UUID for billing reads'
$CostMonth = Read-Host 'Billing month YYYY-MM'
& $Python -m azurefactory monitoring resource-group-costs --subscription $CostSubscription --month $CostMonth --folder $Folder
if ($LASTEXITCODE -ne 0) { throw 'Azure billing read failed; missing costs are not zero.' }
```

<details markdown="1">
<summary>More info</summary>

### Alternatives in this interface

`catalog job`, `catalog logs` and `catalog poll` read the same jobs as the
`runtime` commands, with the same folder/job/cursor/poll arguments.
`schema` without `--openapi` reads the compact schema.

For nonsecret setting replacements, rather than ARM parameter unset/reset,
start a new review and use the implemented `catalog configure-settings`
command. Omitted keys stay unchanged; setting a flag false does not delete
resources. It uses `catalog confirm`, not `runtime confirm`.

```powershell
$SettingsPath = Read-Host 'Full path to a reviewed nonsecret replacement-settings JSON object'
$ConfirmFamily = 'catalog'
$ExpectedMode = 'configuration'
$Preview = Invoke-FactoryJson @('catalog', 'configure-settings', '--folder', $Folder,
    '--factory-id', $FactoryId, '--settings-json', $SettingsPath,
    '--expected-revision', $Revision, '--save-receipt', $ReceiptPath) 'preview.json'
$Preview | ConvertTo-Json -Depth 100
```

Generic request access is an alternative, not missing named deletion support.
A route with no friendly wrapper is **generic-access only**. All generic
POSTs require the CLI's `--write --yes`, even preparation or read-only reports;
these switches permit the HTTP request, not deletion without review.
Raw generic previews and typed receipts are different formats; do not pass
a raw preview to a receipt-based confirmation command.

Both project/scale-set runtime receipts and draft/configuration receipts have
purpose `catalog-confirm`; the operation and mode distinguish them.
Parameter receipts have purpose `parameters-confirm`. Whole-factory receipts
have purpose `delete-aifactory-confirm`.

</details>

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="Python SDK">
<summary>Python SDK</summary>

## 1. Connect and select the exact factory

Use Python 3.10 or later and the reviewed accelerator source folder from
[chapter 18](18-cli-and-api-and-usage.md). These are **Python** blocks for a
Python REPL, notebook, or editor's interactive session, not shell commands.
Run setup, then **one preparation block**. Do not combine this page into a
script that prepares and automatically confirms. Confirmation is a separate,
explicitly called function after review.

Choose a private review parent outside Git, templates and temporary
directories. On Windows, verify its NTFS permissions; Python's mode bits do
not establish a private Windows ACL. Start setup again for each new operation.

```python
import getpass
import json
import os
import pathlib
import sys
import time
import uuid

accelerator = pathlib.Path(input("Reviewed accelerator source folder: ").strip()).expanduser().resolve()
sdk_source = accelerator / "environment_setup" / "azurefactory-cli" / "src"
if not (sdk_source / "azurefactory" / "client.py").is_file():
    raise ValueError("Select the accelerator folder containing the Factory SDK.")
sys.path.insert(0, str(sdk_source))

from azurefactory import AzureFactoryClient
from azurefactory import catalog_requests
from azurefactory.client import catalog_settings_request, redact_secrets
from azurefactory.factory_deletion import validate_deletion_preview
from azurefactory.review import load_receipt, validate_preview, write_receipt

def required(prompt):
    value = input(prompt).strip()
    if not value:
        raise ValueError("An explicit value is required.")
    return value

api_url = required("Approved real API base URL (HTTPS or approved loopback HTTP): ")
api_key = os.environ.get("AIFACTORY_API_KEY") or getpass.getpass("API key for that host: ")
if not api_key:
    raise ValueError("An authenticated API key is required.")
client = AzureFactoryClient(base_url=api_url, api_key=api_key)
del api_key
folder = required("Exact registered factory folder on the API host: ")
review_base = pathlib.Path(required("Existing private review parent outside Git/temp: ")).expanduser()
if not review_base.is_dir():
    raise ValueError("Choose an existing private directory.")
review_dir = review_base / ("remove-" + uuid.uuid4().hex)
review_dir.mkdir(mode=0o700)
receipt_path = review_dir / "review.receipt.json"

def save_json(name, value):
    clean = redact_secrets(value, client.api_key)
    with (review_dir / name).open("x", encoding="utf-8") as stream:
        json.dump(clean, stream, indent=2, ensure_ascii=False)
    return clean

def show(value):
    print(json.dumps(redact_secrets(value, client.api_key), indent=2, ensure_ascii=False))

catalog = client.catalog_list(folder)
show(save_json("catalog.json", catalog))
factory_id = required("Exact factory UUID from this catalog: ")
matches = [item for item in catalog["factories"] if item["id"] == factory_id]
if len(matches) != 1:
    raise ValueError("Select exactly one returned factory UUID.")
factory = matches[0]
revision = catalog["revision"]
show(save_json("settings.json", client.catalog_settings(folder, factory_id)))

def save_review(body, preview, purpose, operation, mode):
    show(save_json("preview.json", preview))
    validate_preview(preview)
    if preview.get("operation_mode") != mode:
        raise ValueError("Unexpected operation mode.")
    if preview.get("source_revision") != body["expected_revision"]:
        raise ValueError("The reviewed source revision changed.")
    if purpose == "delete-aifactory-confirm":
        validate_deletion_preview(body, preview)
    write_receipt(
        str(receipt_path), client=client, purpose=purpose, operation=operation,
        request_body=redact_secrets(body, client.api_key),
        preview=redact_secrets(preview, client.api_key),
    )
    print("STOP. Review the saved receipt and obtain approval; nothing was confirmed.")
```

`save_review` writes a plain JSON review file, not the client or API key.
Keep the folder private: the file is not encrypted. The SDK checks its format
and content, but a saved file is not approval.

## 2. Prepare ONE change

These friendly SDK methods are **implemented**. Execution of Azure deletions
remains **conditional** and can be **blocked** by ownership, retention,
permissions, source/runtime capability or deployment records. No helper
bypasses those checks or changes coordination mode.

### A. Unset an override or reset a parameter profile — no Azure deletion

Read real template/field names first. Unset uses defaults/inheritance where
available. **Reset clears all old saved settings in the selected scale set,
even with a project selected**, before saving reviewed replacements.
Required missing values can block it; use chapter 19 rather than guessing.

```python
scale_set_id = required("Exact scale-set UUID for parameters: ")
project_id = input("Exact project UUID, or blank for common parameters: ").strip() or None
parameters = client.catalog_parameters(folder, factory_id, scale_set_id, project_id)
show(save_json("parameters.json", parameters))
template = required("Exact returned template name: ")
if template not in {item["template"] for item in parameters["templates"]}:
    raise ValueError("Unknown template.")
edit = required("Choose unset or reset-profile: ")
if edit not in {"unset", "reset-profile"}:
    raise ValueError("Choose an exact operation.")
unset = [required("Exact configured parameter name to unset: ")] if edit == "unset" else []
body = {
    "contract_version": 1, "folder": folder, "factory_id": factory_id,
    "scale_set_id": scale_set_id, "project_id": project_id,
    "expected_revision": parameters["source_revision"],
    "schema_revision": parameters["schema_revision"],
    "reset_profile": edit == "reset-profile",
    "templates": [{"template": template, "parameters": {}, "unset": unset}],
}
save_review(body, client.parameter_prepare(body), "parameters-confirm", "parameters", "configuration")
```

### B. Remove draft local configuration

Choose `factory`, `scale-set` or `project`. The API must establish
`deployment_state: draft` and safe references before archival in
`draft-removals`. Unknown/interrupted/deployed records do not qualify.
Confirmation does not delete Azure resources, repositories or subscriptions,
and starts no pipelines.

```python
kind = required("Draft kind: factory, scale-set, or project: ")
if kind not in {"factory", "scale-set", "project"}:
    raise ValueError("Invalid draft kind.")
selection = {
    "folder": folder, "factory_id": factory_id, "kind": kind,
    "expected_revision": revision,
}
if kind == "scale-set":
    selection["scale_set_id"] = required("Exact draft scale-set UUID: ")
if kind == "project":
    selection["project_id"] = required("Exact draft project UUID: ")
body = catalog_requests.draft_remove_request(**selection)
save_review(body, client.draft_remove_prepare(**selection),
            "catalog-confirm", "draft-remove-" + kind, "configuration")
```

### C. Delete project resources in explicit environments

Each environment must be unique; order does not matter. Both choices below
become real Python/JSON booleans, never strings. `False` keeps the named
resources; `True` includes them. The subnet choice does not approve a shared
group. Inspect exact resource IDs and both delete/retain lists.

**Modern layout 2 is required; single-writer selective project deletion is
blocked.** The selected source must support `selective-project-resources-v1`,
with an exact registered placement per environment. This is the selective
lifecycle path, **not necessarily GitHub Actions or whole-factory pipelines**.

```python
if catalog.get("layout_version") != 2:
    raise ValueError("Modern layout version 2 is required.")
project_id = required("Exact project UUID: ")
environments = [value.strip() for value in required("Environments, comma-separated: dev, stage, prod: ").split(",")]
if (not environments or not set(environments) <= {"dev", "stage", "prod"}
        or len(environments) != len(set(environments))):
    raise ValueError("Select each valid environment once.")

def boolean_choice(prompt):
    answer = required(prompt)
    if answer not in {"true", "false"}:
        raise ValueError("An explicit true or false is required.")
    return answer == "true"

selection = {
    "folder": folder, "factory_id": factory_id, "project_id": project_id,
    "expected_revision": revision, "environments": environments,
    "include_project_subnets": boolean_choice("Include project subnets? true/false: "),
    "include_keyvault_and_resource_group": boolean_choice("Include Key Vault and project resource group? true/false: "),
}
body = catalog_requests.project_delete_request(**selection)
save_review(body, client.project_delete_prepare(**selection),
            "catalog-confirm", "project-delete", "runtime")
```

After verified group deletion the API updates affected deployment settings;
removing every placement can remove local project configuration.
Services-only deletion keeps configuration. Neither deletes the factory or
its scale sets. Azure retention and soft-delete rules still apply.

### D. Delete scale-set runtime resources

Not draft removal: shared dependencies, active projects and retained resources
can block deletion. A preview group row is not approval to delete its group;
inspect the exact delete/retain manifest.

```python
selection = {
    "folder": folder, "factory_id": factory_id,
    "scale_set_id": required("Exact scale-set UUID for runtime deletion: "),
    "expected_revision": revision,
}
body = catalog_requests.scaleset_delete_request(**selection)
save_review(body, client.scaleset_delete_prepare(**selection),
            "catalog-confirm", "scaleset-delete", "runtime")
```

### E. Delete the whole factory — named operation and plan validation

**Whole-group deletion cannot retain selected resources inside a deleted
group.** Reusable hub/VPN/platform/bootstrap resources, coordination storage,
the executing identity and private runners must be outside those groups.
Entra groups and Git repositories/history stay. No Key Vault purge occurs;
other external dependencies need separate review.

Execution is **conditional** on named ordered-pipeline support and **Blob**
coordination. The API's frozen accelerator pin lacks that ordered runtime
contract; installing a newer SDK does not upgrade it. Do not switch mode to
bypass a blocker. Every registered project's **GHA or ADO** deletion pipeline
in every environment must complete before shared-group removal. Configuration
cleanup follows verified success, not merely pipeline submission.

```python
body = {
    "contract_version": 1, "folder": folder,
    "factory_id": factory_id, "expected_revision": revision,
}
preview = client.delete_aifactory_prepare(body)
save_review(body, preview, "delete-aifactory-confirm", "delete-aifactory", "runtime")
```

The helper calls `validate_deletion_preview` before making a confirmable
receipt. This checks the ordered plan and hash, source and scope bindings,
retention and inventory. Still review all pipelines, dependencies, resources,
warnings, limitations and the exact server phrase yourself.

## 3. STOP — explicitly confirm an approved receipt, once

Review the request and full preview: exact factory, scope, environments,
tenant/subscription, deletion choices, delete/retain IDs, settings, revision,
mode, expiry and blockers. Do not use a stale, blocked or incomplete review.
The SDK confirm methods alone do not replace this review or receipt validation.

Define this function separately; **defining it sends nothing**. It requires
the intended operation/mode and a freshly typed scope. For whole-factory
deletion it revalidates the named plan and sends the server's exact
`preview_hash` plus the phrase you type.

```python
def confirm_review_once():
    purpose = required("Receipt purpose: parameters-confirm, catalog-confirm, or delete-aifactory-confirm: ")
    if purpose not in {"parameters-confirm", "catalog-confirm", "delete-aifactory-confirm"}:
        raise ValueError("Unknown receipt purpose.")
    mode = required("Reviewed operation mode: configuration or runtime: ")
    if mode not in {"configuration", "runtime"}:
        raise ValueError("Unknown mode.")
    receipt = load_receipt(str(receipt_path), client=client, purpose=purpose, operation_mode=mode)
    if receipt["folder"] != folder or receipt["request"]["factory_id"] != factory_id:
        raise ValueError("Receipt does not match this selected scope.")
    show(receipt)
    if required("Retype the exact reviewed operation from the receipt: ") != receipt["operation"]:
        raise ValueError("Operation was not approved.")
    if required("After approval, retype the exact factory UUID: ") != factory_id:
        raise ValueError("Scope was not approved.")
    if required("Type CONFIRM-ONCE: ") != "CONFIRM-ONCE":
        raise ValueError("Stopped.")
    phrase = None
    if purpose == "delete-aifactory-confirm":
        validate_deletion_preview(receipt["request"], receipt["preview"])
        phrase = input("Type the exact server confirmation_phrase: ")
        if phrase != receipt["preview"]["confirmation_phrase"]:
            raise ValueError("Phrase mismatch.")
    receipt = load_receipt(str(receipt_path), client=client, purpose=purpose, operation_mode=mode)
    with (review_dir / "confirmation-attempted.txt").open("x", encoding="utf-8") as stream:
        stream.write(receipt["confirmation_id"])
    if purpose == "delete-aifactory-confirm":
        result = client.delete_aifactory_confirm(
            folder=folder, confirmation_id=receipt["confirmation_id"],
            preview_hash=receipt["preview"]["preview_hash"], confirmation_phrase=phrase,
        )
    elif purpose == "parameters-confirm":
        result = client.parameter_confirm(folder, receipt["confirmation_id"])
    else:
        result = client.catalog_confirm(folder, receipt["confirmation_id"])
    save_json("confirmation-result.json", result)
    if (result.get("job") or {}).get("id"):
        save_json("job-id.json", {"job_id": result["job"]["id"]})
    show(result)
    return result
```

**Only after separate human approval**, call:

```python
result = confirm_review_once()
```

Parameter changes use `parameter_confirm`. Draft and scoped settings use
`catalog_confirm` in configuration mode; project/scale-set deletion uses
that same catalog endpoint in runtime mode. A settings result may have no job.
Exceptions are not suppressed, and the attempt marker remains if a response
is lost. Do not delete that marker to retry an uncertain confirmation.

## 4. Read status and logs; reconcile only the whole-factory job

Correlate a lost response by exact action, scope, source and time using the
same identity; never assume the first listed job is yours.

```python
show(save_json("jobs-" + uuid.uuid4().hex + ".json", client.catalog_jobs(folder)))
job_id = required("Exact correlated job UUID from the saved result or job list: ")
show(save_json("logs-" + uuid.uuid4().hex + ".json", client.catalog_terminal(folder, job_id, cursor=0)))
deadline = time.monotonic() + 120
while True:
    job = client.catalog_job(folder, job_id)
    show(save_json("status-" + uuid.uuid4().hex + ".json", job))
    if job["status"] in {"succeeded", "failed", "interrupted"}:
        break
    if job["status"] not in {"queued", "running"}:
        raise ValueError("Unknown status; stop and inspect.")
    if time.monotonic() >= deadline:
        raise TimeoutError("Observation stopped; the job was not cancelled or retried.")
    time.sleep(5)
```

There is no dedicated SDK `runtime_poll`; this bounded loop reads existing
jobs. A missing log, timeout or local exit code does not prove deletion.
If job correlation is uncertain, ask the owning operator to inspect it.

For an exact `delete-factory` job, read its named status:

```python
whole_status = client.delete_aifactory_status(folder, job_id)
show(save_json("whole-status-" + uuid.uuid4().hex + ".json", whole_status))
```

Inspect `pipeline_runs`, `deletion_plan`, `reconciliation_required` and the
saved completion records. If Azure deletion was verified but local cleanup
was interrupted, the following separate action finishes local cleanup:

```python
if required("Retype the reviewed delete-factory job UUID for local cleanup: ") != job_id:
    raise ValueError("Stopped.")
cleanup = client.delete_aifactory_reconcile(folder, job_id)
show(save_json("reconcile-" + uuid.uuid4().hex + ".json", cleanup))
```

Reconcile does not call Azure, restart pipelines or retry deletion. Missing
verified completion records keep it blocked. General project/scale-set
recovery is **not implemented** here; keep job records and locks intact.

## 5. Optional read-only checks and reports

Host/schema/sign-in checks do not establish deployment success. `doctor()`
is **not implemented** as an SDK method; the CLI's doctor performs client
compatibility checks rather than calling a `/doctor` route.

```python
show(client.health())
show(client.schema())
show(client.openapi())
show(client.creation_capabilities())
observed_scale_set_id = required("Exact scale-set UUID for an authorized Azure sign-in check: ")
show(client.auth_status(aifactory_folder=folder, factory_id=factory_id, scale_set_id=observed_scale_set_id))
```

### GitHub Actions observation — not Azure DevOps

```python
repository = required("Exact GitHub OWNER/REPO recorded for this operation: ")
run_id = int(required("Exact GitHub Actions numeric run ID: "))
show(client.get_workflow_run_status(repository, run_id))
events = client.watch_workflow_run(repository, run_id, after=None, follow=True, timeout=120)
try:
    for event in events:
        show(save_json("workflow-" + uuid.uuid4().hex + ".json", event))
finally:
    events.close()
```

These methods only observe GHA. Read-only feed reconnects do not restart
pipelines; `after` can resume from a returned event cursor. Closing or timing
out stops observation, not execution. For ADO use provider results and the
original catalog job.

### Sample metrics, saved metrics and actual Azure billing

```python
show(client.monitoring_catalog())
show(client.monitoring_report({"source": "sample", "report_id": "showback"}))
show(client.monitoring_summary({"source": "sample"}))
csv_text = client.monitoring_export({"source": "sample", "report_id": "showback", "format": "csv"})
with (review_dir / "sample-showback.csv").open("x", encoding="utf-8", newline="") as stream:
    stream.write(csv_text)
context = {"folder": folder, "factory_id": factory_id}
show(client.monitoring_evidence_read(context))
show(client.monitoring_saved_summary(context))
show(client.monitoring_saved_report(context, report_id="showback"))
```

`sample` is demonstration data. Saved metrics read authorized stored results,
without collection/imports/job starts. `live` means supplied observations,
not automatic Azure collection. Missing/stale/incomplete results do not
imply good health or zero costs.

This next call performs an **Azure Cost Management read** for an explicitly
permitted subscription. Billing can arrive late; zero charges do not prove
that a resource was deleted.

```python
subscription_id = required("Exact authorized subscription UUID for billing reads: ")
month = required("Billing month YYYY-MM: ")
show(client.resource_group_costs({
    "subscription_ids": [subscription_id], "month": month, "aifactory_folder": folder,
}))
```

<details markdown="1">
<summary>More info</summary>

### Settings replacement alternative

For nonsecret catalog settings rather than ARM parameter unset/reset,
start a new review, read `catalog_settings`, and supply only intentional
replacements. Omitted keys stay unchanged. This **implemented** method
never deploys or deletes resources, including when a service flag becomes false.

```python
settings_path = pathlib.Path(required("Path to a reviewed nonsecret settings JSON object: "))
settings = json.loads(settings_path.read_text(encoding="utf-8"))
selection = {"folder": folder, "factory_id": factory_id, "expected_revision": revision}
body = catalog_settings_request(**selection, settings=settings)
preview = client.catalog_settings_prepare(**selection, settings=settings)
save_review(body, preview, "catalog-confirm", "catalog-settings", "configuration")
```

Review and use the same separate `confirm_review_once()` function. Optional
`scale_set_id`/`project_id` arguments narrow the settings scope, not resource
deletion. Generic `catalog_prepare`/`request` remain alternatives; use them
only with a documented route and request contract. Features without a
friendly method are **generic-access only**, not automatically unavailable.
The named removal methods above are implemented, not generic-only.

</details>

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="REST (curl)">
<summary>REST (curl)</summary>

## 1. Connect using Bash or Git Bash

Required tools: **Bash (or Git Bash), curl 7.76+ with `--fail-with-body`,
jq 1.6+, and standard `mkdir`, `date`, `cat` utilities**. No Python,
PowerShell or Azure Factory CLI is needed. Use the approved API already set
up in [chapter 18](18-cli-and-api-and-usage.md); do not start a demo host for
real deletion.

Run setup in one Bash session, then one preparation choice. Select an existing
private review parent outside Git/templates/temp. `umask` protects POSIX
files; on Windows also verify the parent's NTFS permissions.
The key comes from your approved environment or a hidden prompt, never a file
in this review. Do not enable shell tracing.

```bash
set -euo pipefail
set +x
set -o noclobber
umask 077
command -v curl
command -v jq
read -r -p 'Approved real API base URL: ' base_url
base_url=${base_url%/}
case "$base_url" in
  https://*|http://127.0.0.1:*|http://localhost:*|http://\[::1\]:*) ;;
  *) printf '%s\n' 'Use HTTPS, or an explicitly approved loopback HTTP host.' >&2; exit 1 ;;
esac
if [[ -z ${AIFACTORY_API_KEY:-} ]]; then
  read -r -s -p 'API key for that host: ' AIFACTORY_API_KEY
  printf '\n'
fi
[[ -n "$AIFACTORY_API_KEY" ]]
[[ "$AIFACTORY_API_KEY" != *$'\n'* && "$AIFACTORY_API_KEY" != *$'\r'* ]]
read -r -p 'Exact registered factory folder on the API host: ' folder
[[ -n "$folder" ]]
read -r -p 'Existing private local review parent, outside Git/temp: ' review_base
[[ -d "$review_base" ]]
review_dir="$review_base/remove-$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM"
mkdir -m 700 -- "$review_dir"

call_api() {
  local output=$1 route=$2 code
  shift 2
  [[ ! -e "$output" ]] || { printf '%s\n' 'Refusing to overwrite output.' >&2; return 1; }
  if code=$(printf 'X-API-Key: %s\n' "$AIFACTORY_API_KEY" |
    curl --silent --show-error --fail-with-body --noproxy '*' \
      --header @- --output "$output" --write-out '%{http_code}' \
      "$@" "$base_url$route"); then
    [[ "$code" == 2* ]] || { cat "$output" >&2; return 1; }
  else
    [[ ! -f "$output" ]] || cat "$output" >&2
    printf '%s\n' 'Request failed. Keep the response; never retry an uncertain confirmation.' >&2
    return 1
  fi
}
get_json() {
  local output=$1 route=$2
  shift 2
  call_api "$output" "$route" --get "$@"
}
post_json() {
  call_api "$1" "$2" --request POST --header 'Content-Type: application/json' --data-binary "@$3"
}
get_json "$review_dir/catalog.json" /api/v1/factory-catalog --data-urlencode "folder=$folder"
jq . "$review_dir/catalog.json"
read -r -p 'Exact factory UUID from this catalog: ' factory_id
jq -e --arg id "$factory_id" '[.factories[] | select(.id == $id)] | length == 1' "$review_dir/catalog.json" >/dev/null
revision=$(jq -er '.revision' "$review_dir/catalog.json")
get_json "$review_dir/settings.json" /api/v1/factory-catalog/settings \
  --data-urlencode "folder=$folder" --data-urlencode "factory_id=$factory_id"
jq . "$review_dir/settings.json"
request_path="$review_dir/prepare-request.json"
preview_path="$review_dir/preview.json"
prepare_route=/api/v1/factory-catalog/prepare
confirm_route=/api/v1/factory-catalog/confirm
expected_mode=configuration
operation=catalog
```

Each call saves the response before displaying/parsing it, including HTTP
error bodies. No redirect following or automatic confirmation retries are
configured. JSON comes from quoted `jq -n` arguments, not string interpolation.

## 2. Build ONE request

Catalog action preparation/confirmation uses the same
`/api/v1/factory-catalog/prepare` and `/api/v1/factory-catalog/confirm` routes
for draft, scoped settings and project/scale-set deletion. ARM parameter
profiles use the `/parameters/prepare` and `/parameters/confirm` subroutes.
Whole-factory deletion uses its separate named operation routes.

These APIs are **implemented**. Azure execution is **conditional** and may
be **blocked** by source/runtime capabilities, ownership, retention,
permissions and deployment records. Do not work around failed checks.

### A. Unset an override or reset a saved parameter profile — no Azure deletion

Unset uses defaults or inheritance where available. **Reset clears old saved
parameter settings across the selected scale set, even when a project is
selected**, before saving reviewed replacements. Required missing values can
block preparation; see chapter 19 to supply them.

```bash
read -r -p 'Exact scale-set UUID for parameters: ' scale_set_id
read -r -p 'Exact project UUID, or blank for common parameters: ' project_id
query=(--data-urlencode "folder=$folder" --data-urlencode "factory_id=$factory_id"
       --data-urlencode "scale_set_id=$scale_set_id")
[[ -z "$project_id" ]] || query+=(--data-urlencode "project_id=$project_id")
get_json "$review_dir/parameters.json" /api/v1/factory-catalog/parameters "${query[@]}"
jq . "$review_dir/parameters.json"
read -r -p 'Exact returned template name: ' template
jq -e --arg name "$template" 'any(.templates[]; .template == $name)' "$review_dir/parameters.json" >/dev/null
read -r -p 'Choose unset or reset-profile: ' edit
unset_fields='[]'
reset=false
case "$edit" in
  unset)
    read -r -p 'Exact configured parameter name to unset: ' field
    [[ -n "$field" ]]
    unset_fields=$(jq -nc --arg field "$field" '[$field]')
    ;;
  reset-profile) reset=true ;;
  *) printf '%s\n' 'Choose unset or reset-profile.' >&2; exit 1 ;;
esac
jq -n --arg folder "$folder" --arg factory "$factory_id" --arg scale "$scale_set_id" \
  --arg project "$project_id" --arg template "$template" --argjson unset "$unset_fields" \
  --argjson reset "$reset" --slurpfile parameters "$review_dir/parameters.json" \
  '{contract_version:1, folder:$folder, factory_id:$factory, scale_set_id:$scale,
    project_id:(if $project == "" then null else $project end),
    expected_revision:$parameters[0].source_revision, schema_revision:$parameters[0].schema_revision,
    reset_profile:$reset, templates:[{template:$template, parameters:{}, unset:$unset}]}' > "$request_path"
prepare_route=/api/v1/factory-catalog/parameters/prepare
confirm_route=/api/v1/factory-catalog/parameters/confirm
operation=parameters
```

### B. Remove draft local configuration

The API must establish `deployment_state: draft` and safe references.
Deployed, unknown, interrupted and conflicting records cannot be treated as
drafts. Confirmation archives local files in `draft-removals`; it starts no
pipelines and deletes no Azure resources, repositories or subscriptions.

```bash
read -r -p 'Draft kind: factory, scale-set, or project: ' kind
scale_set_id=''
project_id=''
case "$kind" in
  factory) ;;
  scale-set) read -r -p 'Exact draft scale-set UUID: ' scale_set_id; [[ -n "$scale_set_id" ]] ;;
  project) read -r -p 'Exact draft project UUID: ' project_id; [[ -n "$project_id" ]] ;;
  *) printf '%s\n' 'Invalid draft kind.' >&2; exit 1 ;;
esac
jq -n --arg folder "$folder" --arg factory "$factory_id" --arg revision "$revision" \
  --arg kind "$kind" --arg scale "$scale_set_id" --arg project "$project_id" \
  '{contract_version:1, folder:$folder, factory_id:$factory, expected_revision:$revision,
    action:("delete-draft-" + $kind)}
   + (if $scale == "" then {} else {scale_set_id:$scale} end)
   + (if $project == "" then {} else {project_id:$project} end)' > "$request_path"
```

### C. Delete project resources in selected environments

Use unique environments in any order. Both independent choices must be JSON
booleans, not strings: `false` keeps the named resources; `true` includes them
for deletion. Subnet permission does not approve shared-group deletion.

**Modern layout 2 is required; single-writer selective project deletion is
blocked.** The selected source needs `selective-project-resources-v1` and
one exact registered placement per chosen environment. Ordinary project
deletion uses the selective lifecycle path; do not assume GitHub Actions
or the whole-factory ordered-pipeline path.

```bash
jq -e '.layout_version == 2' "$review_dir/catalog.json" >/dev/null
read -r -p 'Exact project UUID: ' project_id
read -r -p 'Environments, comma-separated: dev, stage, prod: ' environment_text
environments=$(jq -nc --arg value "$environment_text" '$value | split(",") | map(gsub("^\\s+|\\s+$"; ""))')
jq -e 'length > 0 and length <= 3 and length == (unique | length)
  and all(.[]; . == "dev" or . == "stage" or . == "prod")' <<< "$environments" >/dev/null
read -r -p 'Include project subnets? true or false: ' include_subnets
read -r -p 'Include Key Vault and project resource group? true or false: ' include_group
[[ "$include_subnets" == true || "$include_subnets" == false ]]
[[ "$include_group" == true || "$include_group" == false ]]
jq -n --arg folder "$folder" --arg factory "$factory_id" --arg revision "$revision" \
  --arg project "$project_id" --argjson environments "$environments" \
  --argjson subnets "$include_subnets" --argjson group "$include_group" \
  '{contract_version:1, folder:$folder, factory_id:$factory, expected_revision:$revision,
    action:"delete-project", project_id:$project,
    deletion_options:{environments:$environments, include_project_subnets:$subnets,
      include_keyvault_and_resource_group:$group}}' > "$request_path"
expected_mode=runtime
```

Verified group deletion updates affected deployment settings; removing every
placement can remove local project configuration. Services-only deletion
keeps it. Neither removes factory/scale-set configuration. Azure soft-delete
and retention rules still apply.

### D. Delete a scale set's runtime resources

This is not draft removal. Shared dependencies, retained resources and active
projects can block it. Inspect exact `delete` and `retain` lists; a group row
alone is not approval to delete that group.

```bash
read -r -p 'Exact scale-set UUID for runtime deletion: ' scale_set_id
jq -n --arg folder "$folder" --arg factory "$factory_id" --arg revision "$revision" \
  --arg scale "$scale_set_id" \
  '{contract_version:1, folder:$folder, factory_id:$factory, expected_revision:$revision,
    action:"delete-scale-set", scale_set_id:$scale}' > "$request_path"
expected_mode=runtime
```

### E. Delete the whole factory — separate named operation

**Whole-group deletion cannot preserve selected resources inside deleted
groups.** Protected hub/VPN/platform/bootstrap resources, coordination
storage, the executing identity and private runners must be outside them.
Entra groups and Git repositories/history stay. No Key Vault purge occurs;
other external dependencies need separate review.

Execution is **conditional** on named ordered-pipeline support and **Blob**
coordination. The API's frozen accelerator pin lacks the ordered runtime
contract; client publication does not upgrade it. No automatic mode change
occurs. Every registered project **GHA or ADO** pipeline in every environment
must finish before shared-group removal. Configuration cleanup follows
verified completion, not simply pipeline submission.

```bash
jq -n --arg folder "$folder" --arg factory "$factory_id" --arg revision "$revision" \
  '{contract_version:1, folder:$folder, factory_id:$factory, expected_revision:$revision}' > "$request_path"
prepare_route=/api/v1/operations/delete-aifactory/prepare
confirm_route=/api/v1/operations/delete-aifactory/confirm
expected_mode=runtime
operation=delete-aifactory
```

## 3. Prepare, save the raw preview, and STOP

All choices above join this flow. Unlike a CLI/SDK typed receipt,
`preview.json` is the **raw API preview**. It cannot be passed to a
receipt-based CLI confirmation.

```bash
post_json "$preview_path" "$prepare_route" "$request_path"
jq . "$preview_path"
check_preview() {
  jq -e --arg mode "$expected_mode" --arg operation "$operation" --slurpfile request "$request_path" '
    $request[0] as $r |
    .contract_version == 1 and .can_execute == true
    and (.can_execute | type) == "boolean"
    and (.blockers | type) == "array" and (.blockers | length) == 0
    and .operation_mode == $mode and .source_revision == $r.expected_revision
    and (.source_revision | type) == "string" and (.source_revision | test("^[a-f0-9]{64}$"))
    and .target.id == $r.factory_id
    and (if $operation == "parameters" then true else
      .factory_id == $r.factory_id
      and .scale_set_id == ($r.scale_set_id // null) and .project_id == ($r.project_id // null)
    end)
    and (.confirmation_id | type) == "string" and (.confirmation_id | length) > 0
    and ((.expires_at | sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdateiso8601) > now)
    and (if $r.action == "delete-project" then
      (.deletion_options.include_project_subnets | type) == "boolean"
      and (.deletion_options.include_keyvault_and_resource_group | type) == "boolean"
      and .deletion_options.include_project_subnets == $r.deletion_options.include_project_subnets
      and .deletion_options.include_keyvault_and_resource_group == $r.deletion_options.include_keyvault_and_resource_group
      and (.deletion_options.environments | sort) == ($r.deletion_options.environments | sort)
    else true end)' "$preview_path" >/dev/null
}
check_preview
```

The expiry check accepts the API's UTC timestamp; malformed/unsupported dates
fail closed. Review the request and full response: scope, environment,
tenant/subscription, source/revision, mode, settings, exact resources to
delete/keep, both project choices, warnings and blockers.

Parameter previews identify the target factory and source revision, not
separate top-level scale/project IDs. Review those IDs in the saved request
and the earlier parameter read; the server binds them to the confirmation ID.

For **whole-factory only**, also define and run this structural plan check.
It is not the SDK's complete plan/hash validator: inspect the entire saved
plan, its hash, immutable source, pipelines and manifests. The server
revalidates its stored plan at confirmation; never hand-edit a preview.

```bash
check_whole_preview() {
  jq -e --slurpfile request "$request_path" '
    $request[0] as $r | . as $p | .deletion_plan as $plan |
    .action == "delete-factory" and .folder == $r.folder
    and (.capabilities | index("delete-aifactory-v1")) != null
    and .deletion_scope == "whole-factory" and .deletion_options == null
    and .preserve_entra_groups == true and .retain_saved_configuration == false
    and .target.id == $r.factory_id and .confirmation_phrase == ("DELETE " + .target.key)
    and (.preview_hash | test("^[a-f0-9]{64}$"))
    and .deletion_retention_policy.mode == "preserve-reusable-infrastructure"
    and .deletion_retention_policy.required_execution_contract == "ordered-project-pipelines-v1"
    and .deletion_retention_policy.execution_scope == "whole-resource-groups"
    and .deletion_retention_policy.selective_retention_supported == false
    and (.deletion_retention_policy.limitations | type == "array" and length > 0)
    and $plan.retention_policy == .deletion_retention_policy
    and $plan.contract == "ordered-project-pipelines-v1"
    and $plan.factory_id == $r.factory_id and $plan.policy == "all-projects-before-common"
    and ($plan.plan_hash | test("^[a-f0-9]{64}$"))
    and ($plan.source_commit | test("^[a-f0-9]{40}$"))
    and ($plan.stages | type == "array" and length > 0)
    and ([ $plan.stages[].id ] | length == (unique | length))
    and all($plan.stages[]; .kind == "project" or .kind == "common")
    and ([$plan.stages[] | select(.kind == "project") | .id] as $projects |
      all($plan.stages[] | select(.kind == "common"); .depends_on == $projects))
    and ([$plan.stages[].kind] | . == (map(select(. == "project")) + map(select(. == "common"))))
    and all($plan.stages[] | select(.kind == "project");
      .depends_on == [] and .inputs == {
        enableDeleteForDisabledResources:true, deleteAllServicesForProject:true,
        deleteKeyvaultAlso:true, deleteAllForProject:true}
      and .lifecycle_order == ["foundry-capability-hosts","target-project-search-shared-private-links",
        "service-managed-lifecycle","project-resources","project-network"]
      and (.pipeline.provider == "gha" or .pipeline.provider == "ado")
      and (.pipeline.commit | test("^[a-f0-9]{40}$")))
    and (.deletion_targets | type == "array" and length > 0)
    and all(.deletion_targets[]; .retain == [] and (.resource_id as $id | .delete | index($id)) != null)
    and all(($plan.protected_resources + $plan.retained_resources)[]; . as $keep |
      all($p.deletion_targets[]; (.resource_id | ascii_downcase) as $group |
        ($keep | ascii_downcase | (. != $group and (startswith($group + "/") | not)))))' "$preview_path" >/dev/null
}
if [[ "$operation" == delete-aifactory ]]; then check_whole_preview; fi
printf '%s\n' 'STOP. Review the saved request and preview and obtain separate approval.'
```

## 4. After approval, POST confirmation exactly once

Run this block **separately**, after human review. Retype the confirmation ID
from this fresh, unexpired preview; whole-factory deletion additionally needs
the exact phrase and server hash. The local attempt marker remains even if
the response is lost. Do not remove it to retry.

```bash
check_preview
if [[ "$operation" == delete-aifactory ]]; then check_whole_preview; fi
confirmation_id=$(jq -er '.confirmation_id' "$preview_path")
read -r -p 'After approval, retype the exact factory UUID: ' approved_factory
[[ "$approved_factory" == "$factory_id" ]]
read -r -p 'Retype the confirmation_id from this reviewed preview: ' approved_id
[[ "$approved_id" == "$confirmation_id" ]]
read -r -p 'Type CONFIRM-ONCE: ' approval
[[ "$approval" == CONFIRM-ONCE ]]
if [[ "$operation" == delete-aifactory ]]; then
  read -r -p 'Type the exact server confirmation_phrase: ' phrase
  [[ "$phrase" == "$(jq -er '.confirmation_phrase' "$preview_path")" ]]
  jq -n --arg folder "$folder" --arg phrase "$phrase" --slurpfile preview "$preview_path" \
    '{contract_version:1, folder:$folder, confirmation_id:$preview[0].confirmation_id,
      preview_hash:$preview[0].preview_hash, confirmation_phrase:$phrase}' > "$review_dir/confirm-request.json"
else
  jq -n --arg folder "$folder" --arg id "$confirmation_id" \
    '{contract_version:1, folder:$folder, confirmation_id:$id}' > "$review_dir/confirm-request.json"
fi
check_preview
printf '%s\n' "$confirmation_id" > "$review_dir/confirmation-attempted.txt"
post_json "$review_dir/confirmation-result.json" "$confirm_route" "$review_dir/confirm-request.json"
jq . "$review_dir/confirmation-result.json"
if jq -e '.job.id | type == "string" and length > 0' "$review_dir/confirmation-result.json" >/dev/null; then
  jq -r '.job.id' "$review_dir/confirmation-result.json" > "$review_dir/job-id.txt"
fi
```

Configuration-only confirmation may return `catalog` without a job. Runtime
confirmation returns `job.id`; the response and ID are saved before any
observation. HTTP success alone does not prove resource deletion.

## 5. Observe, or finish local whole-factory cleanup

If a confirm response was lost, list jobs using the same identity and
correlate action, exact scope, source and time. Never choose the first job.
If unsure, stop and ask the owning operator to inspect the records.

```bash
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
get_json "$review_dir/jobs-$stamp.json" /api/v1/factory-catalog/jobs --data-urlencode "folder=$folder"
jq . "$review_dir/jobs-$stamp.json"
read -r -p 'Exact correlated job UUID from saved result or job list: ' job_id
[[ "$job_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]
get_json "$review_dir/status-$stamp.json" "/api/v1/factory-catalog/jobs/$job_id" --data-urlencode "folder=$folder"
jq . "$review_dir/status-$stamp.json"
get_json "$review_dir/logs-$stamp.json" /api/v1/factory-catalog/terminal \
  --data-urlencode "folder=$folder" --data-urlencode "job_id=$job_id" --data-urlencode 'cursor=0'
jq . "$review_dir/logs-$stamp.json"
```

Repeat **GETs only** with new output filenames to observe progress; there is
no REST poll endpoint. Statuses are `queued`, `running`, `succeeded`, `failed`,
`interrupted`. Timeout stops waiting, not the job. Missing logs do not prove
deletion or make another confirmation safe.

For a job whose action is exactly `delete-factory`, read named status:

```bash
get_json "$review_dir/whole-status-$stamp.json" /api/v1/operations/delete-aifactory/status \
  --data-urlencode "folder=$folder" --data-urlencode "job_id=$job_id"
jq . "$review_dir/whole-status-$stamp.json"
```

Review `pipeline_runs`, `deletion_plan`, `reconciliation_required` and saved
completion records. If Azure completion was verified but local cleanup was
interrupted, this **separate** request asks for local reconciliation only:

```bash
read -r -p 'Retype the reviewed delete-factory job UUID for local cleanup: ' approved_job
[[ "$approved_job" == "$job_id" ]]
jq -n --arg folder "$folder" --arg job "$job_id" \
  '{contract_version:1, folder:$folder, job_id:$job}' > "$review_dir/reconcile-request.json"
post_json "$review_dir/reconcile-result.json" /api/v1/operations/delete-aifactory/reconcile "$review_dir/reconcile-request.json"
jq . "$review_dir/reconcile-result.json"
```

Reconciliation does not call Azure, restart pipelines or retry deletion;
missing verified records keep it blocked. General project/scale-set recovery
is **not implemented** here. Never clear locks or re-register as a shortcut.

## 6. Optional read-only checks and reports

Health/schema/sign-in checks do not establish deployment success.
These documented REST calls are **implemented**; there is no `/doctor`
endpoint (doctor is a CLI-side compatibility check).

```bash
get_json "$review_dir/health.json" /health
jq . "$review_dir/health.json"
get_json "$review_dir/schema.json" /api/v1/schema
jq . "$review_dir/schema.json"
get_json "$review_dir/openapi.json" /openapi.json
get_json "$review_dir/capabilities.json" /api/v1/creation/capabilities
jq . "$review_dir/capabilities.json"
read -r -p 'Exact scale-set UUID for an authorized Azure sign-in check: ' observed_scale
jq -n --arg folder "$folder" --arg factory "$factory_id" --arg scale "$observed_scale" \
  '{aifactory_folder:$folder, factory_id:$factory, scale_set_id:$scale}' > "$review_dir/auth-request.json"
post_json "$review_dir/auth-status.json" /api/v1/azure/auth/status "$review_dir/auth-request.json"
jq . "$review_dir/auth-status.json"
```

### GitHub Actions status and read-only event stream — not ADO

These calls do not start pipelines. Use the exact recorded repository/run;
for ADO use its provider results and the original catalog job.

```bash
read -r -p 'Exact GitHub OWNER/REPO recorded for this operation: ' repository
read -r -p 'Exact GitHub Actions numeric run ID: ' run_id
get_json "$review_dir/workflow-status.json" /api/v1/workflow-runs/status \
  --data-urlencode "repository=$repository" --data-urlencode "run_id=$run_id"
jq . "$review_dir/workflow-status.json"
call_api "$review_dir/workflow-events.sse" /api/v1/workflow-runs/events \
  --get --no-buffer --max-time 120 --header 'Accept: text/event-stream' \
  --data-urlencode "repository=$repository" --data-urlencode "run_id=$run_id" --data-urlencode 'follow=true'
cat "$review_dir/workflow-events.sse"
```

The events file contains **SSE, not JSON**. curl exit 28 means its observation
deadline expired; inspect the partial file and current status, not another
confirmation. Reconnect GETs with a returned `after` cursor to resume.
Reconnecting or closing a stream neither reruns nor cancels the workflow.

### Sample metrics, saved metrics and Azure billing

```bash
get_json "$review_dir/monitoring-catalog.json" /api/v1/monitoring/catalog
jq . "$review_dir/monitoring-catalog.json"
jq -n '{source:"sample", report_id:"showback"}' > "$review_dir/sample-report-request.json"
post_json "$review_dir/sample-report.json" /api/v1/monitoring/report "$review_dir/sample-report-request.json"
jq . "$review_dir/sample-report.json"
jq -n '{source:"sample"}' > "$review_dir/sample-summary-request.json"
post_json "$review_dir/sample-summary.json" /api/v1/monitoring/summary "$review_dir/sample-summary-request.json"
jq . "$review_dir/sample-summary.json"
jq -n '{source:"sample", report_id:"showback", format:"csv"}' > "$review_dir/export-request.json"
post_json "$review_dir/sample-showback.csv" /api/v1/monitoring/export "$review_dir/export-request.json"
jq -n --arg folder "$folder" --arg factory "$factory_id" \
  '{folder:$folder, factory_id:$factory}' > "$review_dir/saved-request.json"
post_json "$review_dir/saved-results.json" /api/v1/monitoring/evidence/read "$review_dir/saved-request.json"
jq . "$review_dir/saved-results.json"
jq -e '.contract == "aifactory.monitoring-evidence.v1"
  and .status == "available" and (.rows | type) == "array"
  and (.native_bindings | type) == "array"' "$review_dir/saved-results.json" >/dev/null
jq '{source:"live", rows:.rows, native_bindings:.native_bindings}' \
  "$review_dir/saved-results.json" > "$review_dir/saved-summary-request.json"
post_json "$review_dir/saved-summary.json" /api/v1/monitoring/summary "$review_dir/saved-summary-request.json"
jq . "$review_dir/saved-summary.json"
jq '. + {report_id:"showback"}' "$review_dir/saved-summary-request.json" > "$review_dir/saved-report-request.json"
post_json "$review_dir/saved-report.json" /api/v1/monitoring/report "$review_dir/saved-report-request.json"
jq . "$review_dir/saved-report.json"
```

`sample` uses demonstration data. Saved metrics do not collect/import data or
start jobs; projection runs only when saved results are `available`. Keep the
original envelope, warnings and source errors alongside reports.
`absent`, `incompatible` or `unavailable` is not zero cost or good health.
`live` here means supplied stored observations, not automatic Azure collection.

This last request performs an **Azure Cost Management read**. Use only an
explicitly permitted subscription; late/zero billing does not prove deletion.

```bash
read -r -p 'Exact authorized subscription UUID for billing reads: ' subscription_id
read -r -p 'Billing month YYYY-MM: ' month
jq -n --arg subscription "$subscription_id" --arg month "$month" --arg folder "$folder" \
  '{subscription_ids:[$subscription], month:$month, aifactory_folder:$folder}' > "$review_dir/cost-request.json"
post_json "$review_dir/resource-group-costs.json" /api/v1/monitoring/resource-group-costs "$review_dir/cost-request.json"
jq . "$review_dir/resource-group-costs.json"
```

<details markdown="1">
<summary>More info</summary>

### Scoped settings replacement alternative

For nonsecret catalog settings rather than ARM parameter unset/reset, begin
a new review with setup. Supply only intentional replacements; omitted keys
stay unchanged. This is configuration only, even when setting a service flag
false. It uses the normal catalog prepare/confirm routes above.

```bash
read -r -p 'Path to a reviewed nonsecret replacement-settings JSON object: ' settings_path
jq -e 'type == "object"' "$settings_path" >/dev/null
jq -n --arg folder "$folder" --arg factory "$factory_id" --arg revision "$revision" \
  --slurpfile settings "$settings_path" \
  '{contract_version:1, folder:$folder, factory_id:$factory, expected_revision:$revision,
    action:"configure-settings", settings:$settings[0]}' > "$request_path"
```

Continue with the separate prepare/review/confirm steps in this tab.
Routes without a friendly CLI/SDK wrapper are **generic-access only** in
those clients; the named removal wrappers already exist. REST always uses
the actual HTTP contracts, not CLI receipt formats.

</details>

</details>
<!-- /factory-tool -->

## Alternative and Legacy ways

Prefer manual configuration editing? Read
[file-first versus wrapper-first configuration](18-cli-and-api-and-usage.md#choose-how-to-author-configuration-file-first-or-wrapper-first).
Deleting a JSON key or setting a service flag false does not approve or perform
Azure deletion. Use the selected tab's reviewed flow for resource removal.

Legacy saved-creation removal and `/projects/delete` or `/scale-sets/delete`
routes are not substitutes for catalog runtime deletion. Legacy `submitted`
means the local script exited zero, **not** pipeline submission/success or
verified Azure deployment; `deployment_verified` remains false.

An expired **unused** review can be prepared again from fresh settings. An
uncertain **confirmed** operation must be inspected and resolved first.
Automatic flag-to-delete behavior, selective retention inside whole-factory
deleted groups, and generic force/retry/cancel-on-timeout recovery are
**not implemented**. Do not use legacy paths to bypass a blocker.

<details markdown="1">
<summary>More info</summary>

### Support labels and compatibility

* **implemented** — the command, SDK method or HTTP route exists.
* **generic-access only** — a documented API contract is accessible through
  generic requests but lacks a friendly wrapper; this does not describe the
  named project/scale-set/draft removal wrappers on this page.
* **conditional** — execution still needs the installed host/source/runtime
  capabilities, correct coordination, ownership, retention and permissions.
* **blocked** — a check failed or required proof is missing; stop and resolve it.
* **not implemented** — no supported feature is provided; do not infer a fallback.

This page was checked against accelerator client source at `300234cd`, including
the named wrappers introduced at `0da0d85b` and the environment-order review fix
at `2ae10aa9`. Environments can be requested in any order but must be unique;
both project deletion flags must be actual booleans.

The API baseline is `d52463f`. Its frozen accelerator pin
`3e9102ee07c959d91e5ac508432bd1545d258a15` is not changed by this guide and
does not provide the named ordered-pipeline runtime. Published source advertises
`factory_deletion_pipeline_coordination_modes: ["blob"]`; generic single-writer
whole-owned-group support is not this named contract or selective project
deletion. The API checks the selected immutable source and enrolled mode.
No client publication, optional preflight or offline test approves execution.

### Whole-factory plan and retention contract

`deletion_retention_policy` must equal `deletion_plan.retention_policy`:

| Field | Required value |
|---|---|
| `mode` | `preserve-reusable-infrastructure` |
| `required_execution_contract` | `ordered-project-pipelines-v1` |
| `execution_scope` | `whole-resource-groups` |
| `selective_retention_supported` | `false` |
| `limitations` | Nonempty server-provided limitations, reviewed verbatim |

All project stages must precede common stages; common stages depend on every
registered project placement. Each project stage explicitly sets
`enableDeleteForDisabledResources`, `deleteAllServicesForProject`,
`deleteKeyvaultAlso` and `deleteAllForProject` to boolean `true`.
The order is capability hosts, target-project Search shared private links,
service-managed lifecycle, project resources, then project network.
Pipeline success and verified absence of the exact resources are both required.
Configuration references alone do not establish actual inventory or preservation.

Draft guards also check protected parameter profiles, ownership, registered
pipeline connections, bootstrap references and projects shared across scale
sets. An optional `scale_set_id` on project resource deletion identifies an
existing placement; it does not replace or broaden the explicit environments.

### Source references

* [CLI commands](../../../environment_setup/azurefactory-cli/src/azurefactory/cli.py),
  [SDK client](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py),
  [request builders](../../../environment_setup/azurefactory-cli/src/azurefactory/catalog_requests.py),
  [receipt validation](../../../environment_setup/azurefactory-cli/src/azurefactory/review.py),
  [named deletion validation](../../../environment_setup/azurefactory-cli/src/azurefactory/factory_deletion.py).
* [Saved metrics adapter](../../../environment_setup/azurefactory-cli/src/azurefactory/monitoring_saved.py),
  [workflow observer](../../../environment_setup/azurefactory-cli/src/azurefactory/workflow_events.py),
  [named wrapper tests](../../../environment_setup/azurefactory-cli/tests/test_catalog_wrappers.py),
  [whole-factory tests](../../../environment_setup/azurefactory-cli/tests/test_factory_deletion.py).
* [API guide](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/docs/API.md),
  [OpenAPI](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/docs/openapi.json),
  [catalog contracts](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/factory_catalog_models.py),
  [parameter contracts](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_parameter_models.py),
  [project deletion](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_project_deletion.py),
  [named routes](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/factory_deletion.py),
  [ordered plan](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_factory_deletion.py).

Examples describe supported contracts, not a verified live deletion. No Azure
operation, pipeline start, installation, runtime/pin change or deletion was
performed to write this page.

</details>
