# Update a v1.24 factory/project: Bash, Python, REST and CLI

[Back to How to UPDATE AI Factory](26-update-AIFactory.md)

## The scenario

Update the accelerator source/templates of an **existing legacy AI Factory** and
create/update its current **Project001, Dev** through Azure DevOps. The existing
common factory, service connections and pipeline definition are prerequisites.
This is not a new-factory bootstrap, a folder migration or a request to redeploy
every common resource.

All examples are anonymized:

| Setting | Example |
|---|---|
| Consumer repository folder | `C:\code\customers\example\AIFactory` |
| Direct Bash consumer branch | `prj001` |
| API-reviewed consumer branch | Published `main`; see the API route's restrictions |
| Current project | `"001"` |
| Azure environment | `dev` |
| Accelerator version | `124`, selecting `release/v1.24` |
| Provider | `ado` |

**Choose the route, not four consecutive deployments.**

| Route | Configuration | Local API required? | Review/run boundary |
|---|---|---:|---|
| [A. Direct Bash](#a-file-first-edit-configuration-then-one-bash-command) | Active YAML or JSON file | No | Launcher merge review, commit/push confirmation, then pipeline |
| [B. Python SDK](#b-factory-api-through-the-python-sdk) | Reviewed legacy API request | Yes | Plan/prepare, approved start, observe |
| [C. REST](#c-factory-api-through-rest-and-curlexe) | Same reviewed API request | Yes | The same server endpoints and approval boundaries |
| [D. CLI](#d-factory-api-through-the-cli) | Client of that same API | Yes | The same review/confirmation sequence |

The API-backed routes pursue the same update objective but are **not an HTTP
alias for every interactive Bash option**. In particular, an arbitrary
`ADO_BRANCH=prj001` direct update is not the reviewed API's published-main route.
Do not invent a missing branch argument or remove a confirmation to make the
examples look identical.

## A. File-first: edit configuration, then one Bash command

### Step 1: edit the file that will actually be used

For YAML, edit:

```text
aifactory\esml-infra\azure-devops\bicep\yaml\variables\variables.yaml
```

For JSON, edit `aifactory\variables.json`. Preserve the selected factory's naming,
tenant, subscription and service-connection values; ensure the current project is
`project_number_000: "001"` (YAML) or `"project_number_000": "001"` (JSON).
Check deletion flags and prerequisites before deployment. Never place credential
values in a configuration file intended for Git.

### Step 2: run the matching command from the consumer root

**Git Bash; YAML remains authoritative:**

```bash
AIFACTORY_USE_JSON_OVERRIDE=no ADO_BRANCH=prj001 bash ./ADO-update-aifactory-and-run-project.sh --aifactory-version 124
```

**Git Bash; JSON is the deployment override:**

```bash
AIFACTORY_USE_JSON_OVERRIDE=yes ADO_BRANCH=prj001 bash ./ADO-update-aifactory-and-run-project.sh --aifactory-version 124
```

`ADO_BRANCH` chooses the **consumer** branch, not the accelerator version or Azure
project number. Without it, the legacy ADO updater defaults to `main`, even when
the current checkout is `prj001`. The branch must exist locally and remotely.
These inline environment assignments affect only this command; no separate
`export` is needed.

> **YAML + `no`; JSON + `yes`.** The current maintained ADO launcher can initialize
> a missing JSON file from active YAML before tenant lookup. It does not replace
> an existing JSON file. If both files exist, editing YAML and selecting JSON does
> not synchronize the YAML changes into JSON. Older installed launchers may not
> have the missing-JSON initialization fix.

`AIFACTORY_USE_JSON_OVERRIDE` skips only the JSON-choice prompt, not authentication,
version/destination questions, review, commit approval or provider approvals.
Neither the Config Wizard UI nor the local API/SDK/CLI is needed for this route.

### What that one command does

1. Resolves the selected accelerator release to an exact source commit and
   protects existing local work/configuration.
2. Refreshes the submodule and copied ADO templates, retaining the active
   configuration's existing values and adding missing template defaults.
3. Reports newly added/removed settings. The merge is deterministic Python code:
   **GitHub Copilot is not invoked or required**.
4. Validates the ADO pipeline and, when tracked changes need publication, asks
   **Commit and continue? [y/N]**. Declining stops before push/dispatch and leaves
   local changes for review. With no tracked changes, that prompt may be skipped.
5. After approval, commits/pushes the refreshed consumer files, validates the
   published pipeline and queues the current project's Dev deployment. This
   normal ADO route skips Stage and Prod and monitors the returned run.

The terminal's variable report is **not a complete Git diff**. Review the full
diff in VS Code or with `git diff`/`git diff --cached` before answering Yes.
The legacy launcher stages broadly; do not approve unrelated edits or secrets
merely because they were already present.

This refreshes accelerator code/templates and deploys the project against its
existing common factory. A change to common factory resources requires its
appropriate common deployment; the project update is not a whole-factory
infrastructure upgrade guarantee.

### GitHub Actions is a separate provider route

Use the GitHub provider launcher/workflows for a GitHub consumer. Do not pass
`ADO_BRANCH` to select its workflow branch or assume the v1.24 GitHub launcher
supports the ADO version flags. The release's legacy GitHub helper targets
consumer `main`, uses release-specific runner defaults and must receive the
correct `AIFACTORY_REPO_ROOT`; inspect those settings before execution.

See the [GitHub workflow input guide](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/readme.md#manual-inputs-and-subnet-authentication).
Both copied workflow files and their pinned source must be updated together.

## API-backed routes: the same objective with explicit reviewed operations

The next routes use a **compatible current Factory API and its current clients**
to target legacy version `124`. They do not imply that an old v1.24 checkout
contains a current API server, Python SDK or CLI package. The API host's Azure,
Git and provider identities remain separate from the client's API key.

### The equivalence and its limits

| Choice | Direct Bash | Reviewed API/SDK/REST/CLI |
|---|---|---|
| Consumer branch | `ADO_BRANCH=prj001` supported by the legacy ADO updater | Current reviewed helper requires published consumer `main` |
| Source/template refresh | Normal update; omit `--project-only` | **`patch: true` / `--patch`** in plan and prepare |
| Source version | `--aifactory-version 124` | `aifactory_version: "124"` / the same CLI flag |
| Configuration input | YAML or JSON selection | Existing canonical legacy configuration recognized by the API host |
| Current project/environment | Selected configuration and normal Dev route | Explicit project001 and Dev-to-Dev `operation: update` |
| Approval | Interactive launcher commit/run gate | Executable prepare preview, then separately approved start; host/provider approvals can remain |

`patch: false` / `--no-patch` means **project-only, retaining installed code**.
It is not the equivalent of refreshing accelerator source/templates.
`operation: update` means the same source and target environment; `deploy` is
the legacy promotion operation. Neither flag silently migrates a catalog root.

The API's `folder` is the exact **legacy `aifactory` directory on the API host**:
`C:\code\customers\example\AIFactory\aifactory`, not the parent Git root and not
an `azurefactory` register. The saved configuration selects provider/scale-set
identity; do not add invented `orchestrator`, `ADO_BRANCH` or `scale_set_id`
fields to the legacy deployment request.

For these routes, prepare/review valid legacy JSON configuration first. They
are not the Bash YAML-only opt-out. Keep the configured ADO provider identity,
origin and installed reviewed templates compatible with the API/helper. A
custom URL accepted by the interactive Bash prompt does not establish that a
reviewed provider route accepts the same origin format.

### Shared setup for B, C and D

1. Install an approved **current** Factory API host. On Windows, download the
   [packaged configuration wizard](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/install_config_wizard/readme.md#windows),
   extract the entire archive and keep `_internal` beside the executable. Open
   **Quick setup > Start API host**, supply a private key, and copy the actual URL.
   Keep the host open. This uses the wizard only to host the API, not to edit the
   project configuration. A packaged MAUI sidecar is another operator-managed host.
2. Obtain a compatible current tools checkout separately from the v1.24 consumer
   pin. The examples below call it `C:\code\tools\azure-enterprise-scale-ml`.
   An old v1.24 submodule need not contain the SDK/CLI.
3. For Python/CLI, install the current client package and select the authorized
   API. **PowerShell 7.3+**, in a client terminal:

```powershell
$Tools = 'C:\code\tools\azure-enterprise-scale-ml'
python -m venv C:\code\tools\aifactory-client-env
& C:\code\tools\aifactory-client-env\Scripts\Activate.ps1
python -m pip install -e "$Tools\environment_setup\azurefactory-cli"
if ($LASTEXITCODE -ne 0) { throw 'Client installation failed.' }

$env:AIFACTORY_API_URL = Read-Host 'Actual URL displayed by the approved API host'
$env:AIFACTORY_API_KEY = Read-Host 'Same private key as the API host' -MaskInput
azurefactory health
if ($LASTEXITCODE -ne 0) { throw 'API unavailable; stop.' }
azurefactory doctor
if ($LASTEXITCODE -ne 0) { throw 'API/client contract mismatch; stop.' }
```

The default source port `8765` is only an example, not discovery of a running
host. Do not connect to an unrelated process that happens to use that port.
Plain HTTP is allowed only on loopback; use approved HTTPS for a remote host.
Never put the key in JSON, a script, Git or a receipt.

The canonical backend source is maintained outside this accelerator checkout.
The packaged-host installation above is documented; this guide does not invent
a `pip install` server package or assume an arbitrary `uvicorn` entry point.
An authorized backend-source installation has its own prerequisites and
`python -m src.api` instructions in that repository.

**Before using any route**, require the live host to expose the legacy
`project-deployments` plan/prepare/start/terminal endpoints and acknowledgement
`deployment_contract.version: 2`, including the selected patch/version/source
bindings. Stop on incompatibility or blockers. Client code and this guide are
not evidence that an installed host can execute the request.

For raw REST without installing the CLI, set the same two environment variables,
GET `/health` and `/openapi.json`, and inspect that legacy contract yourself.
The SDK/CLI's contract checks are safer than manually chaining HTTP requests.

### Configuration before deployment

All three API-backed examples below assume the intended Project001 configuration
is already saved on the host. Editing configuration and deploying it are separate:

- Direct file editing is sufficient for the legacy workflow; no configuration
  API call is mandatory.
- If configuration itself must be API-driven, use the current
  [legacy JSON configuration flow](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/azurefactory-cli/readme.md#edit-a-legacy-json-projects-configuration-without-deployment):
  load the exact project, preserve its full state, validate/export for review,
  then separately approve save. `ConfigurationDraft` is the Python convenience
  helper. Those save operations do not deploy Azure.
- Do not send an inline replacement JSON/YAML payload to a legacy deployment
  endpoint that accepts only folder/project selectors.

## B. Factory API through the Python SDK

### Step 1: save this example as update_legacy.py outside generated templates

Use the client environment from shared setup. The SDK supplies HTTP transport
and preview validation; the script checks exact scope/source and asks for approval.
It does not use a made-up `write_ack_version` request field: contract version 2
is returned by the host and checked before starting.

```python
import json
import re

from azurefactory import (
    AzureFactoryClient, load_receipt, validate_preview, write_receipt,
)

client = AzureFactoryClient()  # Uses AIFACTORY_API_URL and AIFACTORY_API_KEY.
request = {
    "folder": r"C:\code\customers\example\AIFactory\aifactory",
    "project_number": "001",
    "source_environment": "dev",
    "target_environment": "dev",
    "operation": "update",
    "patch": True,
    "aifactory_version": "124",
}


def check_draft(draft):
    for name in (
        "project_number", "source_environment", "target_environment",
        "operation", "patch", "aifactory_version",
    ):
        if draft.get(name) != request[name]:
            raise ValueError(f"Draft changed requested {name}; stop.")
    contract = draft["deployment_contract"]
    if (type(contract.get("version")) is not int or contract["version"] != 2
            or not draft.get("id") or contract.get("draft_id") != draft["id"]
            or type(draft.get("patch")) is not bool):
        raise ValueError("Legacy acknowledgement version/draft mismatch.")
    for name in (
        "operation", "patch", "aifactory_version", "requested_version",
        "branch", "resolved_ref",
    ):
        if contract.get(name) != draft.get(name):
            raise ValueError(f"Source/operation binding changed: {name}")
    if (contract.get("patch") is not True
            or contract.get("branch") != "release/v1.24"
            or not re.fullmatch(r"[0-9a-f]{40}", contract.get("resolved_ref", ""))):
        raise ValueError("Expected a pinned v1.24 source refresh.")


def saved_draft(draft_id):
    matches = [
        item for item in client.project_deployments(request["folder"])["drafts"]
        if item["id"] == draft_id
    ]
    if len(matches) != 1:
        raise ValueError("Exact saved draft not found.")
    return matches[0]


plan = client.project_deployment_plan(request)  # Creates a local draft, not Azure.
check_draft(plan)
prepare_request = {
    "folder": request["folder"],
    "draft_id": plan["id"],
    "patch": True,
    "aifactory_version": "124",
}
preview = client.project_deployment_prepare(prepare_request)
validate_preview(preview)  # Requires can_execute, no blockers, ID and valid expiry.
current = saved_draft(plan["id"])
check_draft(current)
if not (preview["deployment_contract"] == current["deployment_contract"]
        == plan["deployment_contract"]):
    raise ValueError("Source changed during preparation; obtain a new review.")

receipt_path = "legacy-v124.python.receipt.json"
receipt = write_receipt(
    receipt_path, client=client, purpose="legacy-start",
    operation="legacy-project-deployment", request_body=prepare_request,
    preview=preview, contract=preview["deployment_contract"],
)
print(json.dumps(receipt["preview"], indent=2))  # Sanitized review; not raw config.
if input("After review, type UPDATE 001 DEV to start: ") != "UPDATE 001 DEV":
    raise SystemExit("Not approved; no deployment started.")

approved = load_receipt(receipt_path, client=client, purpose="legacy-start")
latest = saved_draft(plan["id"])
check_draft(latest)
if latest["deployment_contract"] != approved["contract"]:
    raise ValueError("Saved source/operation changed after review; stop.")
started = client.project_deployment_start(
    approved["folder"], approved["confirmation_id"],
)
if started["deployment_contract"] != approved["contract"]:
    raise ValueError("Unexpected start reply; inspect the host, do not retry.")
print(json.dumps({
    "job_id": started["job_id"],
    "status": started["status"],
    "execution_result": started["execution_result"],
}, indent=2))
```

### Step 2: run and review

```powershell
python .\update_legacy.py
```

The first call saves a **local draft**; prepare produces the executable preview.
Review the exact folder/project/environment, release commit, effects, warnings,
expiry and blockers. Only the explicit text approval calls `/start`.
The receipt filename is exclusive: an existing file causes a stop, not an
overwritten approval. Keep it private and outside Git.

The Python receipt is for this script; use route D's CLI-generated receipt for
`azurefactory legacy start`. The CLI additionally binds saved draft metadata.
After a start or lost reply, do not rerun the entire script just to check progress.
Observe the returned job instead, for example:

```python
status = client.project_deployment_terminal(request["folder"], started["job_id"])
print(status["status"], status["execution_result"])
```

## C. Factory API through REST and curl.exe

Use PowerShell 7 and the authorized API environment variables from shared setup.
Raw REST does not add the SDK's receipt guards for you; retain and review the
responses. Files below contain selectors and previews, never API keys.

### Step 1: create a draft with the explicit source-update choice

Save `legacy.plan.request.json`:

```json
{
  "folder": "C:\\code\\customers\\example\\AIFactory\\aifactory",
  "project_number": "001",
  "source_environment": "dev",
  "target_environment": "dev",
  "operation": "update",
  "patch": true,
  "aifactory_version": "124"
}
```

```powershell
$Api = $env:AIFACTORY_API_URL.TrimEnd('/')
if (-not $env:AIFACTORY_API_KEY) { throw 'API key missing.' }
curl.exe --fail-with-body --silent --show-error --max-time 30 `
  --request POST "$Api/api/v1/operations/project-deployments/plan" `
  --header "X-API-Key: $env:AIFACTORY_API_KEY" `
  --header 'Content-Type: application/json' `
  --data-binary '@legacy.plan.request.json' --output .\legacy.plan.response.json
if ($LASTEXITCODE -ne 0) { throw 'Plan failed/uncertain; inspect state before retry.' }
$plan = Get-Content .\legacy.plan.response.json -Raw | ConvertFrom-Json
$plan | ConvertTo-Json -Depth 30
if ($plan.project_number -cne '001' -or $plan.source_environment -cne 'dev' `
    -or $plan.target_environment -cne 'dev' -or $plan.operation -cne 'update' `
    -or $plan.patch -isnot [bool] -or $plan.patch -ne $true `
    -or $plan.aifactory_version -cne '124' -or -not $plan.id `
    -or $plan.deployment_contract.version -ne 2 `
    -or $plan.deployment_contract.draft_id -cne $plan.id `
    -or $plan.deployment_contract.branch -cne 'release/v1.24' `
    -or $plan.deployment_contract.resolved_ref -cnotmatch '^[0-9a-f]{40}$') {
  throw 'Plan did not acknowledge the exact v1.24 Project001 Dev update.'
}
foreach ($field in @('operation','patch','aifactory_version','requested_version',
                     'branch','resolved_ref')) {
  if ($plan.deployment_contract.$field -cne $plan.$field) {
    throw "Plan source/operation acknowledgement mismatch: $field"
  }
}
```

Require the requested Project001/Dev-to-Dev `update`, boolean `patch:true`,
version `124`, and `deployment_contract.version:2`. Its `draft_id` must equal
the returned **`id`**; its branch must be `release/v1.24` with an exact source
commit. Plan does not return the start approval; prepare does.
Do not proceed if any request/contract field was ignored or changed.

### Step 2: prepare that exact draft

```powershell
$prepareRequest = @{
  folder = 'C:\code\customers\example\AIFactory\aifactory'
  draft_id = $plan.id
  patch = $true
  aifactory_version = '124'
}
$prepareRequest | ConvertTo-Json | Set-Content .\legacy.prepare.request.json -Encoding utf8
curl.exe --fail-with-body --silent --show-error --max-time 30 `
  --request POST "$Api/api/v1/operations/project-deployments/prepare" `
  --header "X-API-Key: $env:AIFACTORY_API_KEY" `
  --header 'Content-Type: application/json' `
  --data-binary '@legacy.prepare.request.json' --output .\legacy.prepare.response.json
if ($LASTEXITCODE -ne 0) { throw 'Prepare failed/uncertain; inspect state before retry.' }
$preview = Get-Content .\legacy.prepare.response.json -Raw | ConvertFrom-Json
$preview | ConvertTo-Json -Depth 30
```

**Stop for review.** Require `can_execute:true`, an empty blockers list, an
unexpired `expires_at`, `confirmation_id` and the same deployment contract.
Preparation can inspect/validate repository/provider prerequisites; it does not
authorize Git publication or cloud deployment. Resolve blockers rather than
switching to another route to bypass them.

### Step 3: only after approval, start once

```powershell
if ($preview.can_execute -ne $true -or @($preview.blockers).Count -ne 0 `
    -or -not $preview.confirmation_id `
    -or [DateTimeOffset]::Parse($preview.expires_at) -le [DateTimeOffset]::UtcNow) {
  throw 'Preview is blocked, invalid or expired.'
}
foreach ($field in @('version','draft_id','operation','patch','aifactory_version',
                     'requested_version','branch','resolved_ref')) {
  if ($preview.deployment_contract.$field -cne $plan.deployment_contract.$field) {
    throw "Changed acknowledgement field: $field"
  }
}
if ((Read-Host 'After reviewing all effects, type UPDATE 001 DEV') -cne 'UPDATE 001 DEV') {
  throw 'Not approved; no start request sent.'
}
@{
  folder = $prepareRequest.folder
  confirmation_id = $preview.confirmation_id
} | ConvertTo-Json | Set-Content .\legacy.start.request.json -Encoding utf8
curl.exe --fail-with-body --silent --show-error --max-time 30 `
  --request POST "$Api/api/v1/operations/project-deployments/start" `
  --header "X-API-Key: $env:AIFACTORY_API_KEY" `
  --header 'Content-Type: application/json' `
  --data-binary '@legacy.start.request.json' --output .\legacy.start.response.json
if ($LASTEXITCODE -ne 0) { throw 'Start failed/uncertain; do not repeat. Inspect the saved job.' }
$started = Get-Content .\legacy.start.response.json -Raw | ConvertFrom-Json
$started | ConvertTo-Json -Depth 30
```

The start body is **only `folder` and `confirmation_id`**; do not invent an
`acknowledgement`, patch or version field for `/start`. The server-held preview
binds those choices. Use unique files for a fresh review, and never replay an
uncertain start as an automatic retry.

### Step 4: observe, without starting again

```powershell
curl.exe --fail-with-body --silent --show-error --max-time 30 --get `
  "$Api/api/v1/operations/project-deployments/terminal" `
  --header "X-API-Key: $env:AIFACTORY_API_KEY" `
  --data-urlencode "folder=$($prepareRequest.folder)" `
  --data-urlencode "job_id=$($started.job_id)" --data-urlencode 'cursor=0'
if ($LASTEXITCODE -ne 0) { throw 'Status read failed; do not submit another start.' }
```

For incremental terminal reads, use returned `next_cursor` and honor `reset`;
do not treat log count as a cursor. Avoid displaying raw terminal output in
shared logs: it may contain private configuration/provider details.

## D. Factory API through the CLI

Use the installed current client and API settings from shared setup. These are
PowerShell commands; the CLI wraps the same plan/prepare/start API methods.

### Step 1: plan the legacy Project001 Dev update

```powershell
$Folder = 'C:\code\customers\example\AIFactory\aifactory'
$planText = azurefactory legacy plan --folder $Folder --project-number 001 `
  --source-env dev --target-env dev --operation update --patch --aifactory-version 124
if ($LASTEXITCODE -ne 0) { throw 'Plan blocked/failed; stop.' }
$plan = ($planText -join "`n") | ConvertFrom-Json
$plan | ConvertTo-Json -Depth 30
```

Plan saves a local draft. Note **`$plan.id`**, not an invented plan
`confirmation_id`. The CLI validates the returned scope and acknowledgement.

### Step 2: prepare and review a CLI receipt

```powershell
azurefactory legacy prepare --folder $Folder --draft-id $plan.id `
  --patch --aifactory-version 124 --save-receipt .\legacy-v124.cli.receipt.json
if ($LASTEXITCODE -ne 0) { throw 'Prepare blocked/failed; do not start.' }
```

Review the complete preview/receipt, exact target, `patch:true`, selected release
and source commit, effects, warnings, expiry and blockers. No deployment has
started. Existing receipt files are not overwritten.

### Step 3: in a separate invocation after approval

```powershell
azurefactory legacy start --receipt .\legacy-v124.cli.receipt.json --yes `
  --wait --poll-timeout 1800
if ($LASTEXITCODE -ne 0) { throw 'Start/wait failed or timed out; inspect state, do not restart.' }
```

`--yes` is the explicit approval for this exact saved receipt, not a reason to
skip reading it. The CLI reloads the saved draft and checks receipt/source/
environment bindings before start. `--wait` observes the **local script** only.

To observe later without resubmitting, use the returned job ID:

```powershell
$JobId = Read-Host 'Exact job_id returned by start'
azurefactory legacy status --folder $Folder --job-id $JobId --wait --poll-timeout 1800
```

## What counts as done?

| Boundary | What it proves |
|---|---|
| Configuration saved | Local project configuration persisted, not deployment |
| Plan | Local draft with exact project/environment/version choice |
| Executable prepare | Reviewed operation is eligible now; no cloud-success guarantee |
| Start | Local execution/job accepted; Git/provider/Azure effects may follow |
| Legacy `submitted`, exit code 0 or `--wait` completion | Local launcher boundary, **not verified Azure deployment success** |
| Correct provider run and Azure observations | Separate evidence needed before reporting the project deployed |

Timeouts do not cancel the host job or authorize a duplicate start. Stop and
reconcile uncertain/failed operations. The API-backed route may still invoke
the host's launcher, authentication and commit/publish controls; it is not an
unattended-approval bypass.

## Source and version references

- [Legacy plan/prepare/start and patch semantics](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/install_config_wizard/api-usage-examples/readme.md#4-legacy-project-update-and-promotion)
- [Current CLI/SDK legacy commands and completion boundaries](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/azurefactory-cli/readme.md#legacy-project-deployment)
- [SDK HTTP methods](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/azurefactory-cli/src/azurefactory/client.py)
- [CLI argument and receipt enforcement](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/azurefactory-cli/src/azurefactory/cli.py)
- [Packaged API installation and startup](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/install_config_wizard/readme.md#windows-cli-tutorial-start-the-packaged-api)

These instructions are grounded in current source/client contracts, not a live
test of an installed API or a deployment. Match the tools to your authorized
host's capabilities and pin reviewed executable source; do not assume all
historical releases or future versions implement this exact flow.
