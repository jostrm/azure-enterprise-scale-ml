# 18. Choose CLI, Python SDK or REST: routing and common setup

[Existing guide 17](17-cli-and-api-and-usage.md) |
[19: Add and modify](19-cli-and-api-and-usage.md) |
[20: Remove and recover](20-cli-and-api-and-usage.md)

This guide is the starting point for three alternative clients of the same
Factory backend. It supplements guide 17 without changing it. Examples and
implementation labels were reviewed on **2026-10-08**. They describe source
contracts, not proof of an installed version or a deployed Azure environment.

## Choose the operation first, then the interface

Imagine that you need another project in an existing factory. First decide
whether you need to **register a project**, **change its configuration**, or
**deploy its resources**. Those are different operations, regardless of whether
you type a CLI command or call the API from Python.

Next choose the interface that fits your work:

| Your situation | Choose | Why |
| --- | --- | --- |
| You operate from a terminal, write an operator script, or integrate a reviewed step into CI | **Existing `azurefactory` CLI** | Named commands, readable previews, saved review receipts, explicit confirmation and exit codes. |
| You build a Python backend, notebook or automation service | **`azurefactory.AzureFactoryClient` Python SDK** | Standard-library HTTP client plus review helpers; avoids writing transport plumbing. Your application still owns authorization and human approval. |
| You use another language, `curl.exe`, or a language-neutral integration platform | **HTTP REST API** | The canonical wire contract; you supply headers, JSON, review storage and observation logic. |
| You need a desktop UI | Existing Tkinter or MAUI host | Tkinter owns the canonical Python backend; MAUI packages that backend, rather than providing another provisioning engine. |

These choices do not change which operation is safe or supported. A blocked CLI
operation must not be retried through REST as a bypass. A portal calls the API
from a trusted backend/worker, **not browser JavaScript containing the API key**.
Catalog routes also enforce local-host boundaries; configuring HTTPS does not
turn the desktop API into a public multi-tenant control plane.

### Keep the five steps distinct

| Step | Meaning | Does not mean |
| --- | --- | --- |
| Inspect / preflight | Read scope, contracts and available evidence | Permission to mutate; preflight may make authenticated read-only provider calls. |
| Prepare | Build an expiring review; may save local review state | Deployment has started. |
| Review and approve | A person or approved application policy authorizes the exact scope/effects | A checksum or `can_execute:true` is itself approval. |
| Confirm / start | Consume the reviewed authorization | Azure necessarily completed successfully. |
| Observe / reconcile | Read the exact operation and its evidence | Timeout cancels it, or uncertainty permits an automatic retry. |

Configuration confirmation normally returns `job:null`. That means configuration
was saved, not deployed. Runtime confirmation returns a job to observe.
Legacy `submitted` means **the local script exited zero**; even `--wait` and CLI
exit zero do not make `deployment_verified` true.

## Implementation labels used throughout these guides

| Label | Meaning |
| --- | --- |
| **implemented** | The described interface/behavior exists in the reviewed source. Read the stated scope; this is not a live deployment certification. |
| **generic-access only** | The operation is reachable through generic catalog or HTTP methods, but lacks a dedicated friendly wrapper in that client. |
| **conditional/blocked** | A contract or workflow exists, but capability, source, identity, evidence, coordination or runtime limitations can prevent execution. |
| **not implemented** | The requested end-to-end behavior or dedicated surface does not exist; no pretend command is provided. |

Labels describe both interface convenience and execution support. For example,
project deletion has a host contract, generic client access and conditional
execution. These are compatible statements, not interchangeable claims.

### Three-interface coverage

