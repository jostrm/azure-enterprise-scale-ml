# Enterprise Scale AI Factory: API integration examples

Build your own central-cloud-team UX against the configuration wizard API, not
against Tkinter widgets, MAUI views, generated configuration files or shell
launchers. These examples and the [Azure Factory CLI / Python SDK](../../azurefactory-cli/readme.md)
use the same HTTP API.

## Quickstart: CONFIGURE one factory and default project locally

**Use the existing `azurefactory` CLI; no new CLI is needed.** Choose the CLI
path **or** the direct API path below, not both against the same factory identity.
Both prepare one AI factory in your chosen region, one DEV/001 scale set and
default **project001**. A separately approved confirm saves local configuration
drafts. Neither path deploys Azure resources, creates a subscription, publishes
Git, enrolls a provider or changes the host's current Azure account.

| Boundary | Existing CLI commands | Result |
|---|---|---|
| **CONFIGURE (local)** | `factory create`, review, `catalog confirm --yes` | Saves factory/scale/project **drafts**, no Azure provision |
| **DEPLOY (cloud, explicit)** | Separate `runtime deploy` preview, review, `runtime confirm --yes` | May provision/change Azure resources and execute provider workflows |

This quickstart stops at **CONFIGURE**. An existing `DRAFT` factory is already
registered: `factory create` is not an idempotent "open existing" command.
Do not create the same key/prefix/region again, reset/delete its register, or
re-add its default project to obtain a demo.

### 1. Connect and supply the target

The approved API must already be running. From this repository's root, install
the existing stdlib-only package into your chosen Python 3.10+ environment:

```powershell
python -m pip install -e .\environment_setup\azurefactory-cli
if ($LASTEXITCODE -ne 0) { throw 'CLI installation failed.' }
Set-Location .\environment_setup\install_config_wizard\api-usage-examples
$env:AIFACTORY_API_URL = Read-Host 'Authorized API URL (for example http://127.0.0.1:8765)'
# Supply AIFACTORY_API_KEY privately through your approved secret mechanism.
$env:FACTORY_FOLDER = Read-Host 'Fresh isolated API-host demo root ending in azurefactory'
$env:FACTORY_KEY = Read-Host 'New readable factory key'
$env:FACTORY_PREFIX = Read-Host 'Approved factory prefix'
$env:FACTORY_REGION = Read-Host 'Azure region name'
$env:DEV_SUBSCRIPTION_ID = Read-Host 'Target DEV subscription UUID'
$env:TENANT_ID = Read-Host 'Target tenant UUID'
$env:DEV_VNET_CIDR = Read-Host 'Approved non-overlapping DEV VNet CIDR'
$env:ORCHESTRATOR = Read-Host 'Provider: ado or gha'
$env:AIFACTORY_VERSION = 'main' # Or an explicitly approved registered version 125+.
New-Item -ItemType Directory -Force .local | Out-Null
azurefactory health
if ($LASTEXITCODE -ne 0) { throw 'API host is unavailable.' }
azurefactory doctor
if ($LASTEXITCODE -ne 0) { throw 'API compatibility check failed; do not prepare.' }
$beforeText = azurefactory catalog list --folder $env:FACTORY_FOLDER
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the selected demo catalog.' }
$before = ($beforeText -join "`n") | ConvertFrom-Json
if ($before.contract_version -ne 1 -or $before.mode -ne 'catalog' -or @($before.factories).Count -ne 0) {
  throw 'Use a fresh isolated azurefactory root; do not recreate an occupied factory.'
}
```

For this demo, `FACTORY_FOLDER` must exist **on the API host** and be a fresh
isolated, empty `azurefactory` root, never the actual consumer's register or a
legacy `aifactory` root. Ask the host operator to create that separate empty
directory; do not copy `register.json`, saved factories, bindings or credentials
from the actual register. An empty existing directory is sufficient; there is
no extra CLI initialization command. The clients cannot upload a folder.
The read-only catalog check above must show `mode:"catalog"` and zero factories.
If a selected register already contains the requested key or prefix/region,
treat it as a conflict and select a new isolated demo root/identity; do not retry
creation against the occupied identity. To inspect the actual existing draft
instead, use `catalog list` and the exact-selection inspector, without a create.
Isolation protects local catalog state; it is **not** an Azure sandbox and does
not authorize deployment to the supplied subscription.
CIDR capacity is three projects in this tutorial so later scenarios can
add 002 and 003. The API validates region/network constraints. Do not treat
default settings or a successful `doctor` as evidence of deployment readiness.

### 2A. Prepare through the existing CLI

```powershell
azurefactory factory create --folder $env:FACTORY_FOLDER --factory-key $env:FACTORY_KEY `
  --prefix $env:FACTORY_PREFIX --region $env:FACTORY_REGION --kind ai `
  --environment dev --suffix 001 --subscription-id $env:DEV_SUBSCRIPTION_ID `
  --tenant-id $env:TENANT_ID --orchestrator $env:ORCHESTRATOR `
  --vnet-cidr $env:DEV_VNET_CIDR --max-projects 3 --aifactory-version $env:AIFACTORY_VERSION `
  --save-receipt .local\factory.cli.receipt.json
if ($LASTEXITCODE -ne 0) { throw 'Stop: inspect blockers/errors; do not confirm.' }
```

Omitting `--project-number`, `--initial-project-json` and `--common-only` delegates
default project001 to the API. Do **not** immediately run `project add --number
001`. Review the complete printed preview and receipt: requested region, prefix,
tenant/subscription, DEV/001, one project001 with the matching scale UUID,
effects, warnings, source revision, blockers, expiry and `operation_mode`.

