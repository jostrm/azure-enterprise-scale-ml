# Enterprise Scale AI Factory: API integration examples

Build your own central-cloud-team UX against the configuration wizard API, not
against Tkinter widgets, MAUI views, generated configuration files or shell
launchers. These examples and the [Azure Factory CLI / Python SDK](../../azurefactory-cli/readme.md)
use the same HTTP API.

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

**Tkinter is the canonical backend**, here at
`C:\code\code_py_25\008_aifactory_admin_ux_tkinter\src\api.py`. MAUI's
`build-windows.ps1` invokes the Tkinter repository's `build-api.ps1` and bundles
`aifactory-api.exe`; MAUI does not implement a competing REST API. The bundled
host starts it on a dynamically selected loopback port with a per-process
`X-API-Key`. The source server defaults to port
8765. Obtain the actual address and authorized key from your API host/operator;
do not scrape another process's environment or commit connection secrets.

For an operator-provided host using port 64979, the addresses would be:

- OpenAPI: <http://127.0.0.1:64979/openapi.json> (one `http://`, not two)
- Swagger: <http://127.0.0.1:64979/docs>
- Health: <http://127.0.0.1:64979/health>

That port is an example, not a stable MAUI endpoint; it was **not listening**
during this update. **GET `/api/v1/schema`** (not POST) describes
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
| Create an AI Factory in region X | Catalog `create-factory` prepare, then confirm | Saves factory identity and explicit scale-set definitions; no Azure resources |
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

**Current runtime limits are intentional.** The Tkinter catalog runtime blocks
common-only creation, GHA dispatch without atomic reviewed-commit support, and
shared-remote execution without supported namespaced authentication templates.
Runtime deployment additionally requires an explicit reviewed pipeline binding,
Azure Blob lock enrollment, exact Azure identity, published source and supported
parameter/runtime capabilities. A template below may therefore produce blockers
instead of an executable preview. Honor them. Configuration examples use GHA;
this does not claim that their catalog runtime deployment is supported.

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
$env:AIFACTORY_API_URL = 'http://127.0.0.1:64979'
# Set AIFACTORY_API_KEY through your approved secret mechanism, not a committed file.
$env:FACTORY_FOLDER = 'C:\AIPlatform\azurefactory'
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

Edit `requests\01-create-factory.json` for your approved prefix, readable
factory key, region, orchestrator, network capacity and source version.
`main` is explicit in the example; use your approved published version instead
when required. CIDRs are illustrations, not an allocation recommendation.
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
  --body .local\create-confirm.json --allow-write
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
$factories = @($catalog.factories | Where-Object key -eq 'central-ai-sweden')
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
| `04-add-project-existing-scaleset.json` | Uses `DEV_SCALESET_001_ID`, project number 001. |
| `05-add-project-new-scaleset.json` | First confirm scenario 03, refresh revision and IDs; then create project 002 in DEV/002. |
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
  --factory-key central-ai-sweden --environment dev --suffix 001 --project-number 001 `
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
owner-bound and expiring (currently ten minutes); changed scope, source,
configuration or expired consent requires another explicit review, not automatic
re-preparation/approval. Reconciliation is a separately reviewed operation, not
permission to rerun a failed deployment.

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
schema-to-patch, read-only inspection and guarded JSON-configuration SDK examples;
`node` and `powershell` contain raw REST consumers.
`.local` is ignored for generated requests/reviews, but ignore rules are not
encryption or access control. Protect and delete local artifacts appropriately.

Run the existing pytest runner from this folder:

```powershell
python -m pytest .\tests -q
```

Optionally validate every template against the actual Tkinter Pydantic models
and in-process route definitions using the backend's existing development environment:

```powershell
$env:AIFACTORY_API_SOURCE = 'C:\path\to\008_aifactory_admin_ux_tkinter'
& "$env:AIFACTORY_API_SOURCE\.venv\Scripts\python.exe" -m pytest .\tests -q
```

These are offline tests with loopback fixture servers; they do not sign in,
change a real factory or deploy Azure resources.