| Capability | REST | Python SDK | CLI | Execution boundary |
| --- | --- | --- | --- | --- |
| Health, schema/OpenAPI, capabilities, scoped auth inspection | implemented | implemented | implemented | `doctor` and `api instructions` are CLI conveniences, not separate provisioning APIs. |
| Create factory configuration | implemented | implemented: `factory_create_prepare` | implemented: `factory create` | Configuration only; confirmation is separate. |
| Clone, add scale set, add project/placements | implemented: catalog actions | generic-access only: `catalog_prepare` | implemented: named commands | No resource/data clone; no deployment from registration. |
| Explicit `latest-successful` project placement | implemented | implemented through catalog request/review | implemented via project placement option | Requires qualifying recorded evidence; **not** the default. |
| Read scoped settings | implemented | implemented: `catalog_settings` | implemented: `catalog settings` | Read only. |
| Replace scoped settings, migrate configuration, correct an eligible draft identity | implemented: catalog actions | generic-access only | generic-access only: `request` | Reviewed local changes, not infrastructure execution. |
| Parameter get/prepare/confirm; override unset/profile reset | implemented | implemented | implemented | Configuration changes; resource removal is separate. |
| Runtime prepare/confirm/status/logs | conditional/blocked | conditional/blocked | conditional/blocked | Requires compatible source, bindings and reviewed exact scope. CLI supplies polling conveniences. |
| Registered bootstrap/preflight/staged or bounded approval | conditional/blocked | conditional/blocked | conditional/blocked | A supported workflow is not proof every hub/network combination works. |
| Legacy configuration and deployment | implemented | implemented | implemented | Legacy roots only; deployment remains conditional and local completion is not Azure success. |
| Named whole-factory deletion/status/reconcile | conditional/blocked | conditional/blocked; named methods | conditional/blocked; named commands | Ordered pipeline and retention requirements must actually be executable. |
| Project/scale-set deletion; draft removal | conditional/blocked | generic-access only | generic-access only | Exact catalog action, modern schema where required, separate review. |
| GitHub workflow status/watch | implemented | implemented | implemented | GitHub only; no equivalent ADO status/watch surface is claimed. |
| Sample/supplied-evidence and saved-evidence monitoring | implemented | implemented | implemented | Sample is synthetic; saved evidence is not a new collection. |
| Resource-group costs | implemented | implemented | implemented | Authenticated read-only Azure billing query, not an offline sample. |
| Advanced enrollment plan/ensure | not implemented as an equivalent REST enrollment contract | not implemented as an `AzureFactoryClient` enrollment method | implemented local enrollment core; conditional execution | `ensure` can provision Azure/provider resources. Binding publication separately uses the API. |
| Captured-source configuration/version promotion | not implemented | not implemented | not implemented | Placement plus target deployment is not this operation. |

`AzureFactoryClient.request(...)` is generic HTTP transport. It does not create
a missing REST operation. Likewise, `azurefactory request` does not invent a
supported execution capability.

### The eight end-to-end scenarios

| Scenario | Label and current boundary | Tutorial |
| --- | --- | --- |
| A. New factory, own hub/VPN, project001, selected Dev/Stage/Prod | **implemented** configuration; **conditional/blocked** deployment. Select every environment explicitly. Integrated-hub ownership/retention and workflow-stage limitations must be resolved, not hidden. | Guide 19 |
| B. Add an AI Factory scale set | **implemented** configuration; **conditional/blocked** deployment. This is not an Azure VM Scale Set. | Guide 19 |
| C. Add project using latest successful eligible scale set | **implemented** explicit opt-in. Selection **by default** is **not implemented**. | Guide 19 |
| D. Promote Dev to Stage to Prod with captured source config/version | **not implemented** as the captured-state operation. Explicit target placements and deployment are available but different. | Guide 19 |
| E. Add/update/remove configuration and resources | **implemented** configuration/parameter editing; resource effects are **conditional/blocked**. Generic removal reconciliation from ordinary updates is **not implemented**. | Guides 19 and 20 |
| F. Select APIM versus Kong | **conditional/blocked** component configuration/deployment; unified first-class selection/deployment parity is **not implemented**. The later MCP/AI Gateway pipeline integration does not establish full three-client gateway-choice parity. Application Gateway is distinct. | Guide 19 |
| G. Delete a project | **generic-access only** SDK/CLI; **conditional/blocked** execution. Requires exact environments, independent retention options and compatible runtime; selective single-writer deletion is unsupported. | Guide 20 |
| H. Delete factory/projects while preserving hub/VPN/dependencies | **conditional/blocked**. Ordered project teardown precedes common teardown; retained infrastructure inside whole-group deletion targets blocks execution. | Guide 20 |

## Common docs - What is needed for all