**Stop for a human approval of that exact configuration-only preview.** Only in
a separate invocation after approval:

```powershell
azurefactory catalog confirm --receipt .local\factory.cli.receipt.json --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect host state before any retry.' }
python .\python\inspect_factory.py --folder $env:FACTORY_FOLDER `
  --factory-key $env:FACTORY_KEY --environment dev --suffix 001 --project-number 001
if ($LASTEXITCODE -ne 0) { throw 'Saved scope could not be verified; do not create it again.' }
```

### 2B. Alternatively, prepare through the direct API example

`python\create_factory.py` is a narrow tutorial adapter over the **existing**
`AzureFactoryClient` and review-receipt helpers, not another HTTP client or CLI
product. It uses the same template as section 1's raw Node/PowerShell calls:

```powershell
python .\python\render_request.py .\requests\01-create-factory.json --out .local\factory.api.request.json
if ($LASTEXITCODE -ne 0) { throw 'Request rendering failed.' }
python .\python\create_factory.py --request .local\factory.api.request.json `
  --receipt .local\factory.api.receipt.json
if ($LASTEXITCODE -ne 0) { throw 'Stop: inspect the blocked preview or error; do not confirm.' }
```

It calls POST `/api/v1/factory-catalog/prepare` (`CatalogPrepare`), requires
contract 1 and `operation_mode:"configuration"`, checks requested identity and
one DEV/001/default-project001 placement, then writes a CLI-compatible receipt
exclusively. It shows the complete nonsecret request/preview, and refuses
runtime actions, project overrides, expired/blocked previews and existing
receipt files. It does not confirm automatically.

**Stop for the same human review.** Only after explicit approval:

```powershell
python .\python\create_factory.py --confirm --receipt .local\factory.api.receipt.json --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect host state before any retry.' }
```

Confirmation calls POST `/api/v1/factory-catalog/confirm` (`CatalogConfirm`):
`{folder,contract_version:1,confirmation_id}`. Expect
`{contract_version:1,catalog:<CatalogSummary>,job:null}`, **not** a job ID.
The example then GETs `/api/v1/factory-catalog?folder=...`, verifies the exact
reviewed factory/scale/project UUIDs and placement, and prints
`phase:"configuration-saved"`. Configuration confirmation is synchronous; an
unexpected runtime job is an error, never permission to poll/deploy.

The receipt binds the request, preview, API URL, operation and expiry. It is not
a signed approval or per-user authorization; your service must enforce that.
Lost replies, conflicts and malformed results are never automatically retried.
Use new request/receipt filenames for a new review, not an overwritten approval.

### 2C. Copy the Python SDK starter to your consumer repo root

Use an **already registered/bootstrap-configured consumer repo** with its initialized
`azure-enterprise-scale-ml` submodule; this does not bootstrap or enroll providers.
Obtain **approved updated starter and submodule support assets** first; the new
starter folder may not yet exist in public clones. The commands below assume an
approved updated checkout. If supplied in a tutorial bundle, copy the same two
starter files from its `bootstrap\python-sdk` folder instead.
From the consumer root, copy **only these two files**. All support code stays in the
submodule, located relative to the copied script, not the working directory:

```powershell
Copy-Item .\azure-enterprise-scale-ml\bootstrap\python-sdk\aifactory_sdk.py .
Copy-Item .\azure-enterprise-scale-ml\bootstrap\python-sdk\aifactory.request.example.json .\aifactory.request.json
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\azure-enterprise-scale-ml\environment_setup\azurefactory-cli
if ($LASTEXITCODE -ne 0) { throw 'SDK installation failed.' }
.\.venv\Scripts\python.exe .\aifactory_sdk.py --help
```

Edit **every `[replace-…]` placeholder** in the renamed `aifactory.request.json`: an
absolute Windows `azurefactory` folder **on the API host**, canonical nonzero tenant
and subscription UUIDs, and an approved non-overlapping CIDR. Review the nonsecret
`team-ai` / `team-`, `swedencentral`, `main`, `gha`, DEV/001 and capacity-three
defaults too. Use a fresh isolated host folder and unused identity as in section 1;
do not recreate an existing factory or add its existing/default project001 again.
The request deliberately omits `initial_project`, letting the API create project001.

The approved API must already be running (Tkinter **Quick setup → Start API host**).
Use the actual URL and **the same authorized API key as that server**, supplied
privately; never put a key/token in JSON, code or Git:

```powershell
$env:AIFACTORY_API_URL = Read-Host 'Authorized running API URL'
$env:AIFACTORY_API_KEY = Read-Host 'Same API key as the server' -MaskInput
.\.venv\Scripts\python.exe .\aifactory_sdk.py --request .\aifactory.request.json `
  --receipt .\factory.receipt.json
