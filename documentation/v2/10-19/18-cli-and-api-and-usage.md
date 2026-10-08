# 18. Get started with the Factory CLI, Python SDK or REST API

[19: Add and update](19-cli-and-api-and-usage.md) |
[20: Remove and recover](20-cli-and-api-and-usage.md)

This guide starts with the **new registered Azure Factory** approach. Try the
connection examples below before creating or changing a factory.

## Choose the tool that suits you

All three tools use the same Factory service. You do not need to learn all three.

| If you want to... | Choose | What it means |
| --- | --- | --- |
| Type commands in a terminal | **CLI** | Ready-made commands, such as `azurefactory factory create`. Start here if you are unsure. |
| Write a Python script | **Python SDK** | Python helpers that send your requests to the Factory service. |
| Connect another application or language | **REST API** | Send requests directly to the Factory service using HTTP. The example uses `curl.exe`. |

## Common docs - What is needed for all

- An existing Factory API setup and matching CLI/SDK files. Ask your platform
  team for the folders if you have not installed them.
- Two PowerShell windows for this local tutorial.
- Approval before changing a real factory. **Saving settings and deploying
  resources are separate actions.**

### The five steps

| Step | Meaning | Remember |
| --- | --- | --- |
| Check / preflight | Validates your configuration and environment. | Resolve any reported problems first. |
| Prepare | Shows the changes for you to review. | No deployment yet. |
| Review and approve | Check the selected factory, environment and changes. | Approve only what you intend to do. |
| Confirm / start | For deployment, sends the approved configuration to the configured Azure DevOps (ADO) or GitHub Actions (GHA) pipeline and starts it. | A settings-only confirmation saves settings; it does not deploy. Starting a run does not mean it has finished. |
| Follow progress | Reads status and output from the current deployment run. | If a response is missing, check the run before trying again. |

## Tutorial: the same safe smoke test through all three approaches

A **smoke test** is a quick check that the tools can connect. This tutorial uses
an empty temporary folder. **It does not create Azure resources, deploy or delete.**

Open **two PowerShell windows**. Copy each setup block into the named window.
**Variables are not shared between windows**: complete the Window B setup even
if you already completed Window A.

### Window A: start the Factory service

Enter the full path to your prepared API folder when asked. It must already
contain `src\api.py` and its `.venv` Python environment.

```powershell
$ErrorActionPreference = 'Stop'
$ApiRoot = Read-Host 'Absolute path to the reviewed API source checkout'
$Python = Join-Path $ApiRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'The selected API checkout needs its existing .venv. Follow API setup first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ApiRoot 'src\api.py'))) {
    throw 'This is not the API source checkout.'
}
Set-Location -LiteralPath $ApiRoot
$env:AIFACTORY_API_KEY = 'local-parity-smoke-only'
& $Python -m uvicorn src.api:app --host 127.0.0.1 --port 8876
```

Leave this window running. The example key is **only for this local demo**.
Do not use it for a real factory. If port 8876 is already in use, ask the operator
for a free port and use it in both windows; do not stop someone else's service.

<details>
<summary>More info</summary>

The API is the local service that receives requests. This example deliberately
uses `http://127.0.0.1:8876`; `127.0.0.1` means your own computer. The usual
source API default is 8765, and a desktop application's port may be different.