| Requirement | Practical rule |
| --- | --- |
| An available compatible API | CLI and SDK do not replace the API host. An installed desktop sidecar may lag published source. |
| Correct URL and API key | Obtain them from the authorized operator. Source default is loopback port 8765; MAUI ports are dynamic. This isolated tutorial deliberately uses 8876. |
| Correct host-local paths | `folder`, `aifactory_folder`, `repo_root` and API file paths are on the **API host**, not uploads from your client. CLI `--request-json` and client receipt files are client-local. |
| Exact identity | Discover and explicitly choose factory, scale-set and project UUIDs. A suffix such as `001` and a project number such as `002` are not UUIDs. |
| Two distinct kinds of authentication | API-key authentication is separate from the host's Azure/GHA/ADO identity, permissions, coordination and human approval. |
| Suitable local tools | PowerShell 5.1 or 7; `curl.exe` with `--fail-with-body` support for REST examples; a supported Python environment. CLI/SDK require Python 3.10+ with no third-party runtime dependencies; the API has its own dependencies. |
| Private review storage | Keep requests, receipts, terminal output and configuration outside replaceable template directories and out of Git. Do not log secrets. |
| Review before execution | Scope/revision/hash/expiry must match. Confirmation is single-use. A timeout is not permission to repeat it. |

### Source, installation and consumer ownership

The accelerator supplies shared source and templates. A consumer may reference
it as a submodule and own copied configuration/pipeline files. A submodule URL
or branch name is not an immutable source commit.

Legacy `aifactory` configuration and registered `azurefactory/register.json`
are different layouts. The register is API-managed mutable configuration, not a
deployment receipt. Changing source version does not migrate layouts.
`variables.json`, ADO `variables.yaml`, local `.env`, and provider variables
have entry-point-specific import/export rules; they are not universally
interchangeable. Do not edit generated projections to bypass catalog ownership.