if ($LASTEXITCODE -ne 0) { throw 'Stop: inspect blockers/errors; do not confirm.' }
```

`-MaskInput` requires PowerShell 7+. Keep `aifactory.request.json` and
`factory.receipt.json` private: exclude them and `.venv` from the **consumer's**
Git tracking and restrict local access; submodule ignore rules do not protect
consumer-root files.

**Prepare is configuration-only. Stop and obtain a separate human approval** of
the complete exact preview/receipt (including scope, blockers and expiry). Only
after that approval, in a separate invocation:

```powershell
.\.venv\Scripts\python.exe .\aifactory_sdk.py --confirm --receipt .\factory.receipt.json --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect host state before any retry.' }
Remove-Item Env:AIFACTORY_API_KEY
```

This thin starter calls the existing SDK-backed `python\create_factory.py` main,
retaining its request/receipt guards and exact saved-UUID verification. It is not a
new CLI or HTTP client, does not fetch code, and runs no Bash bootstrap, Azure
deployment or Git publication. `--help` needs neither the SDK nor the submodule.

### 3. Continue only with the intended scenario

Use [exact IDs](#2-discover-exact-ids-before-adding-scale-sets-and-projects) and
fresh revisions. Existing numbered templates cover clone-to-region, DEV scale
set 002, project002 in the existing scale and project003 in the new scale.
[Typed parameter editing](#3-update-project-resources-using-the-schema-not-guessed-field-names)
updates saved configuration only. [STAGE placement and deployment](#configuration-is-not-deployment)
are separate reviews; adding placement is **not** promotion in Azure. For
asynchronous deployment observation, use the existing CLI's
[bounded polling](#jobs-errors-and-approval-lifecycle), not a new deployment client.

**Evidence boundary:** this tutorial's unit tests use synthetic/offline responses.
Neither passing tests, local validation, `can_execute:true`, nor a saved catalog
draft proves that Azure has been provisioned. Provisioning and Git publication
require their own explicitly approved runtime/provider workflows and evidence.

**DEPLOY is a different step, not the next automatic quickstart command.**
The configured factory/project remains a draft. Before cloud execution, complete
and review the exact target's settings, provider binding, source publication,
coordination, identity and runner prerequisites. `runtime deploy` prepares a
runtime preview; only a separate approved `runtime confirm --yes` can execute
it. Do not run it merely to complete a recording of local configuration.

## Monitoring reports without collection or deployment

With the sibling CLI/SDK installed and an approved local API already running:

```powershell
azurefactory monitoring catalog
python .\python\monitoring_report.py --request .\monitoring\sample-summary.json --summary
python .\python\monitoring_report.py --request .\monitoring\sample-report.json
python .\python\monitoring_report.py --request .\monitoring\sample-export.json --export
pwsh -NoProfile -File .\powershell\Request-AzureFactory.ps1 -Method POST `
  -Path /api/v1/monitoring/report -BodyFile .\monitoring\sample-report.json -AllowWrite
```

The raw client's `-AllowWrite` permits HTTP POST; this specific canonical report
endpoint only calculates from supplied/sample evidence. It is not the legacy
automation start endpoint. These examples print responses, never launch Azure
collectors or write report files. API credentials use the existing environment
configuration described below.

The six report IDs are `agent-value`, `showback`, `foundry-tokens`,
`foundry-usage`, `quality-reliability`, `security-governance`. Change the sample
request's report ID to inspect each family. Project `001` under All factories
can match multiple compound identities; specify factory/scaleset/environment
for a single placement. The canonical response preserves filters, metric
provenance, missing evidence and sample labeling. Export returns the same scoped
projection as the API's CSV attachment, printed to stdout.

`--summary` calls `POST /api/v1/monitoring/summary` and returns all six report
sections under one source/scope/window. Its request has no `report_id`, and rows
are included only once. Summary and detailed requests accept paired
`start_date` / `end_date` values as inclusive UTC dates, at most 90 days.
Intervals must be fully contained; no partial-period cost or benefit is prorated.
Omitted bounds preserve legacy behavior, and `days` remains sample-generation
length rather than a live lookback. Use the returned frozen `sample_clock` and
observed period when selecting sample dates.

For live imports, supply an explicitly reviewed canonical request with
`source: live` and observation evidence. No API-host path or Azure authentication
is inferred. Estimates are not bills; modeled benefit is not verified realized
value, and model tokens are not business outcomes.

## Which API?

These examples use **the backend Python API used by the AI Factory Configuration
Wizard**. Its source entry point is `src/api.py` in the backend source directory. MAUI's
`build-windows.ps1` invokes the backend's `build-api.ps1` and bundles
`aifactory-api.exe`; MAUI does not implement a competing REST API. The bundled
host starts it on a dynamically selected loopback port with a per-process
`X-API-Key`. The source server defaults to port
8765. Obtain the actual address and authorized key from your API host/operator;
do not scrape another process's environment or commit connection secrets.

For an operator-provided host using port 64979, the addresses would be:

- OpenAPI: <http://127.0.0.1:64979/openapi.json> (one `http://`, not two)
- Swagger: <http://127.0.0.1:64979/docs>
- Health: <http://127.0.0.1:64979/health>

That port is an example, not a stable MAUI endpoint. These examples do not assert
that any particular host is listening. **GET `/api/v1/schema`** (not POST) describes
**wizard fields**, not HTTP routes. API version `1.0.0` alone is not a sufficient
compatibility check: the clients also depend on catalog contract **1**, typed
parameter endpoints and legacy project-deployment acknowledgement **2**.

The shared source/build contract explains which implementation is packaged; it
does **not** certify equality of running binaries or distributed installers.
No live compatibility claim is made for this update. After starting an approved
host, check its actual contract with the [CLI](../../azurefactory-cli/readme.md):

```powershell
azurefactory doctor
azurefactory doctor --local-openapi C:\contracts\approved-tkinter-openapi.json
```