A typical developer API folder is
`C:\code\code_py_25\008_aifactory_admin_ux_tkinter`. Use the actual prepared
folder provided by your operator, not a guessed path. The tutorial installs
nothing. See [setup instructions](17-cli-and-api-and-usage.md#install-and-connect-the-cli)
if the required environment is missing.

</details>

### Window B: set up the tools

Enter the **same API folder** as Window A, then the accelerator folder containing
the CLI and Python helpers. This block also creates the empty demo folder.

```powershell
$ErrorActionPreference = 'Stop'
$ApiRoot = Read-Host 'Absolute path to the API checkout used in Window A'
$AcceleratorRoot = Read-Host 'Absolute path to the reviewed accelerator checkout'
$Python = Join-Path $ApiRoot '.venv\Scripts\python.exe'
$SdkSource = Join-Path $AcceleratorRoot 'environment_setup\azurefactory-cli\src'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'API Python environment not found.'
}
if (-not (Test-Path -LiteralPath (Join-Path $SdkSource 'azurefactory\client.py'))) {
    throw 'SDK source not found in the selected accelerator checkout.'
}
$env:PYTHONPATH = $SdkSource
$env:AIFACTORY_API_URL = 'http://127.0.0.1:8876'
$env:AIFACTORY_API_KEY = 'local-parity-smoke-only'
$DemoRoot = Join-Path $env:TEMP ('factory-parity-smoke-' + [guid]::NewGuid())
$env:FACTORY_FOLDER = Join-Path $DemoRoot 'azurefactory'
New-Item -ItemType Directory -Path $env:FACTORY_FOLDER | Out-Null
Set-Location -LiteralPath $DemoRoot
Write-Host "Empty demo folder: $env:FACTORY_FOLDER"
```

Keep using **this Window B** for the following examples. You can choose one
approach or try all three: these examples only read information.

<details>
<summary>More info</summary>

A typical accelerator folder is
`C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml`.
`PYTHONPATH` selects its CLI/SDK source without another installation. Using
`& $Python -m azurefactory` means the `azurefactory` command does not need to be
installed separately on your command search path.

Both windows must use the same URL and key. The scripts work in PowerShell 5.1
or 7. REST examples need a `curl.exe` version supporting `--fail-with-body`.
The CLI/SDK requires Python 3.10+; the API uses its own prepared environment.

</details>

### Approach 1: terminal commands - CLI

Run in Window B:

```powershell
& $Python -m azurefactory health
if ($LASTEXITCODE -ne 0) { throw 'CLI could not reach the API.' }
& $Python -m azurefactory catalog list --folder $env:FACTORY_FOLDER
if ($LASTEXITCODE -ne 0) { throw 'Catalog read failed.' }
```

Expect a healthy service and an empty factory list. This is correct: you have
not created a factory yet.

### Approach 2: Python helpers - SDK

Paste the complete block into Window B:

```powershell
@'
import json
import os
from azurefactory import AzureFactoryClient

client = AzureFactoryClient()
print(json.dumps(client.health(), indent=2))
catalog = client.catalog_list(os.environ["FACTORY_FOLDER"])
print(json.dumps(catalog, indent=2))
'@ | & $Python -
if ($LASTEXITCODE -ne 0) { throw 'SDK smoke test failed.' }
```

This sends the same two requests using Python. You do not need to create a
separate Python file.

### Approach 3: direct requests - REST API

Run in Window B. Use `curl.exe` exactly as written:

```powershell
curl.exe --silent --show-error --fail-with-body `
    "$env:AIFACTORY_API_URL/health"
if ($LASTEXITCODE -ne 0) { throw 'REST health request failed.' }

curl.exe --silent --show-error --fail-with-body --get `
    "$env:AIFACTORY_API_URL/api/v1/factory-catalog" `
    --header "X-API-Key: $env:AIFACTORY_API_KEY" `
    --data-urlencode "folder=$env:FACTORY_FOLDER"
if ($LASTEXITCODE -ne 0) { throw 'REST catalog request failed.' }
```

All three approaches should show the same empty factory list.

### Finished

**No extra test step is required.** Stop the idle demo service with **Ctrl+C in
Window A** when you finish.

Next, use [guide 19 to add or update](19-cli-and-api-and-usage.md), or
[guide 20 to remove resources](20-cli-and-api-and-usage.md). For real work, use
the real factory's service address and private key, not the demo key or folder.
Do not stop a real running deployment's service as a way to cancel Azure work.

## First identify which variables.json you mean

For the default registered Azure Factory approach, use the supported commands
or requests to change settings. Let the service maintain these files:

| File / location | Ownership and editing rule |
| --- | --- |
| Registered `azurefactory\factories\<key>\scalesets\<suffix>\projects\projectNNN\variables.json` | A project settings file written by the service. Manual edits are not automatically loaded and can be overwritten. Change settings through the supported commands or requests. |
| Registered `azurefactory\register.json`, bindings, receipts and encrypted profiles | Files maintained by the service. Do not edit them to change factory identity, approve work or bypass an error. |

## If something goes wrong

| Message or symptom | What to do |
| --- | --- |
| `Set-Location` says the path is null | Run the complete setup block in that window. Variables do not carry over from another window. |
| `No module named azurefactory` | Check the accelerator folder entered in Window B, then rerun its setup. |
| Connection refused | Keep Window A running and check both windows use the same address and port. |
| 401 / wrong key | Use the key belonging to that service. |
| Blocked request or missing response | Read the message and check the run's status. Do not repeat a deployment or deletion blindly. |

## Optional reference

<details>
<summary>More info</summary>

### Compatibility and common requirements

An installed desktop/API can be older than the published code. An API key gives
access to that service; it does not replace Azure permissions or your approval
process. For a real operation, select the exact factory, project and environment.

Paths sent as `folder`, `aifactory_folder` or `repo_root` refer to the computer
running the API. Request JSON and client review files are local to the client.
Keep keys, requests, review files and output private and outside Git.

A settings-only confirmation normally returns `job:null`; it saved configuration,
not a deployment. A deployment confirmation returns a job to follow.
Requests from other computers may be restricted: do not expose the desktop API
publicly or put its key in browser JavaScript to work around that restriction.

Optional compatibility checks in the initialized Window B:

```powershell
& $Python -m azurefactory api instructions
& $Python -m azurefactory doctor
& $Python -m azurefactory schema --openapi
& $Python -m azurefactory bootstrap capabilities
```

`doctor` checks supported interfaces, not whether Azure deployment will succeed.
Interactive API help is at `http://127.0.0.1:8876/docs`; the machine-readable
description is at `http://127.0.0.1:8876/openapi.json`.

### Source versions

The original parity walkthrough used API source
`d52463fa6e1fd4371e38fdb9d0b4f9028f0cc17b` and accelerator source
`eb077742e230e1b5338767f2e3c942b2ed792e85`, or compatible later code.
These are source references, not instructions to change a deployment pin.
Do not pull, reset or change a submodule in a checkout containing other work
merely to run this tutorial. Use a reviewed compatible copy.

The accelerator provides shared source/templates. Registered configuration is
managed by the API; copying templates, changing a branch or saving a file does
not deploy a factory. A branch name alone does not identify the exact code used.

### Support labels

| Label | Meaning |
| --- | --- |
| **implemented** | Available in the reviewed code; check that your installed version supports it. |
| **generic-access only** | Available through a general request, without a dedicated shortcut command or method. |
| **conditional/blocked** | Needs supported versions, permissions, settings and successful checks before it can run. |
| **not implemented** | The complete requested behavior is not available. |

### Three-interface coverage

| Capability | REST | Python SDK | CLI | Important limit |
| --- | --- | --- | --- | --- |
| Health, schema, capabilities and selected-account checks | implemented | implemented | implemented | `doctor` is an extra CLI helper. |
| Create factory configuration | implemented | implemented: `factory_create_prepare` | implemented: `factory create` | Saves settings only. |
| Clone/add scale set/project/placement | implemented | generic-access only: `catalog_prepare` | implemented: named commands | Does not copy deployed resources or data. |
| Explicit `latest-successful` placement | implemented | implemented through catalog request/review | implemented | Requires successful recorded common deployment; not the default. |
| Read settings | implemented | implemented | implemented | Reading does not change anything. |
| Replace registered settings | implemented | generic-access only | generic-access only | Review and save separately from deployment. |
| Parameter get/prepare/confirm and override removal | implemented | implemented | implemented | Removing an override is not deleting a resource. |
| GitHub workflow status/watch | implemented | implemented | implemented | No equivalent ADO watcher is claimed. |
| Sample reports, saved results and costs | implemented | implemented | implemented | Saved results are not a new collection; real costs require Azure reads. |
| Deployment and registered bootstrap | conditional/blocked | conditional/blocked | conditional/blocked | The selected workflow and Azure setup must support the request. |
| Whole-factory deletion/status/recovery | conditional/blocked | conditional/blocked | conditional/blocked | Project teardown finishes before common infrastructure teardown. |
| Project/scale-set deletion and draft removal | conditional/blocked | generic-access only | generic-access only | Different deletion choices; see guide 20. |
| Captured Dev-to-Stage-to-Prod promotion | not implemented | not implemented | not implemented | Adding a placement and deploying it is different. |

### The eight scenarios

| Scenario | Support and limit | Guide |
| --- | --- | --- |
| A. New factory, hub/VPN, project001 and selected environments | **implemented** configuration; **conditional/blocked** deployment. Explicitly select environments and complete the network setup. | 19 |
| B. Add an AI Factory scale set | **implemented** configuration; **conditional/blocked** deployment. This is not an Azure VM Scale Set. | 19 |
| C. Choose latest successful eligible scale set | **implemented** when explicitly requested; default automatic selection is **not implemented**. | 19 |
| D. Promote a captured successful configuration/version through environments | **not implemented** as a complete operation. | 19 |
| E. Add/update/remove settings and resources | Settings changes are **implemented**; resource changes are **conditional/blocked**. A normal settings update does not provide general resource removal. | 19/20 |
| F. Choose APIM versus Kong | Unified three-tool selection is **not implemented**. Component setup has **conditional/blocked** support; Application Gateway is different. | 19 |
| G. Delete a project | **generic-access only** in SDK/CLI; **conditional/blocked** execution. Selected environments and retention choices matter. | 20 |
| H. Delete factory/projects while keeping hub/VPN/dependencies | **conditional/blocked**. Resources that must remain inside a group selected for deletion block that operation. | 20 |

### Optional developer regression tests

These are **not required to use the tools**. They check the three interfaces
together using simulated provider results and temporary data. They do not
contact Azure, deploy anything or require Window A's server.

In the initialized Window B, select the consumer 114 folder containing the test
script. Both source folders must contain the compatible code and existing test
dependencies. The script installs nothing:

```powershell
$ConsumerRoot = Read-Host 'Absolute path to the consumer 114 offline harness checkout'
$ParityRunner = Join-Path $ConsumerRoot 'test-parity.ps1'
if (-not (Test-Path -LiteralPath $ParityRunner -PathType Leaf)) {
    throw 'This checkout does not contain the offline parity harness.'
}
& $ParityRunner -ApiRoot $ApiRoot -AcceleratorRoot $AcceleratorRoot
if ($LASTEXITCODE -ne 0) { throw 'Offline parity tests failed; inspect the reported failures.' }
```

The original walkthrough reported `25 passed, 1 warning`. The
`StarletteDeprecationWarning` about `httpx` was not a test failure; no package
change is needed just to follow this guide. Counts can change as tests are added.
Consumer 114 is a test repository, not an Azure sandbox; 113 is not used.

### Command index

These are command names, not complete examples. Guides 19/20 provide the inputs.

| Intent | Commands | Guide |
| --- | --- | --- |
| Connect/check | `health`, `doctor`, `api instructions`, `schema`, `bootstrap capabilities`, `auth status` | 18/19 |
| Read settings | `catalog list`, `catalog settings`, `parameters get` | 19 |
| Create/register | `factory create/clone`, `scaleset add`, `project add/add-placements`, `catalog confirm` | 19 |
| Edit/deploy | `parameters prepare/confirm`, `runtime deploy/confirm` | 19 |
| Registered bootstrap | `bootstrap workflow prepare/start/status/next/continue`, `preflight` | 19 |
| Follow progress | `catalog jobs/job/logs/poll`, `runtime status/logs/poll`, `workflow status/watch` | 20 |
| Delete/recover | `delete-aifactory prepare/confirm/status/reconcile`, general catalog deletion requests | 20 |
| Monitor | `monitoring catalog/summary/report/export`, `monitoring saved read/summary/report`, `monitoring resource-group-costs` | 20 |

There is no dedicated CLI `catalog prepare`, `project promote`, `project delete`,
`scaleset delete` or general `resource delete` command in this baseline.
There are no `AzureFactoryClient.scaleset_add()` or `project_promote()` methods.
General request methods do not make an unsupported operation available.

### Implementation references

Use the selected service's OpenAPI and current source for exact field names:
[CLI/SDK reference](../../../environment_setup/azurefactory-cli/readme.md),
[API examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md),
[client methods](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py),
[review helpers](../../../environment_setup/azurefactory-cli/src/azurefactory/review.py),
[canonical API guide](https://github.com/jostrm/azure-aifactory-config/blob/main/docs/API.md)
and [offline tests](https://github.com/jostrm/azure-enterprise-scale-byor-114).

Source descriptions and architecture graphs are not live Azure results. The
four support labels describe reviewed code, not a guarantee that an installed
host supports every operation. Never bypass blocked checks or retry uncertain
writes automatically.

</details>

<details>
<summary>Alternative and Legacy ways</summary>

## Choose how to author configuration: file-first or wrapper-first

The default for a registered factory is **wrapper-first**: use the supported
commands or Python helpers and let the service save the settings. A wrapper is
simply a helper that builds a request for you.

Choose **file-first** only when you deliberately maintain a consumer-owned
configuration file used by a supported pipeline or older factory setup.
Both styles need a separate deployment review.

| Your preference | Route |
| --- | --- |
| Edit my `variables.json` and review the file changes myself | File-first for the exact supported consumer file; do not edit registered generated files as a substitute. |
| Let the tools handle settings | Wrapper-first through guide 19's commands, SDK helpers or REST requests. |
| Write JSON but keep a registered factory managed | Write a request or small patch JSON file and send it through prepare/confirm. |
| Use an existing desktop application | Use its supported setup and actual URL/key; this tutorial's demo address is not that application's address. |

### Files outside the default registered approach

| File / location | Ownership and editing rule |
| --- | --- |
| Accelerator `environment_setup\aifactory\variables.json` | Shared template/defaults, not the place for a consumer-specific change. Do not change pinned shared source to customize a project. |
| Legacy consumer `aifactory\variables.json`, or its selected persistent project JSON | File-first editing can apply. Confirm the exact file used by the loader/pipeline; a root default is not always the project input. |
| `.env`, ADO `variables.yaml` and GitHub Environment variables | Separate inputs with their own save/publish steps. Editing one does not automatically update the others. |

### File-first steps

1. Identify the exact project, environment and file used by the intended run.
2. Keep a private backup and review the changes. Preserve other settings, types
   and environment sections. Never put secrets into source-controlled JSON.
3. Check the JSON and the selected version's supported settings. Valid JSON alone
   does not prove a deployment is ready.
4. Follow the approved procedure to get the file to the intended pipeline.
   Saving locally does not publish GitHub variables, commit/push or run a pipeline.
5. Review and separately approve deployment, then follow its recorded results.

Do not replace an approved run's settings by editing another file. If settings
change after review, reload and review again. If a run has already started and
its outcome is unclear, inspect it before trying again.

### Legacy configuration and deployment

For an exact legacy JSON project, `config review` / `config save` and the SDK
`ConfigurationDraft` can help preserve the file's existing content. They are
not commands for registered catalog roots.

Older `legacy plan/prepare/start/list/status` and launcher
`bootstrap config/prepare/start/status` flows are described in guide 19. Do not
use them to bypass a blocked registered operation. Legacy `submitted` means the
local script finished with exit zero, not that Azure deployment succeeded.

### Advanced enrollment

`enrollment plan/ensure/prepare-binding/publish/plan-and-publish` is an advanced,
separate CLI flow. It is **implemented** with **conditional/blocked** execution:
`ensure` can create resources and grant roles. Equivalent REST enrollment and
`AzureFactoryClient.enrollment_ensure()` are **not implemented**.
Binding publication uses the API, but that does not make all enrollment actions
available through all three interfaces.

### Switching approaches

- After manually editing legacy JSON, reload the exact project before using
  wrappers; an older review is no longer valid.
- For a registered factory, send a supported settings/parameter request rather
  than hand-editing `register.json` or its project files.
- Importing a JSON file is not registering or deploying a factory. Migration is
  a separate reviewed action.
- Saving a snapshot does not necessarily update pipeline files or remote settings.

<details>
<summary>More info</summary>

There is no automatic two-way sync between arbitrary JSON edits and the registered
catalog. The API reads the register and writes the registered project files.
Manual edits to those files may be overwritten and do not change the catalog's
deployment input.

The legacy source-preserving path retains an opaque `_json_source` reference.
Do not edit or reconstruct it. Source changes after loading/reviewing require a
fresh load/review; do not repair hashes to replay an old save.

The pipeline reader `apply-json-config-overrides.py` starts from `dev`, overlays
`stage_prod` for a non-Dev target when present, then exact `test` for Stage or
`prod` for Prod when supplied. That rule is specific to that reader. Registered
project snapshots use `dev` and `stage_prod` with explicit placement checks;
do not copy a legacy environment layout into them.

General configuration actions include `migrate`, `configure-settings`,
`configure-binding` and `correct-draft-scale-identity`. Their requirements are
described in guide 19. A general CLI POST's `--write --yes` acknowledges that
request, not permission to perform a later deployment.

References:
[legacy JSON editing](../../../environment_setup/azurefactory-cli/readme.md#edit-a-legacy-json-projects-configuration-without-deployment),
[pipeline JSON reader](../../../environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py),
[catalog storage](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/factory_catalog.py),
[registered project settings](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_project_configuration.py).

</details>

</details>