Use [guide 17's installation/distribution instructions](17-cli-and-api-and-usage.md#install-and-connect-the-cli)
if you do not already have the CLI package or API environment. The walkthrough
below deliberately reuses existing environments; it installs nothing.

For a known published parity baseline, use API source
`d52463fa6e1fd4371e38fdb9d0b4f9028f0cc17b` or compatible later code and accelerator
source `eb077742e230e1b5338767f2e3c942b2ed792e85` or compatible later code.
These are source references, **not instructions to update a deployment pin**.
Do not `git pull`, reset or change a submodule merely to run this tutorial in a
dirty/concurrently edited checkout. Select a reviewed clean checkout instead.

## Choose how to author configuration: file-first or wrapper-first

This is a second decision, separate from choosing CLI, Python or HTTP. You can
prefer writing configuration yourself, or prefer having the supported backend
operations manage it. **Both paths still require a separate reviewed deployment.**

| Your preference | Choose this working style | Start here |
| --- | --- | --- |
| "I want to edit my `variables.json`, inspect the Git diff and control every field." | **File-first**, for the exact consumer-owned configuration file that your supported legacy/pipeline route actually reads. You own field names, types, environment sections and review of the effective result. | File-first steps below; then the applicable legacy/configuration route in guide 19. |
| "I want commands or Python methods to do as much of the work as possible." | **Wrapper-first**, especially for registered factories. Use named CLI commands, supported SDK helpers, and shared API prepare/confirm operations rather than hand-editing catalog storage. | Guide 19 for adding/updating; guide 20 for removal. |
| "I prefer authoring JSON, but this is a registered factory." | Write a **request/patch JSON file** for a supported API operation. Let the backend persist the resulting registered configuration. | Guide 19's typed parameter or generic scoped-settings workflow. |
| "I want a non-Python application to manage configuration." | Use the same managed operations through REST. The backend supplies orchestration; your application supplies authentication, exact scope and approval handling. | Guide 19's REST preparation and confirmation alternatives. |

For example, changing a service setting can mean either editing a legacy
pipeline's selected `variables.json`, or preparing a scoped parameter/settings
patch against a registered project. The resulting JSON may look similar, but the
source-of-truth and persistence contracts are different. Do not mix the two paths
on the assumption that a file watcher will synchronize them.

### First identify which variables.json you mean

| File / location | Ownership and editing rule |
| --- | --- |
| Accelerator `environment_setup\aifactory\variables.json` inside the source checkout/submodule | Upstream template/default input. Do not use edits here as a shortcut for customer configuration or change a pinned source merely to set a project value. |
| A legacy consumer's `aifactory\variables.json`, or the exact persistent project JSON selected by its existing loader/pipeline | The **file-first** route can apply here. Confirm the actual selected file and environment; root defaults and project-specific files are not interchangeable. |
| Registered `azurefactory\factories\<key>\scalesets\<suffix>\projects\projectNNN\variables.json` | API-written project projection. The registered catalog remains authoritative; hand edits are not automatically imported into it and may be overwritten when that project is saved. Use reviewed settings/parameter operations for managed changes. |
| Registered `azurefactory\register.json`, bindings, receipts and encrypted profiles | Backend-managed identity/configuration/authorization state. Do not hand-edit these to change identity, repair a blocked operation, or make file edits appear approved. |
| Local `.env`, ADO `variables.yaml`, GitHub Environment variables and reviewed runtime JSON | Distinct inputs/exports with route-specific mappings. Editing one does not automatically synchronize the others or change an already frozen execution request. |

There is **not implemented** automatic two-way synchronization between arbitrary
`variables.json` edits and the registered catalog. Generic JSON import is not
catalog registration, placement creation or deployment authorization. In
particular, editing the registered project's exported file does not override the
catalog's deployment input.

### File-first: edit the consumer-owned JSON yourself

**Label: implemented for supported consumer JSON input routes; conditional/blocked
for actual deployment.** This is not a recommendation to edit generated catalog
projections.

1. Identify the exact consumer, selected project, environment and JSON path used
   by the intended loader/pipeline. If an execution uses a reviewed/frozen
   configuration file, changing some other root file will not change that run.
2. Keep a private backup or an appropriate reviewed Git diff of the nonsecret
   configuration. Edit only intended values with a JSON-aware editor; preserve
   unknown keys, value types, identity and other environment sections. Never add
   credentials, tokens or private keys to source-controlled JSON.
3. Validate JSON syntax, then validate against the **selected source version's**
   schema and effective environment. Syntax alone does not establish supported
   flags, identity consistency, network capacity or Azure readiness.
4. Follow the existing route's explicit synchronization/publication procedure:
   for example, the approved legacy GHA or ADO pipeline must receive the reviewed
   file and the correct provider variables. Do not run a template copier that
   replaces your edits, assume `.env` is already published to GitHub, or silently
   change a source pin. Commit/push/dispatch, if needed, are distinct approved steps.
5. Prepare and review the actual operation before starting it, then observe its
   exact job/receipts. Saving JSON does not add, update or remove Azure resources.

**Environment example, not a universal precedence rule:** the accelerator's
`apply-json-config-overrides.py` pipeline reader starts with `dev`, overlays
`stage_prod` for a non-Dev target when present, then overlays exact `test` for
Stage or `prod` for Prod when supplied. This can make a Dev baseline change
effective in other environments unless overridden. Its allowed sections are
not the same as registered project snapshots, which use `dev` and `stage_prod`
with exact placement checks. Do not copy a legacy `test`/`prod` section into a
registered snapshot or invent a new `stage` JSON section because the public
environment name is `stage`.

You can combine manual editing with the **legacy** source-preserving wrappers:
reload the exact persistent project after the edit, then use `config review`
and a separately approved `config save`, or the SDK's `ConfigurationDraft`.
These are not catalog-root commands. They preserve the opaque `_json_source`
reference and check its source fingerprint. An edit made **after** a load/review
invalidates that review: reload and review again instead of repairing a checksum
or replaying an old save. Inline JSON content is not a substitute for the
persistent source-bound load when preservation is required.

### Wrapper-first: use the managed operations as much as possible

**Label: implemented where a wrapper exists; generic-access only where it does
not.** You still choose the target, values and approvals, but you do not maintain
register/projection/receipt internals by hand.

| Intent | Prefer these supported wrappers / contracts |
| --- | --- |
| New factory configuration | CLI `factory create`; SDK `factory_create_prepare`; REST catalog action `create-factory`. |
| Clone, add scale set, add project or placement | Named CLI commands; SDK `catalog_prepare` / `review_catalog_prepare`; REST equivalent catalog actions. Dedicated SDK methods do not exist for every CLI verb. |
| Change a resource parameter | CLI `parameters get`, `prepare`, `confirm`; SDK `catalog_parameters`, `parameter_prepare`, `parameter_confirm`; corresponding REST parameter routes. Discover the published fields before patching. |
| Change an editable registered setting | `catalog settings` / `catalog_settings` reads the scope; generic `configure-settings` preparation and catalog confirmation perform the write. No invented `settings set` wrapper. |
| Edit a legacy JSON project without reconstructing full state | CLI `config review` / `config save`; SDK `ConfigurationDraft.load/review/save`. Keep the underlying import/validation/export/save contract if implementing raw REST yourself. |
| Apply configuration to Azure | A new runtime or bootstrap review and separate confirmation/start. Configuration confirmation does not implicitly call this step. |
| Remove something | Choose override removal, draft removal, selective resource deletion or whole-factory deletion explicitly in guide 20. No wrapper equates a disabled flag with approved deletion. |

Here, "wrapper" means an existing client/helper that constructs or validates
requests around the shared backend. It is **not** a promise of a one-command
deploy/promote/delete flow. `AzureFactoryClient` is a transport-oriented SDK;
its raw methods do not obtain consent for you. REST clients use the same
orchestration but own their review UI/storage. Advanced CLI enrollment is a
separate local-core exception, not equivalent REST/SDK provisioning.

You may still hand-author a small `changes.json`, parameter-patch file or full
request JSON in this style. Those files are **requests**, not edits to
`register.json` or an execution receipt. Use the supported field names from
`schema`, `catalog settings`, or `parameters get`; do not paste an entire
pipeline `variables.json` into a scalar settings patch.

### Switching styles without losing changes

- **Manual legacy JSON to wrappers:** finish the edit, reload the exact project,
  preserve its opaque origin, review and save through the source-aware legacy
  contract. Migration to a registered root is a separate explicit operation.
- **Wrappers to a manual legacy pipeline:** inspect the actual exported path and
  format, and decide which consumer file the pipeline will use. A saved snapshot
  alone is not proof that pipeline variable files or remote provider variables
  were updated.
- **Manual preference in a registered factory:** author the supported request
  JSON and use the managed prepare/confirm path. Do not hand-edit a project
  projection or register and expect an automatic merge.
- **Any change after preparation:** invalidate the old review and obtain a fresh
  one where appropriate. For an already-confirmed operation with an uncertain
  outcome, observe/reconcile first; never use a manual edit to force a retry.

Source evidence: the
[pipeline JSON reader](../../../environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py),
[legacy source-preserving client contract](../../../environment_setup/azurefactory-cli/readme.md#edit-a-legacy-json-projects-configuration-without-deployment),
[catalog loading and projection writer](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/factory_catalog.py),
and [registered project snapshot/identity checks](https://github.com/jostrm/azure-aifactory-config/blob/d52463f/src/catalog_project_configuration.py).
The examples in guides 19/20 implement the wrapper-first path; this section
explains when the file-first path is a valid alternative rather than a bypass.

## Tutorial: the same safe smoke test through all three approaches

**Label: implemented.** This creates an empty temporary directory, starts a
loopback development API, and reads health/catalog information. It does not
create a factory, authenticate to Azure, enroll a provider, deploy or delete.

Use **two PowerShell windows**. Variables and environment variables are
process-local: **Window B does not inherit anything you typed in Window A**.
Copy each setup block into its indicated window. Do not execute `$Pub` or any
other variable from an earlier chat unless you have defined it in that window.

### Window A: start the development API

When prompted, enter the absolute path of your reviewed API source checkout,
which must already contain `src\api.py` and a working `.venv`.
The ordinary development checkout is often
`C:\code\code_py_25\008_aifactory_admin_ux_tkinter`; an approved clean worktree is
also suitable if it has access to the existing environment.

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

Leave Window A running. The displayed key is intentionally a public
**development-only example**, not a production secret. Use it only for this
empty demonstration. Use approved secret handling and the actual owning
host/key for real factories. Do not reuse this server/key for privileged work.
If port 8876 is occupied, stop and choose another free port in **both** windows;
do not terminate an unrelated server.

### Window B: initialize the client environment

Enter the same API source root as Window A, then the reviewed accelerator root
containing `environment_setup\azurefactory-cli\src\azurefactory`.
The ordinary accelerator checkout is often
`C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml`; again, use a
reviewed compatible source rather than assuming a dirty local branch is current.

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

This block is complete: it does not depend on variables from Window A or a
previous PowerShell session. The same URL/key must be used on both sides.
`PYTHONPATH` selects the reviewed SDK source without installing a different
package. The CLI invocation below does not require `azurefactory.exe` on PATH.

### Approach 1: CLI

Run in Window B:

```powershell
& $Python -m azurefactory health
if ($LASTEXITCODE -ne 0) { throw 'CLI could not reach the API.' }
& $Python -m azurefactory catalog list --folder $env:FACTORY_FOLDER
if ($LASTEXITCODE -ne 0) { throw 'Catalog read failed.' }
```

Expected: a healthy API and an empty catalog. Reading an empty `azurefactory`
directory does not provision anything or establish a real factory.

Optional local contract discovery:

```powershell
& $Python -m azurefactory api instructions
& $Python -m azurefactory doctor
& $Python -m azurefactory schema --openapi
& $Python -m azurefactory bootstrap capabilities
```

`doctor` is a compatibility aid, not a deployment readiness guarantee.
Unsupported schema/capability messages are meaningful; do not install or upgrade
anything automatically to hide them.

### Approach 2: supported Python SDK

Paste this complete PowerShell block into the same Window B. It executes Python
from standard input; no `.py` file or second package installation is needed.

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

The client reads `AIFACTORY_API_URL` and `AIFACTORY_API_KEY` from this process.
It is an HTTP SDK, not an in-process replacement for the API backend.

### Approach 3: HTTP REST using curl.exe

Run in Window B. Use `curl.exe`, not PowerShell's possible `curl` alias:

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

All three approaches should describe the same empty catalog. On a compatible
host the capabilities include `latest-successful-placement-v1`. That advertises
an interface; it does not mean the empty folder has an eligible successful scale.
Swagger is at `http://127.0.0.1:8876/docs`; OpenAPI at
`http://127.0.0.1:8876/openapi.json`.

### Stop here for a first-time smoke test

You have now used the CLI, SDK and REST API. **No additional step is required.**
Stop the demonstration API with **Ctrl+C in Window A** when finished.
That instruction applies to this idle demo host, not to cancelling a real
in-flight deployment. Do not stop an operational host to try to cancel Azure work.

For a real scenario, open guide 19 or 20, select the real owning API/key and
registered folder, and follow its separate approval gates. Do not substitute a
random real subscription into the smoke test.

## Optional: developer regression tests

This section is **not needed for normal CLI, SDK or REST usage**. Its purpose is
to detect cross-interface regressions using actual route/model/client code with
simulated provider evidence and temporary state.

It does **not** contact Azure, dispatch pipelines or need Window A's server.
It imports both explicitly selected source checkouts and uses an in-process
ASGI-to-urllib adapter. It is not a standalone production SDK example.

In Window B, choose the offline consumer 114 checkout containing `test-parity.ps1`.
Use the already-selected API/accelerator sources; no dependency installation
is performed by this runner:

```powershell
$ConsumerRoot = Read-Host 'Absolute path to the consumer 114 offline harness checkout'
$ParityRunner = Join-Path $ConsumerRoot 'test-parity.ps1'
if (-not (Test-Path -LiteralPath $ParityRunner -PathType Leaf)) {
    throw 'This checkout does not contain the offline parity harness.'
}
& $ParityRunner -ApiRoot $ApiRoot -AcceleratorRoot $AcceleratorRoot
if ($LASTEXITCODE -ne 0) { throw 'Offline parity tests failed; inspect the reported failures.' }
```

The baseline walkthrough returned `25 passed, 1 warning`; future test counts can
change. The observed `StarletteDeprecationWarning` about `httpx` was a dependency
deprecation, not a test failure. It does not require the tutorial user to install
`httpx2` or modify the API environment.

Consumer 114 is an integration repository, **not an Azure sandbox**. Consumer
113 is not used by this tutorial or harness.

## Command routing index

This table is an index of **command names**, not standalone executable examples.
The linked tutorials supply required inputs and complete invocations.

| Intent | CLI entry points | Guide |
| --- | --- | --- |
| Connect/discover | `health`, `doctor`, `api instructions`, `schema`, `schema --openapi`, `bootstrap capabilities`, `auth status` | 18; scoped auth in 19 |
| Inspect saved scope | `catalog list`, `catalog settings`, `parameters get` | 19 |
| Create/register | `factory create`, `factory clone`, `scaleset add`, `project add`, `project add-placements`, `catalog confirm` | 19 |
| Edit | `parameters prepare/confirm`, `config review/save` | 19; unset/reset in 20 |
| Deploy | `runtime deploy/confirm`, `legacy plan/prepare/start` | 19 |
| Bootstrap | `bootstrap config/prepare/start/status`; `bootstrap workflow prepare/start/status/next/continue`; `preflight` | 19 |
| Enroll | `enrollment plan/ensure/prepare-binding/publish/plan-and-publish` | 19 |
| Observe | `catalog jobs/job/logs/poll`, `runtime status/logs/poll`, `legacy list/status`, `workflow status/watch` | 20 |
| Delete/reconcile | `delete-aifactory prepare/confirm/status/reconcile`; generic catalog deletion actions | 20 |
| Monitor | `monitoring catalog/summary/report/export`, `monitoring saved read/summary/report`, `monitoring resource-group-costs` | 20 |
| Advanced existing API action | `request`; SDK `catalog_prepare` or `request` | 19 and 20 |

There is no dedicated CLI `catalog prepare`, `project promote`, `project delete`,
`scaleset delete` or generic `resource delete` command in this baseline.
There are no supported SDK methods named `scaleset_add()`, `project_promote()` or
`enrollment_ensure()` on `AzureFactoryClient`.
Existing generic catalog actions include `migrate`, `configure-settings`,
`configure-binding`, `correct-draft-scale-identity`, and the guarded deletion
actions. See guide 20 for why generic POST acknowledgement is not deployment
approval.

## Troubleshooting and safety

| Symptom | Meaning / action |
| --- | --- |
| `Set-Location` says the path is null | Run the entire setup block in that window. Variables do not cross PowerShell windows. |
| `No module named azurefactory` | Check this window's `$env:PYTHONPATH`, selected checkout and `$Python`. Do not assume a console executable on PATH. |
| Connection refused on 8876 | Check Window A is still running and both windows use the same port. |
| 401 or authentication failure | Use the key belonging to that API host; API credentials do not grant Azure privileges. |
| 403/local-host rejection | Respect the API's local-host boundary; do not change binding/proxy settings as a workaround. |
| 409 or `can_execute:false` | Inspect blockers, identity, revision, evidence and capability. Do not bypass through another client. |
| Unsupported request/schema | Installed host may lag the source. Arrange an intentional compatible upgrade, not a silent pin change. |
| Empty `resolved_placements` / no eligible success | Empty or draft-only catalogs have no qualifying historical deployment proof. |
| Confirmation response lost / timeout | Retain exact IDs and inspect status/evidence; do not re-confirm, re-dispatch or infer cancellation. |

For an automatic placement, review `resolved_placements`, including the exact
UUID and recorded common-deployment evidence. Confirmation revalidates that
evidence without choosing a different target. A setting, graph snapshot,
inventory cache, latest suffix or local script exit is not a substitute.

## Evidence and maintenance

The source-backed routing contract is documented in the
[CLI/SDK reference](../../../environment_setup/azurefactory-cli/readme.md),
[API usage examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md),
and [registered-layout helper installer](../../../bootstrap/lib/registered_setup.py).
Local architecture notes and bounded graph results guided source inspection;
unpublished local notes are not required to follow these guides.
Dynamic/unresolved graph edges do not prove independence, and a proposed
architecture decision is not an accepted deployment mandate.

Authoritative implementation entry points:

- [CLI parser and handlers](../../../environment_setup/azurefactory-cli/src/azurefactory/cli.py),
  [SDK](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py),
  [review validation](../../../environment_setup/azurefactory-cli/src/azurefactory/review.py).
- [CLI/SDK reference](../../../environment_setup/azurefactory-cli/readme.md),
  [API examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md).
- [Canonical API guide](https://github.com/jostrm/azure-aifactory-config/blob/main/docs/API.md)
  and the selected host's `/openapi.json`.
- [Offline consumer 114 harness](https://github.com/jostrm/azure-enterprise-scale-byor-114).

No example in these guides grants permission to alter source pins, deploy,
delete, publish Git changes or bypass an organization's approval policy.