`doctor` checks route/model/contract compatibility; optional OpenAPI comparison
does not prove identical behavior. Rebuild a stale MAUI sidecar from the approved
Tkinter source, rather than bypassing a missing safety contract.
`BUILD-INFO.json` records the packaged executable hash. Copying an OpenAPI file
alone does not update an executable.

## Configuration is not deployment

| Scenario | API flow | What it actually does |
|---|---|---|
| Create an AI Factory in region X | Catalog `create-factory` prepare, then confirm | Saves factory identity, explicit scales and one default project001 when `initial_project` is omitted; no Azure resources |
| Clone factory X to region Y | Catalog `clone` prepare, then confirm | Copies/rebinds configuration with new IDs; not resource, model, secret or data replication |
| Add DEV scale set 002 | Catalog `create-scale-set` prepare, then confirm | Registers a scale set; does not deploy common infrastructure |
| Add a project in existing scale set 001 | Catalog `add-project` prepare, then confirm | Creates the logical project and explicit DEV placement |
| Add a project in new scale set 002 | Confirm scale set 002, refresh IDs/revision, then add project | Two separately reviewed changes, not an atomic combined operation |
| Update a catalog project's resource configuration | GET typed parameters, prepare a patch, then parameters confirm | Preserves untouched values; Azure deployment remains a separate operation |
| Edit an existing **legacy JSON** project's configuration | Exact projects load, validate/render, separately approved projects save | Preserves JSON source metadata; snapshot/optional variable-file writes only, no deployment |
| Promote a catalog project to STAGE | Add STAGE scale set if absent, add project placement, review STAGE parameters, then catalog `deploy` | Explicit target configuration and deployment; not an automatic copy of all DEV settings/data |
| Update an existing **legacy** project | Legacy deployments plan `operation:update`, prepare, then start | Same environment, exact legacy factory folder |
| Promote an existing **legacy** project DEV to STAGE | Legacy deployments plan `operation:deploy`, prepare, then start | Later environment; validates the target's existing configuration |
| Create and deploy a new factory plus its first project | Full-bootstrap prepare, then start | Common infrastructure **and** initial project, repository creation/changes, commits/pushes, identity setup and pipeline dispatch |
| Move legacy configuration to the Azure Factory register | Catalog `migrate` with an explicit source folder | Reviewed local copy migration; not migration of Azure resources |

**Runtime is capability- and target-dependent.** Common-only, GHA and shared-remote
deployment require supported namespaced scoped routes, an explicit deployment
principal and a hosted/self-hosted Linux runner. Older route contracts may block
these requests; selecting an orchestrator is not proof of runtime support.
Deployment also requires a reviewed pipeline binding, supported coordination
enrollment (Azure Blob leases or explicitly governed repository single-writer
state), exact Azure identity, published source and matching parameter/runtime
capabilities. A template below may therefore produce blockers
instead of an executable preview. Honor them. Some configuration templates use
GHA; this does not claim that their catalog runtime deployment is supported.

Do not substitute `/operations/project-deployments` for a blocked catalog
deployment: those endpoints deliberately reject catalog roots. Do not silently
run the full-bootstrap launcher to add a scale set; bootstrap requires a new
empty destination and always includes an initial project.

## Prerequisites and connection

The API must already be running. For a source installation, the Tkinter
repository documents `python -m src.api` after installing its prerequisites and
setting `AIFACTORY_API_KEY` in the **server** environment. Standalone clients use
the same key. An API key authorizes the local service; it is not an Azure token.
Azure/GitHub/ADO authentication and deployment prerequisites live on the API
host and must match the selected tenant/subscription.

Examples require Python 3.10+ for JSON rendering, and either Node.js 20+ or
PowerShell 7+ for raw REST. There are no extra runtime packages. The CLI/SDK is
an alternative with stronger workflow guards and no Node/PowerShell dependency.

Run these commands from **this examples folder**:

```powershell
$env:AIFACTORY_API_URL = Read-Host 'Operator-provided API URL'
# Set AIFACTORY_API_KEY through your approved secret mechanism, not a committed file.
$env:FACTORY_FOLDER = Read-Host 'Absolute API-host azurefactory register root'
$env:FACTORY_KEY = Read-Host 'New readable factory key'
$env:FACTORY_PREFIX = Read-Host 'Approved factory prefix'
$env:FACTORY_REGION = Read-Host 'Azure region name'
$env:DEV_VNET_CIDR = Read-Host 'Approved DEV VNet CIDR'
$env:ORCHESTRATOR = Read-Host 'Provider: ado or gha'
$env:AIFACTORY_VERSION = 'main'
$env:DEV_SUBSCRIPTION_ID = '<actual-dev-subscription-uuid>'
$env:STAGE_SUBSCRIPTION_ID = '<actual-stage-subscription-uuid>'
$env:TENANT_ID = '<actual-tenant-uuid>'
New-Item -ItemType Directory -Force .local | Out-Null

node .\node\request.mjs --path /health
pwsh -NoProfile -File .\powershell\Request-AzureFactory.ps1 -Path /health
```

`FACTORY_FOLDER` and every `folder`, `aifactory_folder`, `repo_root` or file
`path` in an API request are **absolute paths on the API host**. They are not
uploads and are not necessarily paths on your portal user's machine. A fresh
register root is named `azurefactory`; keep an existing legacy `aifactory`
folder separate and opt into migration explicitly.

All business routes require `X-API-Key`. Public health/OpenAPI calls in the
examples omit it. Both raw clients reject non-loopback origins, embedded
credentials, path escapes and redirects; they do not retry requests.

## 1. Create a factory in a chosen region

This is the raw HTTP equivalent of the quickstart, not another creation step to
run after it. Render `requests\01-create-factory.json` with your approved prefix,
readable key, region, orchestrator, CIDR and version environment values. Change
the integer `max_projects` only after reviewing network capacity.
Use your approved registered version 125+ or `main`.
`initial_project` is deliberately omitted: current AI creation includes default
project001 in the submitted DEV/001 scale. Explicit `initial_project:null` would
instead request common-only; it is not the same as omission.
CIDRs elsewhere are illustrations, not an allocation recommendation.
Do not copy them into a peered network without reviewing overlap.

The renderer substitutes `${VARIABLE}` in **parsed JSON strings**. It preserves
booleans/numbers and safely escapes Windows paths; missing variables fail.
Output files are created exclusively and never silently overwritten.

```powershell
python .\python\render_request.py .\requests\01-create-factory.json --out .local\create.json
node .\node\request.mjs --method POST --path /api/v1/factory-catalog/prepare `
  --body .local\create.json --allow-write > .local\create-preview.json
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed or has blockers; inspect the response.' }
$preview = Get-Content .local\create-preview.json -Raw | ConvertFrom-Json
$preview | ConvertTo-Json -Depth 30
```

`prepare` may persist local preview state and perform preflight reads; it does
not authorize execution. Inspect **all** `effects`, `warnings`,
`network_warnings`, `address_warnings`, `blockers`, `operation_mode`, `target`,
source-version evidence and `expires_at`. Require `contract_version:1`,
`operation_mode:"configuration"`, `can_execute:true` and no blockers for this
create. The target must match what your user requested.

**Stop for approval.** Only after the operator approves this exact preview:

```powershell
if ($preview.contract_version -ne 1 -or $preview.operation_mode -ne 'configuration' -or
    $preview.can_execute -ne $true -or $preview.blockers.Count -gt 0 -or
    [DateTimeOffset]::Parse($preview.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Do not confirm this preview.'
}
$env:CONFIRMATION_ID = $preview.confirmation_id
python .\python\render_request.py .\requests\catalog-confirm.json --out .local\create-confirm.json
node .\node\request.mjs --method POST --path /api/v1/factory-catalog/confirm `
  --body .local\create-confirm.json --allow-write > .local\create-result.json
if ($LASTEXITCODE -ne 0) { throw 'Confirmation failed; inspect host state before retrying.' }
$created = Get-Content .local\create-result.json -Raw | ConvertFrom-Json
if ($created.contract_version -ne 1 -or $null -eq $created.catalog -or $null -ne $created.job) {
  throw 'Unexpected confirmation shape; do not automatically retry or start polling.'
}
python .\python\inspect_factory.py --folder $env:FACTORY_FOLDER `
  --factory-key $env:FACTORY_KEY --environment dev --suffix 001 --project-number 001
if ($LASTEXITCODE -ne 0) { throw 'Saved default project/placement could not be verified.' }
```

The same raw operation in PowerShell is:

```powershell
pwsh -NoProfile -File .\powershell\Request-AzureFactory.ps1 `
  -Method POST -Path /api/v1/factory-catalog/prepare -BodyFile .local\create.json -AllowWrite
```

Do **not** confirm both previews. Each preview represents its own immutable
request. Use the CLI/SDK for saved review receipts bound to connection and scope;
the raw examples intentionally expose the HTTP mechanics.

For a minimal curl comparison using the same rendered JSON:

```powershell
curl.exe --fail-with-body --silent --show-error --max-time 30 `
  --header "X-API-Key: $env:AIFACTORY_API_KEY" --header 'Content-Type: application/json' `
  --data-binary '@.local\create.json' "$env:AIFACTORY_API_URL/api/v1/factory-catalog/prepare"
```

Use this only on a trusted workstation: command-line header arguments can be
visible to local process inspection. Prefer the provided clients, which read
the key from the process environment. Never add curl `--location` with a secret
header. curl's HTTP success does not mean `can_execute:true`.

## 2. Discover exact IDs before adding scale sets and projects

Use names/suffixes for display and **UUIDs for selection**. DEV/001 and
STAGE/001 are different scale sets. Refresh the catalog after every confirmed
change; do not cache revision hashes indefinitely or select the first factory.

```powershell
$text = node .\node\request.mjs --path /api/v1/factory-catalog --query "folder=$env:FACTORY_FOLDER"
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the catalog.' }
$catalog = ($text -join "`n") | ConvertFrom-Json
$factories = @($catalog.factories | Where-Object key -eq $env:FACTORY_KEY)
if ($factories.Count -ne 1) { throw 'Select exactly one factory.' }
$factory = $factories[0]
$scales = @($factory.scale_sets | Where-Object { $_.environment -eq 'dev' -and $_.suffix -eq '001' })
if ($scales.Count -ne 1) { throw 'Select exactly one DEV scale set 001.' }
$env:FACTORY_ID = $factory.id
$env:DEV_SCALESET_001_ID = $scales[0].id
$env:CATALOG_REVISION = $catalog.revision
```

For each configuration scenario, render its JSON, POST to
`/api/v1/factory-catalog/prepare`, review, then separately confirm. Use new
filenames in `.local` for each review.

| Request file | Prerequisite / next step |
|---|---|
| `02-clone-factory.json` | Source `FACTORY_ID`; changes region and prefix. Default `include_projects:"none"`; opt into `"all"` only to copy project definitions. Review copied networking and new IDs. Bindings/credentials require separate setup. |
| `03-add-dev-scaleset-002.json` | Current factory/revision; after confirm select the new DEV/002 UUID into `DEV_SCALESET_002_ID`. |
| `04-add-project-existing-scaleset.json` | Uses `DEV_SCALESET_001_ID`, new project number 002; creation already supplied project001. |
| `05-add-project-new-scaleset.json` | First confirm scenario 03, refresh revision and IDs; then create project 003 in DEV/002. Number 002 is already used if scenario 04 ran. |
| `06-add-stage-scaleset-001.json` | Explicit STAGE subscription/network; save its UUID as `STAGE_SCALESET_001_ID`. |
| `07-add-project-stage-placement.json` | Select the existing logical project's UUID as `PROJECT_ID`; adds STAGE without creating a second logical project. |
| `08-deploy-catalog-project-stage.json` | Review STAGE parameters/binding first. This is a **runtime** preview; confirmation can execute billable actions. Runtime blockers may prevent execution. |
| `09-scoped-auth-status.json` | POST to `/api/v1/azure/auth/status` instead; read-only, no confirm. |
| `14-migrate-legacy-configuration.json` | Explicit legacy source and catalog destination. Review copy receipt and preserved identity; never automatically migrate during another action. |

Project numbers and suffixes remain three-digit strings. `"002"` is not numeric
`2`; a scale-set UUID is not the suffix `"002"`. New project numbers are unique
within the selected factory. The API validates placement ownership and capacity.

## 3. Update project resources using the schema, not guessed field names

The runnable **Python SDK** example performs the same exact selection and can
read both selected-scope authentication and parameter metadata. After installing
the [sibling CLI package](../../azurefactory-cli/readme.md):

```powershell
python .\python\inspect_factory.py --folder $env:FACTORY_FOLDER `
  --factory-key $env:FACTORY_KEY --environment dev --suffix 001 --project-number 001 `
  --auth-status --parameters
```

It refuses ambiguous names and project/scale-set placement mismatches, never
signs in automatically and never writes configuration or deploys resources.
This is a small reusable pattern for a portal's read-only backend handler.

For a project in DEV/001, select its exact `PROJECT_ID` from
`$factory.projects`, then read its typed parameter form:

```powershell
node .\node\request.mjs --path /api/v1/factory-catalog/parameters `
  --query "folder=$env:FACTORY_FOLDER" --query "factory_id=$env:FACTORY_ID" `
  --query "scale_set_id=$env:DEV_SCALESET_001_ID" --query "project_id=$env:PROJECT_ID" `
  > .local\parameters.json
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the published parameter schema.' }
$parameters = Get-Content .local\parameters.json -Raw | ConvertFrom-Json
$parameters.templates | Select-Object template, scope, fields
```

Template names, parameter names, enums and types depend on the selected
published accelerator version. Choose them from `templates[].parameter_schema`
and `fields`, not from hard-coded names in a custom portal.
The API **does not return saved values**; it reports configured/resolved/sensitive
metadata. Do not submit a blank form as replacement data.

The Python form-adapter example builds a **single non-sensitive replacement**
and carries both revision hashes:

```powershell
python .\python\parameter_patch.py .local\parameters.json `
  --folder $env:FACTORY_FOLDER --template '<exact-template-from-response>' `
  --parameter '<exact-boolean-parameter-from-schema>' --value-json true `
  --out .local\parameter-change.json
node .\node\request.mjs --method POST --path /api/v1/factory-catalog/parameters/prepare `
  --body .local\parameter-change.json --allow-write
```

Review the resulting preview. Confirm through
`POST /api/v1/factory-catalog/parameters/confirm` with the same
`{folder,contract_version:1,confirmation_id}` shape as `catalog-confirm.json`.
Do not send it to a different workflow's confirm route. The API is the final
authority on allowed types, immutable identity, secrets and resource ownership.

On revision conflict, re-read and ask the operator to review again.
`reset_profile:true` discards previous version contexts; the example refuses it
instead of silently clearing settings. Deployment/update in Azure is separate.
For catalog STAGE promotion, repeat this step with the **STAGE** scale-set ID and
review intended target settings before scenario 08.

## 4. Legacy project update and promotion

These endpoints are for an existing **single-factory legacy root**, not the
Azure Factory register. Set `LEGACY_FACTORY_FOLDER` to that exact `aifactory`
folder. The folder's saved configuration determines its scale-set identity;
there is no `scale_set_id` field in the legacy plan contract. Do not invent one
or route multiple factories through a global CLI default account.

1. Render `10-legacy-update-project-dev.json` or `11-legacy-promote-project-stage.json`.
2. POST to `/api/v1/operations/project-deployments/plan`; this creates a local draft, not a deployment.
3. Require `deployment_contract.version:2`, matching `draft_id`, `operation`, `patch` and version selection; save the returned `id` as `DRAFT_ID`.
4. Render `legacy-deployment-prepare.json`, POST to `/api/v1/operations/project-deployments/prepare`, and recheck the acknowledgement plus effects/blockers/expiry.
5. After approval, render `legacy-deployment-start.json` and POST to `/api/v1/operations/project-deployments/start`.

The [CLI/SDK](../../azurefactory-cli/readme.md) implements these acknowledgement
guards and is recommended over manually chaining raw requests.

`patch:false` preserves the installed accelerator for project-only execution.
For an intentional accelerator patch, explicitly set `patch:true` consistently
in plan and prepare and review the resolved source commit/version; do not let an
older server silently ignore the choice. Update is same-environment; deploy
allows DEV to STAGE, STAGE to PROD, or DEV to PROD. A promotion does not claim
that customer data or model artifacts have been replicated.

### Edit a legacy JSON configuration with the Python SDK

Editing configuration is a separate operation from the legacy deployment
plan/prepare/start flow above. The runnable `python\edit_configuration.py` uses
the public `AzureFactoryClient` and `ConfigurationDraft` SDK, not a second HTTP
client implementation. It defaults to **review only** and prints review metadata.
Install the sibling package once in your Python environment:

```powershell
python -m pip install -e ..\..\azurefactory-cli
python .\python\edit_configuration.py --help
```

Supply the authorized API URL/key through `AIFACTORY_API_URL` and
`AIFACTORY_API_KEY`; there is no API-key command-line option. Use the **exact
legacy `aifactory` folder and three-digit project number**, not a catalog root.
The SDK calls POST `/api/v1/projects/load` with
`{"aifactory_folder":"C:\\legacy\\aifactory","project_number":"001"}`.
`/api/v1/startup/load` is only a hint and must not choose the project for editing.
Catalog roots are rejected by `/projects/load`; use section 3's existing typed
parameter flow for catalog resource changes. Registering STAGE placement is
also separate from actually deploying/promoting there.

Prepare a private local `changes.json`: a JSON object containing only intended
replacements for exact editable fields from GET `/api/v1/schema` and the selected
configuration. Private keys, `project_number_000` overrides and unknown field
names are refused. Do not reconstruct the state from a form or saved CLI output.
The patch file is on your **client machine**; `--folder` names a directory on the
**API host**. Protect the patch and review its values locally without logging them.

```powershell
python .\python\edit_configuration.py --folder C:\legacy\aifactory --project-number 001 --changes-json .\changes.json
```

Omit `--changes-json` to review the current configuration without replacements.
Review performs API offline validation and in-memory JSON export **without a
path**, so it writes no configuration and does not validate/deploy in Azure.
It returns a 64-hex `review_id`, `can_save`, folder/project scope, `changed_fields`,
`write_variables`, validation issues, warnings and effects. No raw state,
`_json_source`, rendered JSON or patch values are printed. **The operator must
review the patch file too:** changed names alone do not establish approval of
the values.

**Stop here for explicit human approval.** Only in a separate invocation, after
approving that exact patch and metadata, copy the earlier `review_id`:

```powershell
python .\python\edit_configuration.py --folder C:\legacy\aifactory --project-number 001 --changes-json .\changes.json --save --expected-review <review_id> --yes
```

Both `--expected-review` and `--yes` are required with `--save`; neither is
accepted in review-only mode. `save()` repeats validation/rendering and requires
`can_save` and the same hash before sending the full edited state to
`/api/v1/projects/save`. Use `--snapshot-only` in **both** invocations to save
only a snapshot; by default, pipeline variable files are written too. Save
output is limited to returned snapshot/variable paths and warnings, never a
source-state file. Neither invocation deploys, changes accounts, commits or pushes.

Persistent `variables.json` loads return the full state with an opaque
`_json_source` fingerprint/baseline reference. Preserve **all** state and unknown
private keys unchanged except the explicit public-field edits; the SDK does
this for you. Never interpret, edit, display or reconstruct that reference.
Older lossy snapshots and inline-content imports are not safe editable JSON
sources. This guarded example blocks a missing persistent `_json_source`;
generic YAML/env support remains available through the low-level API, not this
JSON-origin review/save workflow.

The hash binds source state, patch, base URL, scope, validation, warnings,
rendered content and write choice. It is not authentication, a signature,
a backend ETag, cross-user approval or an atomic concurrency guarantee. Your
backend must authorize each operator and bind approval to their exact intent.
The server also rejects a changed source fingerprint. Reload/review after every
successful save; obtain fresh approval after any changed input. Do not blindly
retry an ambiguous save error: inspect host state securely first.

The example uses [CLI/SDK exit codes](../../azurefactory-cli/readme.md#exit-codes),
including 2 for local patch/usage errors and 3 for a blocked review/save.
API errors preserve their SDK exit code without printing raw error bodies;
unexpected programming errors are not swallowed. See the
[low-level SDK method table](../../azurefactory-cli/readme.md#sdk) for path-only
import, validation and export. In particular, supplying an export `path` **writes
on the API host**; it is not equivalent to this review-only render.

## 5. Full bootstrap, GHA or Azure DevOps

`12-full-bootstrap-gha.json` and `13-full-bootstrap-ado.json` target
`POST /api/v1/creation/bootstrap/prepare`. Read
`GET /api/v1/creation/capabilities` for currently supported launchers and fields.
Set the nonempty `${...}` values in your environment before rendering.

Bootstrap requires a new/empty `NEW_REPO_ROOT`, explicit initial project/scale
numbers, existing tenant/subscription, team identity and real cost center.
GHA uses `owner/repository` and a private repository. ADO uses an existing
accessible project and a **new** repository, an explicit service connection,
and the host's supported Entra/CLI authentication. Do not put credentials in
the config. `setup_hub_access:false` is an explicit example choice; change it
only after reviewing whether VPN Gateway/Bastion should be deployed.

Review the **full-bootstrap** preview, complete echoed configuration,
`includes_common:true`, `includes_initial_project:true`, source commit,
requirements, effects, warnings and blockers. Only after approval POST
`bootstrap-start.json` to `/api/v1/creation/bootstrap/start`.

This executes the published standard bootstrap, not a full-fidelity export of
arbitrary wizard resource settings or a Simple Mode preset. It can create
billable Azure infrastructure and roles, create/change repositories, commit,
push and dispatch pipelines. Stage/Prod require separate later review.

## Jobs, errors and approval lifecycle

| Workflow | Polling / output | Meaning |
|---|---|---|
| Catalog runtime | GET `/api/v1/factory-catalog/jobs/{job_id}?folder=...` and `/terminal?folder=...&job_id=...&cursor=0` | `queued`, `running`, then `succeeded`, `failed` or `interrupted` |
| Legacy project deployment | GET `/api/v1/operations/project-deployments?folder=...`; select the exact draft/job | `submitted` means launcher/pipeline submission, **not verified Azure deployment success** |
| Legacy terminal | GET `/api/v1/operations/project-deployments/terminal?folder=...&job_id=...&cursor=0` | Advance to `next_cursor`; honor `reset`; HTTP polling, not an invented WebSocket endpoint |
| Bootstrap | GET `/api/v1/creation/bootstrap/jobs/{job_id}` | Bounded high-level events and launcher status; follow pipeline/Azure outcome separately |

Use finite polling deadlines and persist the returned job ID. A client timeout
or Ctrl+C does not cancel a server job. Re-read state before considering another
write; never blindly retry a start after a lost HTTP response. Preview IDs are
owner-bound and expiring; use the returned `expires_at`, not a hard-coded lifetime.
Changed scope, source,
configuration or expired consent requires another explicit review, not automatic
re-preparation/approval. Reconciliation is a separately reviewed operation, not
permission to rerun a failed deployment.

Catalog **configuration** confirmations return `catalog` plus `job:null`; do not
poll them. Only a separately approved **runtime** confirmation returns
`catalog:null` and a nested `job` object. Its ID is `result.job.id`, not a guessed
top-level `job_id`. For an already authorized runtime job, use the existing CLI:

```powershell
# Set JOB_ID from the exact runtime-confirm response; no prepare/start here.
azurefactory runtime poll --folder $env:FACTORY_FOLDER --job-id $env:JOB_ID `
  --poll-timeout 300 --poll-interval 2
if ($LASTEXITCODE -ne 0) { throw 'Job failed/interrupted/timed out; inspect before considering another action.' }
azurefactory runtime logs --folder $env:FACTORY_FOLDER --job-id $env:JOB_ID --cursor 0
```

The deadline bounds observation, not execution. Per-request HTTP timeout also
applies. A custom UX must validate `job.id`, action and exact target IDs, accept
only the documented statuses, and stop at its deadline. Check provider pipeline
and Azure resource results separately before claiming provisioning; legacy
`submitted` is explicitly not deployment success.

The raw clients emit JSON to stdout and errors to stderr. Exit codes: **0**
successful HTTP result, **2** argument/transport/HTTP/JSON error, **3** blocked
preview, **4** top-level failed/interrupted job. They do not automatically
interpret nested jobs or validate every acknowledgement; use the SDK for
workflow semantics. Handle 401/403 as identity/authorization problems, 409 as
scope/revision/capability conflicts, and 422 as request validation errors.

## Integrating a central cloud team's own UX

Use the importable Python SDK in your trusted backend, or translate the raw
Node/PowerShell requests into your existing backend language. An appropriate
request flow is:

```text
User's portal -> authenticated, authorized cloud-team backend
             -> loopback Config Wizard API -> host-local configuration / approved pipeline
```

Keep the API key and Azure authentication **out of browser JavaScript**. Do not
expose the desktop sidecar on a public interface or assume its shared local API
key provides per-user authorization. Authenticate users in your backend, enforce
factory/tenant/subscription permissions, restrict allowed host folders and
operations, and map review receipts to the correct user and session. Isolate
workers/service identities when serving multiple customers; the local sidecar
is not a turnkey multi-tenant control plane.

Render schema-driven forms, preserve exact IDs and revisions, show the server's
complete preview, and require explicit approval before the confirm/start call.
Record safe audit metadata (actor, target IDs, source commit, approval and job ID);
do not log secrets, complete parameter payloads or raw terminal output by default.
The same design works whether Tkinter, MAUI or your service manages the host.

## Layout and maintenance

`requests` holds JSON templates; `scenarios.json` maps every template to its
actual POST route and canonical request model. `python` contains safe rendering,
schema-to-patch, read-only inspection, two-phase catalog creation and guarded JSON-configuration SDK examples;
`node` and `powershell` contain raw REST consumers.
`.local` is ignored for generated requests/reviews, but ignore rules are not
encryption or access control. Protect and delete local artifacts appropriately.

Run the existing pytest runner from this folder:

```powershell
python -m pytest .\tests ..\..\azurefactory-cli\tests\test_cli.py `
  ..\..\azurefactory-cli\tests\test_client.py ..\..\azurefactory-cli\tests\test_reviews.py `
  ..\..\azurefactory-cli\tests\test_quickstart_examples.py -q --basetemp .local\pytest-work
```

Optionally validate every template against the backend Python API's Pydantic models
and in-process route definitions using the backend's existing development environment:

```powershell
$env:AIFACTORY_API_SOURCE = 'C:\path\to\ai-factory-backend'
& "$env:AIFACTORY_API_SOURCE\.venv\Scripts\python.exe" -m pytest .\tests -q
```

These are offline tests with loopback fixture servers; they do not sign in,
change a real factory or deploy Azure resources.