# azurefactory-cli

Stdlib-only Python SDK and CLI for the local AzureFactory API. Like MAUI, the CLI
uses the shared Python API for registered Full bootstrap: the server owns the
provisioning stages, and the client prepares, approves and observes them.
Advanced `enrollment plan|ensure|plan-and-publish` commands instead use the local
enrollment core with explicit Azure/provider authentication; they are not an
additional prerequisite for API-managed Full bootstrap. Start with the
[runnable API scenarios](../install_config_wizard/api-usage-examples/readme.md)
for prerequisites, exact UUID selection and central-cloud-team integration.

## Install

```powershell
cd <repo>\environment_setup\azurefactory-cli
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:AIFACTORY_API_URL = Read-Host 'Operator-provided API URL (default source port is 8765)'
# Set AIFACTORY_API_KEY privately through your approved secret mechanism.
```

The API key is sent only as `X-API-Key`; the CLI does not log or store it. Plain `http` is accepted only for loopback hosts. `https` is also accepted. Redirects, URL credentials and absolute endpoint escapes are rejected.

Server reference: canonical Tkinter API source `<tkinter-repository>\src\api.py`; MAUI's
`build-windows.ps1` invokes Tkinter's `build-api.ps1` and packages the resulting
`aifactory-api.exe`, not a separate REST implementation. The packaged host uses
a random loopback port and per-process key. This source/build relationship does
not certify a running binary or assert that a particular port is listening.
Obtain the actual URL/key from your operator and run `doctor`
against that host. Local API authentication is distinct from both the Azure CLI
identity on the host and a user's approval to save or deploy.

## Quickstart: CONFIGURE a factory with default project001 locally

Use **this existing CLI**, not another CLI or a deployment shell fallback. The
[API tutorial's connection step](../install_config_wizard/api-usage-examples/readme.md#1-connect-and-supply-the-target)
sets the operator-provided API URL/key and user-supplied
`FACTORY_FOLDER`, `FACTORY_KEY`, `FACTORY_PREFIX`, `FACTORY_REGION`,
`DEV_SUBSCRIPTION_ID`, `TENANT_ID`, `DEV_VNET_CIDR`, `ORCHESTRATOR` and
`AIFACTORY_VERSION`. From the repository root the installation command is
`python -m pip install -e .\environment_setup\azurefactory-cli`.

For this quickstart, use a **fresh isolated demo** `azurefactory` directory that
already exists **on the API host**, not the actual consumer's register or a
legacy `aifactory` root. The host operator creates only a separate empty
directory; do not copy an existing register, saved factories, bindings or
credentials. No additional CLI initialization command is needed.
An existing `DRAFT` factory already occupies its key and prefix/region:
`factory create` does not reopen/upsert it. On conflict, inspect it read-only or
choose a fresh isolated demo root/identity; never reset/delete the actual register
or rerun creation against the occupied identity.

**CONFIGURE means local drafts. DEPLOY means explicit cloud execution.**
These commands may
persist previews/drafts but do **not** deploy, publish Git, enroll a provider,
create subscriptions or change the host's Azure account:

```powershell
azurefactory health
if ($LASTEXITCODE -ne 0) { throw 'API unavailable.' }
azurefactory doctor
if ($LASTEXITCODE -ne 0) { throw 'Incompatible API; stop.' }
$beforeText = azurefactory catalog list --folder $env:FACTORY_FOLDER
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the selected demo catalog.' }
$before = ($beforeText -join "`n") | ConvertFrom-Json
if ($before.contract_version -ne 1 -or $before.mode -ne 'catalog' -or @($before.factories).Count -ne 0) {
  throw 'Use a fresh isolated azurefactory root; do not recreate an occupied factory.'
}
azurefactory factory create --folder $env:FACTORY_FOLDER --factory-key $env:FACTORY_KEY `
  --prefix $env:FACTORY_PREFIX --region $env:FACTORY_REGION --kind ai `
  --environment dev --suffix 001 --subscription-id $env:DEV_SUBSCRIPTION_ID `
  --tenant-id $env:TENANT_ID --orchestrator $env:ORCHESTRATOR `
  --vnet-cidr $env:DEV_VNET_CIDR --max-projects 3 --aifactory-version $env:AIFACTORY_VERSION `
  --save-receipt .\factory.receipt.json
if ($LASTEXITCODE -ne 0) { throw 'Review errors/blockers; do not confirm.' }
```

Omission of project flags means exactly one initial AI project001, selected by
the backend and placed in DEV/001. Review the target's IDs, region, subscription,
tenant, network, project placement, effects/warnings/blockers and expiry.
Require contract 1 and configuration mode; defaults are not verified deployment
readiness. **Stop for human approval of that exact preview.** Only afterward,
in a separate invocation:

```powershell
azurefactory catalog confirm --receipt .\factory.receipt.json --yes
if ($LASTEXITCODE -ne 0) { throw 'Inspect host state; never blindly retry confirmation.' }
azurefactory catalog list --folder $env:FACTORY_FOLDER
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify the saved register.' }
```

Expect `contract_version:1`, `catalog:<CatalogSummary>` and `job:null`, not a
runtime job. Check the exact factory UUID from the preview and its project001
placement in the returned catalog. Do **not** add project001 again. The
[executable direct API equivalent](../install_config_wizard/api-usage-examples/readme.md#2b-alternatively-prepare-through-the-direct-api-example)
reuses this package and receipt helpers, verifies the saved UUIDs with a fresh
GET, and does not start Azure deployment. Choose one creation path only.

For the remaining scenario sequence, reuse the existing commands below:
`factory clone` for another region; `scaleset add --environment dev --suffix
002`; `project add --number 002` in existing DEV/001 or `--number 003` in new
DEV/002 if both scenarios run; `parameters get/prepare/confirm` for saved
resource changes. STAGE requires its own scale set, `project add-placements`,
reviewed target parameters/enrollment and separately approved `runtime deploy`.
Placement alone is not Azure promotion; legacy update/promote is a separate
contract. Observe runtime jobs with `runtime poll --poll-timeout 300
--poll-interval 2`; a timeout does not cancel the job. No runtime confirm is part
of this quickstart.

Offline test success, local validation and saved drafts are **not** evidence of
Azure provision or Git publication. A blocked deployment must remain blocked,
not be rerouted through legacy/bootstrap commands.
The isolated directory protects local state; it is not an Azure sandbox.
`runtime deploy` only prepares a separate cloud/runtime preview; an explicitly
approved `runtime confirm --yes` executes it. Neither belongs in the local
configuration recording's happy-path.

## Core commands

### Delete a whole factory's Azure resources

`delete-aifactory` uses only the shared API's named deletion routes, never local
`az`/`gh`, legacy scripts or a catalog fallback. An older API without
`delete-aifactory-v1` is blocked. This is **Azure resource deletion**, not removal
of a saved factory entry.
Repository-only single-writer deletion availability depends on published backend
support and the exact preview's `can_execute` result; the named API capability
alone does not establish readiness. A blocked preview remains blocked; do not
change coordination settings, run separate deletions or use another route to
bypass it.

The factory's existing enrollment must also explicitly permit deletion
(`allow_delete=true`). A confirmation prompt does not grant that permission.
New enrollment defaults to disallowing deletion; have an authorized operator
review that governance setting rather than bypassing it.

First select the exact factory UUID and current `source_revision` from
`azurefactory catalog list --folder $env:FACTORY_FOLDER`, then prepare:

```powershell
azurefactory delete-aifactory prepare --folder $env:FACTORY_FOLDER `
  --factory-id $env:FACTORY_ID --expected-revision $env:CATALOG_REVISION `
  --save-receipt .\delete-factory.receipt.json
```

Preparation does not delete anything. Review **all** listed scale sets, resource
groups, subscriptions, tenants, exact `delete`/`retain` resource IDs, source
version, warnings and expiry. The backend must explicitly acknowledge Entra
security-group preservation and saved-configuration handling. Repositories,
subscription-level configuration and outside-group dependencies are not claimed
deleted; the backend's retained-resource warnings describe the limitations.
Empty, narrowed, inconsistent or broadened manifests cannot be confirmed.
The review reports the backend's saved-configuration handling explicitly:
the current backend removes the local catalog registration/configuration only
after verified whole-factory deletion succeeds, and retains it on failure.
Entra security groups and Git history remain preserved.

The review must also include the server's `deletion_retention_policy`, mirrored
in `deletion_plan.retention_policy`: preserve reusable infrastructure, require
`ordered-project-pipelines-v1`, execute whole resource groups, and report
`selective_retention_supported:false`. The CLI displays and receipt-binds its
limitations; an executable preview missing or contradicting this policy is
rejected, including from an older server. No `--preserve-hub` shortcut invents
runtime support. Protected/retained IDs come from the frozen plan and must
match the preview. Hub/VPN/bootstrap/platform infrastructure inside an owned
group blocks preparation, rather than allowing a cascading group delete.
Outside-group retained inventory is not proof of post-execution preservation.
The selected immutable runtime must independently support the required contract.

After a human approves that exact review, run a separate command:

```powershell
azurefactory delete-aifactory confirm --receipt .\delete-factory.receipt.json
```

The terminal displays “Are you sure…” and the complete review before asking
whether to continue and requiring the exact server phrase, `DELETE <factory key>`.
`--yes` alone **never** deletes. Declining, end-of-input or a wrong phrase sends
no confirmation. Without an interactive terminal, both `--yes` and
`--confirmation-phrase` containing the exact reviewed server phrase are required.
These flags do not replace human/session approval when an assistant runs tools.
The CLI sends the receipt-bound **server** preview hash, not a regenerated
approval. Receipts are bound to the API URL, folder, factory, revision and expiry;
existing receipt files are never overwritten.

Observe the returned job without retrying deletion:

```powershell
azurefactory delete-aifactory status --folder $env:FACTORY_FOLDER --job-id $env:DELETE_JOB_ID
```

A timeout is an **unknown outcome**, not cancellation or permission to retry.
Inspect server state before further action; confirmation is never retried
automatically. Tests use mocked transport only and do not establish Azure
deletion success.

### Shell-first registered onboarding

From the root of an existing consumer Git repository, with a **current approved**
shared submodule:

```bash
git -C ./azure-enterprise-scale-ml status --short --branch
git -C ./azure-enterprise-scale-ml rev-parse HEAD
test -f ./azure-enterprise-scale-ml/01-start-v125-and-above.sh
bash ./azure-enterprise-scale-ml/01-start-v125-and-above.sh
bash ./azurefactory.sh api instructions
```

The source entrypoint installs the same CLI plus registered ADO/GHA root helpers
without running legacy template copy/cleanup. `--provider ado|gha` selects just
one wrapper without deleting the other. Reruns back up changed helpers and
preserve register configuration, explicit saved versions and `.gitignore`;
`--refresh-only` installs helpers without initializing storage. The printed
source commit/dirty state and payload digest describe the files actually used.
They do not certify a published release or the running API binary.
Nothing updates a nested submodule automatically; missing entrypoint means stop
and obtain reviewed current source, not fall back to legacy `00-start.sh`.

**An API is required for catalog creation, but a GUI is not.** `api instructions`
works offline and prints the selected URL and canonical backend startup pattern:
in an approved Tkinter checkout with its documented prerequisites installed,
set the server's `AIFACTORY_API_KEY` privately and run `python -m src.api`.
Keep that terminal running; configure the same key in the client shell and use
`AIFACTORY_API_URL` for a non-default authorized host. Run `health` then `doctor`.
The installed wrapper supports all commands below as `bash ./azurefactory.sh ...`.
No API executable, secret or downloaded shell script is copied into the consumer.

Empty register initialization creates **no factory or project**. The separate
`factory create` preview and approved `catalog confirm` configure the factory
plus one initial project (default project001, `--project-number` for another).
Registered sources are 125+ or `main`; 124 is not a registered fallback.
Omitting the version delegates to the current API's registered default; pass
`--aifactory-version 125` or `--aifactory-version main` to select explicitly.
Deployment remains a separate reviewed runtime operation. See the
[end-to-end shell workflow](../../documentation/v2/20-29/24-end-2-end-setup.md#shell-first-new-registered-consumer-v125--main).

The modern raw Simple/Full creation launchers map `AIF_SETUP_HUB_ACCESS` into
`config.setup_hub_access` for `/api/v1/creation/prepare`. With
`AIF_SIMPLE_MODE=true`, omit it (or use `true`/`y`) to retain the owned-hub preset;
set `AIF_SETUP_HUB_ACCESS=false` (or `n`) for standalone, with no owned or external
hub. Other values are rejected. The API accepts only a JSON boolean for this
optional field and saves both hub and central-hub DNS flags as false for standalone.
This modern override does not change the legacy 124 Simple contract or deploy
anything; review and confirm the local configuration before separate deployment.

```powershell
azurefactory health
azurefactory doctor
# Optional: compare against an approved Tkinter OpenAPI snapshot.
azurefactory doctor --local-openapi C:\contracts\approved-tkinter-openapi.json
azurefactory schema
azurefactory auth status --folder C:\factory --factory-id <uuid> --scale-set-id <uuid> --expected-tenant-id <uuid> --expected-subscription-id <uuid>
azurefactory catalog list --folder C:\factory
azurefactory catalog settings --folder C:\factory --factory-id <uuid> --scale-set-id <uuid> --project-id <uuid>
azurefactory parameters get --folder C:\factory --factory-id <uuid> --scale-set-id <uuid>
```

### Review scoped settings without deployment

**Implemented in source:** `AzureFactoryClient.catalog_settings_prepare()` and
`azurefactory catalog configure-settings` wrap the existing REST
`POST /api/v1/factory-catalog/prepare` action `configure-settings`. Confirmation
still uses `catalog_confirm()` / `catalog confirm` and the same REST `/confirm`.
There is no new API route or deployment capability. Installed clients may lag.

Supply only intentional replacements: omitted keys remain unchanged. The API
owns `field_keys`, defaults, immutable identity checks, and persistence. Discover
supported fields with `catalog settings`; do not infer gateway/MCP support from a
newer document or source commit. Factory scope omits both selectors; scale scope
adds `--scale-set-id`; project scope adds `--project-id`. With both selectors, the
scale must be one of the project's placements. **Project settings are shared
project configuration, not an environment-only patch**, even when a scale is
selected. Registered project variable sections follow the canonical API rules.

This advanced example needs an existing catalog; it is not an empty-catalog smoke
test. It changes the saved Redis setting only. Disabling a flag does not authorize
resource removal, deploy anything, or change a running job's frozen inputs.

**Window A: inspect and prepare** (PowerShell 7; obtain URL/key from your API host):

```powershell
$env:AIFACTORY_API_URL = Read-Host 'Actual API host URL'
$env:AIFACTORY_API_KEY = Read-Host 'API key' -MaskInput
$folder = Read-Host 'Catalog folder on the API host'
$factoryId = Read-Host 'Exact factory UUID'
$receiptPath = Read-Host 'New local settings review receipt path'
$current = azurefactory catalog settings --folder $folder --factory-id $factoryId | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Settings inspection failed' }
$current | ConvertTo-Json -Depth 30
$changesPath = Join-Path $env:TEMP ("factory-settings-" + [guid]::NewGuid() + ".json")
@{ enableRedisCache = 'false' } | ConvertTo-Json | Set-Content -LiteralPath $changesPath -Encoding utf8
azurefactory catalog configure-settings --folder $folder --factory-id $factoryId `
  --settings-json $changesPath --expected-revision $current.revision --save-receipt $receiptPath
$prepareExit = $LASTEXITCODE
Remove-Item -LiteralPath $changesPath
if ($prepareExit -ne 0) { throw 'Preparation failed or was blocked; do not confirm' }
Get-Content -LiteralPath $receiptPath
```

**Window B: review, approve, save, then observe.** Setup is repeated because
PowerShell variables do not transfer between windows. Inspect both `request`
(exact replacements) and `preview` (scope, effects, blockers, revision, expiry).

```powershell
$env:AIFACTORY_API_URL = Read-Host 'Same API host URL used for preparation'
$env:AIFACTORY_API_KEY = Read-Host 'Same API key used for preparation' -MaskInput
$receiptPath = Read-Host 'Local settings review receipt path from Window A'
$review = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
$review | ConvertTo-Json -Depth 40
if ((Read-Host 'Type SAVE to approve this exact configuration-only review') -cne 'SAVE') { throw 'Not approved' }
azurefactory catalog confirm --receipt $receiptPath --yes
if ($LASTEXITCODE -ne 0) { throw 'Save not confirmed; inspect current settings before any new review. Do not retry automatically.' }
azurefactory catalog settings --folder $review.folder --factory-id $review.request.factory_id
if ($LASTEXITCODE -ne 0) { throw 'Post-save inspection failed' }
```

**Equivalent Python SDK flow** (one process, with a separate explicit approval
prompt; stdlib plus the installed `azurefactory` package):

```python
import getpass
import json
from azurefactory import AzureFactoryClient, load_receipt, write_receipt

client = AzureFactoryClient(input("Actual API host URL: "), getpass.getpass("API key: "))
folder = input("Catalog folder on API host: ")
factory_id = input("Exact factory UUID: ")
receipt_path = input("New local settings review receipt path: ")
current = client.catalog_settings(folder, factory_id)
changes = {"enableRedisCache": "false"}
request = {
    "contract_version": 1, "action": "configure-settings", "folder": folder,
    "factory_id": factory_id, "settings": changes, "expected_revision": current["revision"],
}
preview = client.catalog_settings_prepare(
    folder, factory_id, changes, expected_revision=current["revision"],
)
print(json.dumps({"request": request, "preview": preview}, indent=2))
write_receipt(receipt_path, client=client, purpose="catalog-confirm",
              operation="catalog-settings", request_body=request, preview=preview)
if preview.get("can_execute") is not True or preview.get("blockers"):
    raise SystemExit("Blocked; do not confirm.")
if input("Type SAVE to approve the exact review: ") != "SAVE":
    raise SystemExit("Not approved.")
review = load_receipt(receipt_path, client=client, purpose="catalog-confirm",
                      operation_mode="configuration")
result = client.catalog_confirm(review["folder"], review["confirmation_id"])
print(json.dumps(result, indent=2))
print(json.dumps(client.catalog_settings(folder, factory_id), indent=2))
```

The same `request` object is the complete REST prepare body; REST confirmation
uses `folder`, `contract_version: 1`, and the returned `confirmation_id`. The
server persists the frozen review and rejects changed revisions, expired/consumed
reviews, or a different authenticated owner. Configuration confirmation returns
`job: null`, not a deployment receipt. No client fallback or automatic retry is
performed. After a timeout or lost acknowledgement, inspect saved settings before
deciding whether a new review is needed; do not assume that the write failed.

### Read-only deployment preflight

`preflight` **complements**, rather than replaces, `health` (API availability) and
`doctor` (API compatibility). It sends exactly one authenticated
**POST `/api/v1/creation/preflight`**, using the same API URL and `X-API-Key`.
It does not run local `az`/`gh`, prepare/start a workflow, provision resources,
save configuration, or fall back to a deployment route. No `--yes` is required.
HTTP 404/405 means a newer API is needed; it is never reported as ready.

Save this minimal request as `preflight-request.json` on the CLI machine,
replacing `bootstrap_config` with the intended bootstrap inputs. Empty inputs
are valid transport JSON, not a claim of deployment readiness:

```json
{"contract_version":1,"orchestrator":"gha","bootstrap_config":{}}
```

```powershell
azurefactory health
azurefactory doctor
azurefactory --timeout 180 preflight --request-json .\preflight-request.json --save-report .\preflight.report.json
# Alternative: assess an existing workflow request without preparing it.
azurefactory --timeout 180 bootstrap workflow prepare --preflight --request-json .\workflow-request.json
```

Cloud checks can exceed 30 seconds, so both preflight forms default to a
180-second request timeout; health, doctor and all other commands retain their
30-second default. An explicit global `--timeout` **before the command**, even
`--timeout 30`, always takes precedence. Preflight never automatically retries.
Timeout or Ctrl+C exits
nonzero without implying readiness and does not create/approve a workflow.

The closed request requires `contract_version: 1` and a `bootstrap_config`
object; `orchestrator` is `gha` (default) or `ado`. Optional fields are `settings`
(object), `scope` (`folder`, `factory_id`, `scale_set_id`, `project_id`) and
`expected_revision`. Existing workflow-prepare fields `operation`,
`execution_mode`, `creation_mode`, `mode`, `approval_mode`, its known alias `approval_scope`,
`authorization_valid_for_seconds` and `bootstrap_public_ipv4` are also accepted
and forwarded, **not interpreted as consent**; approval policy fields are left
to the API and never authorize preflight. Unknown request fields are rejected.

Output preserves the API JSON report, redacting secret fields and the API key:
`contract_version: 1`, `kind: "deployment-preflight"`, `read_only: true`,
`authorization: false`, `status: "ready"|"blocked"|"incomplete"`, boolean `ready`,
`generated_at`, `input_hash`, `source`, `target`, `checks`, `cost_preview` (object
or null), and `limitations`. Checks contain `id`, `category`, `status`
(`passed|warning|blocked|unknown|skipped`), boolean `blocking`, `message`,
`evidence` and `remediation`. The input fingerprint must be 64 lowercase hex
characters and check IDs must be unique. Exit 0 requires a valid ready report
with at least one check and no blocking checks; a nonblocking warning can still
exit 0. Not-ready reports exit
3; malformed/incompatible reports and transport errors exit nonzero.

`--save-report` optionally writes the redacted JSON to a **new** file, including
valid blocked/incomplete reports; it never overwrites a report or receipt.
The alias rejects `--save-receipt` and `--whole-workflow`; `--save-report` on
workflow preparation requires `--preflight`. A preflight report is **not approval,
a spend cap, or a deployment capture/receipt**. Cost previews are advisory, and
readiness is only evidence at the reported time; separate reviewed preparation
and explicit approval remain necessary to deploy.

## Edit a legacy JSON project's configuration, without deployment

`config review` / `config save` are for an **exact legacy project** loaded from
persistent `variables.json`, not an Azure Factory catalog/register root.
Catalog projects must use the existing typed `parameters get` / `prepare` /
`confirm` flow below. Saving configuration does not deploy, promote, commit,
push, sign in or change an Azure account.

`azurefactory schema` calls **GET `/api/v1/schema`**, which describes wizard
fields. The draft loads via **POST `/api/v1/projects/load`** with
`{"aifactory_folder":"C:\\legacy\\aifactory","project_number":"001"}`.
`/api/v1/startup/load` is only a startup hint, not authoritative selection of the
requested project. `/projects/load` rejects catalog roots.

Prepare a private local `changes.json` containing a JSON object of only intended
field replacements, using exact editable field names from the selected
configuration/schema. Omit `--changes-json` to review without replacements.
Private keys, the identity field `project_number_000` and unknown field names
cannot be patched. The changes file is on the **CLI machine**; `--folder` is an
absolute path on the **API host**. Do not export a full state document as a patch.

```powershell
azurefactory config review --folder C:\legacy\aifactory --project-number 001 --changes-json .\changes.json
```

**Stop and review** the patch file's values and the returned metadata:
`review_id` (64 hex characters), `can_save`, scope, `changed_fields`,
`write_variables`, validation issues, warnings and effects. Output intentionally
shows changed **names**, not values, full state, the source reference or rendered
JSON. Review calls API validation and JSON rendering without an export path:
no configuration write, Azure validation or deployment occurs.

Only after a human approves that exact review, run a **separate** save command,
copying its `review_id`:

```powershell
azurefactory config save --folder C:\legacy\aifactory --project-number 001 --changes-json .\changes.json --expected-review <review_id> --yes
```

Use `--snapshot-only` on **both** commands when intentionally saving only the
snapshot, without pipeline variable files. By default, the save also writes
those variable files. It returns `snapshot_path`, `variables_path` and warnings.
Save repeats validation/rendering and requires `can_save` plus the same hash
before submitting the full edited state to `/api/v1/projects/save`.

Persistent JSON loads include an opaque `_json_source` reference containing
the backend's source fingerprint and baseline. Preserve the **entire** returned
state, including this reference and unknown private keys, unmodified except for
the explicit public-field patch. Never interpret, edit, display or reconstruct
the reference. `ConfigurationDraft` does this preservation for you; do not
substitute an older lossy snapshot or an inline-content JSON import. This
guarded workflow blocks any load missing a persistent `_json_source`, even
though the low-level API still supports generic YAML/env configurations.

The review hash binds source state, patch, base URL, scope, validation, warnings,
rendered content and the write choice. It is **not** authentication, a signature,
a backend ETag, cross-user approval or an atomic concurrency guarantee.
The backend separately checks the source fingerprint and refuses changed
source. Changed inputs require another review and human approval. After a
successful save, reload/review before another save. After an ambiguous save
error, inspect the saved result on the host; never blindly retry.

For runnable SDK code using `ConfigurationDraft.load()`, `review()` and
`save()`, see [edit_configuration.py](../install_config_wizard/api-usage-examples/python/edit_configuration.py)
and its [two-phase usage](../install_config_wizard/api-usage-examples/readme.md#edit-a-legacy-json-configuration-with-the-python-sdk).

## Preview then confirm

Confirm/start and generic writes require separate review and `--yes`. Preparation can persist a local draft/preview but never starts a deployment. Read the complete preview before approving. Save the preview receipt and consume it before expiry; expired or blocked previews are never re-prepared silently. All folder paths below are on the API host. New registers normally use a root named `azurefactory`.

```powershell
azurefactory factory create --folder C:\factory --prefix aif-prod --region swedencentral --environment dev --suffix 001 --subscription-id <uuid> --tenant-id <uuid> --orchestrator ado --vnet-cidr 172.16.0.0/18 --max-projects 2 --save-receipt .\factory.receipt.json
azurefactory catalog confirm --receipt .\factory.receipt.json --yes

azurefactory project add --folder C:\factory --factory-id <uuid> --number 002 --display-name "Portal backend" --placement dev=<scale-set-uuid> --save-receipt .\project.receipt.json
azurefactory catalog confirm --receipt .\project.receipt.json --yes

azurefactory factory clone --folder C:\factory --factory-id <uuid> --prefix aif-copy --region swedencentral --include-projects all --save-receipt .\clone.receipt.json
azurefactory scaleset add --folder C:\factory --factory-id <uuid> --environment stage --suffix 001 --subscription-id <uuid> --tenant-id <uuid> --orchestrator ado --vnet-cidr 172.20.0.0/18 --save-receipt .\scaleset.receipt.json
azurefactory project add-placements --folder C:\factory --factory-id <uuid> --project-id <uuid> --placement stage=<scale-set-uuid> --save-receipt .\placement.receipt.json

azurefactory runtime deploy --folder C:\factory --factory-id <uuid> --scale-set-id <uuid> --project-id <uuid> --version-ref main --save-receipt .\deploy.receipt.json
azurefactory runtime confirm --receipt .\deploy.receipt.json --yes
azurefactory runtime poll --folder C:\factory --job-id <job-guid> --poll-timeout 900
azurefactory runtime logs --folder C:\factory --job-id <job-guid> --cursor 0
```

Each confirm/start line is a **separate approval step**, not a script to execute
unattended immediately after prepare. Receipt checksums detect accidental edits;
they are not cryptographic signatures or a substitute for your backend's user
authorization. Store receipts privately. Resource parameter values are omitted
from parameter receipts; the API retains the reviewed protected payload.

AI `factory create` already includes project001; do not add it a second time.
Use `--project-number 003` (and optionally `--project-display-name`) to choose
one different initial project in that same reviewed configuration transaction.
The backend owns defaulting and placements; the CLI never writes the register.
An omitted factory version uses the backend's registered default, while an
explicit supported version is forwarded unchanged. `doctor` and creation check
the live `CatalogPrepare.initial_project` OpenAPI field; older APIs are blocked
before prepare, not silently used with their old creation/default behavior.
An optional `--region-short-name sec` preserves an explicit naming abbreviation
(`region_short_name="sec"` in the SDK); omission delegates naming to the API.
An older API lacking that field is rejected rather than silently ignoring it.

`--initial-project-json` accepts a project object, for example
`{"number":"007","placements":[{"environment":"dev","suffix":"002"}]}`.
Explicit placements are required when the submitted `--scale-set-json` contains
multiple scales for the same environment. Omitted placements select the only
submitted scale in each environment. `--common-only` explicitly opts out of the
initial project; non-AI factory types do not implicitly create an AI project.
`--settings-json` supplies nonsecret editable factory settings in the same review
(for example `{"enableAIFactoryHub":"false","BYO_subnets":"false"}`).
Immutable identity remains in the top-level factory/scale-set flags. The SDK
equivalent is `client.factory_create_prepare(..., initial_project={...}, settings={...})`;
omit `initial_project` for the default or pass `None` for common-only.

For a project in a **new DEV scale set 002**, first run `scaleset add` with
`--environment dev --suffix 002` and an approved non-overlapping CIDR, confirm
that configuration, then refresh `catalog list`. Pass the returned DEV/002 UUID
to `project add --number 003 --placement dev=<new-scale-set-uuid>` when the earlier
existing-scale example already created 002. If running only the new-scale
scenario, 002 is available instead. For existing DEV/001 use that scale set's
UUID. Project numbers are unique across the factory; the two writes are not atomic.

### Latest-successful placement selection

For an existing registered factory, explicitly opt in to server-side selection:

```powershell
azurefactory project add --folder C:\consumer\azurefactory --factory-id <factory-uuid> --number 002 --placement dev=latest-successful --save-receipt .\project.receipt.json
azurefactory project add-placements --folder C:\consumer\azurefactory --factory-id <factory-uuid> --project-id <project-uuid> --placement stage=latest-successful --save-receipt .\placement.receipt.json
```

These are independent prepare-only examples. Read the resolved scale-set UUID
and recorded-success evidence in the preview, then separately approve the
corresponding `catalog confirm`. Selection is performed by the shared API, not
by sorting the catalog on the client. Explicit UUID placements remain supported.
The selector does not create or deploy a scale set, move an existing placement,
or copy a successful project's configuration between environments.

The same request is available through the existing SDK:

```python
preview = client.review_catalog_prepare({
    "contract_version": 1,
    "folder": r"C:\consumer\azurefactory",
    "action": "add-project",
    "factory_id": factory_id,
    "expected_revision": catalog_revision,
    "project": {
        "number": "002",
        "placements": [{"environment": "dev", "scale_set_id": "latest-successful"}],
    },
})
# Inspect the preview and obtain approval before a separate catalog_confirm call.
```

REST uses this identical JSON with `POST /api/v1/factory-catalog/prepare`.
For `add-project-placements`, supply `project_id` and top-level `placements`
instead of `project`. Omission is not an implicit auto-selection request.
Supporting API source is required; older APIs reject the selector, with no
client fallback, upgrade or retry. A saved draft, highest suffix, local script
completion or inventory alone is not eligible success. Selection uses recorded
verified runtime evidence and configured capacity, not a new live Azure probe.
No eligible candidate or ambiguous scope is a blocker, not permission to guess.
Confirmation saves only the exact reviewed placement; it never silently
reselects a newer candidate.

Executable automatic previews advertise `latest-successful-placement-v1` and
include `resolved_placements`: exact target scope, source commit, verified common
deployment job/completion, and evidence hash. CLI output, saved review receipts
and `review_catalog_prepare` reject missing or contradictory resolution data,
including a mismatch with the preview project's UUID placements. Raw
`catalog_prepare` remains transport-oriented. These checks validate the review
contract, not the authenticity of provider receipts or current Azure health.

Catalog placements register where a logical project may live (`project add-placements`).
They do not run update/promote. Catalog runtime deployment is `runtime deploy`
and uses `/api/v1/factory-catalog/prepare` with `action=deploy`, then `runtime
confirm`; it never uses legacy deployment endpoints. Current server blockers are
preserved in CLI output. Common-only, GHA and shared-remote execution require a
supported scoped route, explicit deployment principal and Linux runner, as well
as reviewed bindings, coordination enrollment, published source and exact Azure
identity. Do not infer runtime support from a configuration template's provider
or switch routes to bypass blockers.

Typed parameter editing keeps catalog source and ARM schema revisions explicit:

```powershell
azurefactory parameters prepare --folder C:\factory --factory-id <uuid> --scale-set-id <uuid> --project-id <uuid> --expected-revision <64hex> --schema-revision <64hex> --template <template-name> --parameters-json .\params.json --save-receipt .\params.receipt.json
azurefactory parameters confirm --receipt .\params.receipt.json --yes
```

Read `parameters get` first: use `source_revision` for `--expected-revision`,
the returned `schema_revision`, and exact template/field names from the response.
Send only changed fields in `params.json`; use `--unset` only for an intentional
removal. `--request-json <file>` alternatively accepts a complete typed request,
including the output of the API examples' `parameter_patch.py`.

### Registered Full bootstrap: the same API as MAUI

Full bootstrap is separate from a configuration-only catalog create. Do not
require an existing runner, every future resource group, a separate hub VNet for
integrated mode, or a manually published enrollment binding merely because the
direct catalog-runtime route requires those things. The server's bootstrap
workflow reviews and provisions its own prerequisites. Existing resources still
need matching scope, ownership and permissions.

MAUI's Full bootstrap has two distinct API phases:

| Phase | MAUI API | CLI surface |
| --- | --- | --- |
| Save configuration | `POST /api/v1/creation/prepare`, then `/creation/confirm` | Registered creation launcher (API-backed); generic `request` also exposes these routes |
| Prepare deployment | `POST /api/v1/creation/workflows/prepare` | `bootstrap workflow prepare` |
| Approve exact stage | `POST /api/v1/creation/workflows/start` | `bootstrap workflow start` |
| Observe actual progress | `GET /api/v1/creation/workflows/{id}` | `bootstrap workflow status` |
| Review next stage | `POST /api/v1/creation/workflows/{id}/prepare-next` | `bootstrap workflow next` |

The existing `factory create` / `catalog confirm` tutorial saves a catalog draft
through the catalog API. It does not supply all Full bootstrap inputs or prove
that prerequisites have already been created. Do not recreate an occupied
factory to change routes: read its saved scope and use the compatible backend
workflow with an explicitly reviewed bootstrap configuration.

With matching updated API and accelerator helpers, a new registered GitHub factory
reviews and creates missing `Dev`, `Stage` and `Prod` environments, binding only its
initial Dev deployment to `Dev`. Creating the other two environments does not
deploy Stage/Prod or create subscriptions. Existing custom/hashed environment
bindings and protection rules are retained, not migrated. An unbound historical
hashed environment or conflicting capitalization requires explicit reconciliation.

The interactive registered Full bootstrap launcher asks for an optional existing
Entra team-group object ID before configuration preparation. Leave it blank to
find/create the named team during bootstrap, or set `AIF_TEAM_GROUP_ID` upfront
to reuse a group without membership changes. Non-interactive requests are not
prompted. The current API still requires `team_group_name` and
`team_member_email` in its Full form, even with a supplied group ID; do not invent
values or silently drop required API fields.

For deployment, `workflow-request.json` contains `contract_version: 1`,
`operation: "create-factory"`, `execution_mode: "privileged-bootstrap"`,
`creation_mode: "full-bootstrap"`, the exact saved `scope` (`folder`, `factory_id`,
`scale_set_id`, optional `project_id`), `expected_revision` from **`catalog list`'s
`revision`**, and `bootstrap_config`. Read the API's capabilities and schema for
the complete bootstrap configuration; do not substitute enrollment options.
Set `bootstrap_config.coordination_mode` explicitly to `"single-writer"` for a
reviewed private-repository, no-Blob-coordination deployment. Do not silently
migrate an existing Blob-bound factory or infer support from the client version.

```powershell
azurefactory bootstrap capabilities
azurefactory bootstrap workflow prepare --request-json .\workflow-request.json --save-receipt .\stage-01.receipt.json
# Review the exact server-returned stage, scope, effects and blockers first.
azurefactory bootstrap workflow start --receipt .\stage-01.receipt.json --yes
azurefactory bootstrap workflow status --folder C:\repos\consumer\azurefactory --workflow-id <returned-workflow-uuid>
# Only when status requires_review is true, prepare the next stage:
azurefactory bootstrap workflow next --folder C:\repos\consumer\azurefactory --workflow-id <returned-workflow-uuid> --save-receipt .\stage-02.receipt.json
```

These commands remain API clients: do not invoke local Azure provisioning as a
fallback. The server determines the stage order and can include repository
initialization, identity/RG/network foundation, runner registration, connection,
publication and common/project deployment. Which stages are supported depends
on the running API and reviewed source. A queued job or a successful individual
stage is not proof that the entire factory is deployed.

Per-stage approval remains the default. With a compatible API, opt in to one
bounded Full bootstrap approval instead:

```powershell
azurefactory bootstrap workflow prepare --whole-workflow --request-json .\workflow-request.json --save-receipt .\workflow.receipt.json
# Review review.workflow_authorization, all stage effects and review.cost_preview.
azurefactory bootstrap workflow start --receipt .\workflow.receipt.json --yes
azurefactory bootstrap workflow status --folder C:\repos\consumer\azurefactory --workflow-id <returned-workflow-uuid>
```

The API must return the `bounded-full-bootstrap-v1` authorization for the exact
saved scope and source revision. The CLI validates its content hash and expiry
before saving or starting the receipt; it does not silently fall back to
per-stage approval or run a client loop approving future receipts. The server
owns continuation within the approved scope. Changed inputs, source or scope,
expired approval, and failed or uncertain stages remain stops requiring review
or reconciliation.

`review.cost_preview` inventories the saved factory's selected workloads and
infrastructure. It is advisory and outside the backend authorization hash.
Missing prices are reported explicitly; an unavailable or partial estimate is
not a complete factory total and does not block deployment.

If the API reports a safely resumable boundary, `bootstrap workflow continue`
accepts the original `--folder`, `--workflow-id` and `--authorization-hash`.
This resumes already-consumed approval only; it is not a retry command for a
failed or in-flight stage. The separate advanced enrollment convenience wrapper
below authorizes only enrollment and binding publication, not Full bootstrap.

### Launcher-based bootstrap API

The older `bootstrap prepare/start/status` family targets
`/api/v1/creation/bootstrap/*`, not MAUI's registered staged workflow above.
Do not switch to it to bypass a blocked registered stage.

MAUI's **Copy common details** uses the same API as
`azurefactory bootstrap config --state-json .\wizard-state.json --mapping-mode common-details`.
That explicit mode returns a **partial** object containing account, team and
region defaults; merge only those returned keys into a separate new-factory
draft. It does not copy the existing destination, project, network or resource
customizations. Omit the mode for the unchanged strict conversion behavior.
Capabilities, mapping and preview responses separate neutral `notes` from observed
`warnings` and blocking failures. VPN client installation is not a connectivity
test, and existing host networking is left unchanged.

```powershell
azurefactory bootstrap capabilities
azurefactory bootstrap prepare --launcher ADO-create-new-aifactory-scaleset.sh --orchestrator ado --config-json .\bootstrap-config.json --save-receipt .\bootstrap.receipt.json
azurefactory bootstrap start --receipt .\bootstrap.receipt.json --yes --wait --poll-timeout 1800
azurefactory bootstrap status --job-id <job-guid> --wait --poll-timeout 1800
```

`--config-json` accepts the inner `BootstrapConfig` object. To consume the
examples' fully rendered GHA/ADO request, use `bootstrap prepare --request-json
<rendered-file> --save-receipt <new-file>` instead. Full bootstrap can create
billable common infrastructure and the initial project, establish identities,
create repositories, commit/push and dispatch pipelines. It is not the same
operation as configuration-only factory creation.

## Enroll a registered factory / scale set

This is the separate advanced enrollment route, not the normal prerequisite
sequence to impose on API-managed Full bootstrap.

First create/add the exact target through `factory create` / `scaleset add` and
the separate `catalog confirm` flow. Refresh `catalog list` and select its UUIDs.
Enrollment requires a **schema-2 consumer repository containing
`azurefactory/register.json`**; an inactive starter, legacy `aifactory` folder,
subscription from the active `az` context, or `.env` defaults are not substitutes.
Neither `plan` nor `ensure` needs a running local API or API key. `plan` makes
read-only Azure/provider calls; `ensure` can create billable/additional resources.
Use an already authenticated, explicitly scoped Azure CLI profile and, for GHA,
GitHub CLI authentication. The core never signs in or switches subscriptions.

Create a non-secret `enrollment-options.json` using the core's closed options
schema (`bootstrap/lib/factory_enrollment.py`, also bundled in installed packages):

```json
{
  "repository": "https://github.com/example/consumer",
  "ref": "refs/heads/main",
  "shared_remote": false,
  "writer_id": "example-stage",
  "auth_namespace": "example-stage",
  "runner": {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04"},
  "resource_group_ids": ["/subscriptions/<subscription-uuid>/resourceGroups/<approved-rg>"],
  "common_dependency_ids": [],
  "deployment_roles": [
    {"scope": "/subscriptions/<subscription-uuid>/resourceGroups/<approved-rg>",
     "role_definition_id": "<approved-role-definition-uuid>"}
  ],
  "public_network_access": "Disabled"
}
```

Replace placeholders with approved, exact values. For ADO use
`https://dev.azure.com/<organization>/<project>/_git/<repository>` and explicitly
set `ado_tenant_id` to the **ADO organization's tenant**, not necessarily the
Azure resource tenant. Self-hosted runner objects are
`{"kind":"self-hosted","os":"linux","pool":"<pool>","agent_name":"<optional-name>"}`
for ADO or `{"kind":"self-hosted","os":"linux","labels":["self-hosted","linux","<label>"]}`
for GHA. Selecting a runner does not install/register one.

Only an administrator who has actually established exclusive-writer governance
may pass `--acknowledge-exclusive-writer-governance`. All writers, including other
tools/operators, must enforce the physical lease protocol and serialize enrollment
resource provisioning. Merely creating blobs
does not establish this governance. The flag is never supplied automatically and
must match on both separately approved commands:

```powershell
azurefactory enrollment plan --consumer-root <consumer-repo> --factory-id <factory-uuid> --scale-set-id <scale-set-uuid> --environment stage --options .\enrollment-options.json --expected-orchestrator gha --acknowledge-exclusive-writer-governance --save-plan .\stage.enrollment-plan.json
# STOP: review the complete plan, actions, role scopes, blockers, path and hashes.
azurefactory enrollment ensure --plan .\stage.enrollment-plan.json --yes --acknowledge-exclusive-writer-governance --save-result .\stage.enrollment-result.json
```

`ensure --plan` reloads the registered target and verifies the artifact digest,
request/path/register-reference hashes, review digest, explicit selections and
governance choice. The core then rechecks current cloud/provider state against
the original `plan_hash` before any mutation. You may repeat scope/options flags
to assert consistency; contradictions fail closed. Alternatively, pass all
plan scope flags to `ensure --expected-plan <approved-plan_hash> --yes`; saving
a publication result requires the saved-plan form. Plans/results are bounded,
non-secret local JSON artifacts, created exclusively without overwriting files.
Their checksums detect edits, not malicious forgery: store them privately and
review them separately. No automatic re-plan, approval, retries or rollback.

Without governance acknowledgment, planning reports the missing prerequisite and
`ensure` refuses before any write. ARM provisioning uses documented create-or-update
operations with fresh existence checks, conflict checks and verification; these
are not atomic create-only REST operations. The operator's serialized-provisioning
attestation is required. Custom
resources are explicit: `identity_id` means strictly reuse; otherwise an absent
UAMI can be created, optionally using `identity_name` /
`identity_resource_group_id`. Coordination storage defaults are derived from the
**registered** tenant/subscription. Use `coordination_account_id` for existing
custom storage, or `coordination_resource_group_id` to choose its group.
`container` / `coordination_blob` are optional coordinates. Missing groups need
`create_resource_group_ids` plus `approved_group_creation_scope` equal to the
selected subscription ARM scope. Existing unrelated/unowned or contradictory
resources fail; they are not adopted, repaired or deleted.

Role grants require exact approved RG scopes and explicit role definitions.
The core provisions/reuses UAMI federation (ADO federated service connection or
GHA environment OIDC), conditional lock blobs and append-only coordination
enrollment. It does **not** create Linux VMs, private endpoints/network routes,
register agents, authorize every pipeline, publish a binding, or deploy workloads.
For GHA, pre-create the named GitHub Environment with its intended protection
rules. GitHub's environment upsert API has no documented atomic create-only
operation; enrollment will not risk resetting a concurrently configured environment.
Disabled storage networking requires working preexisting private connectivity.
Provider/custom OIDC or live-rights limitations remain visible blockers.

### Publish only the reviewed candidate

`ensure` returns a closed `binding_candidate`, not an API request or deployed
resource. Prepare it using the saved result and the current API catalog
`source_revision`. The local API must access the **same** consumer repository;
the CLI derives its `folder` as `<consumer-root>\azurefactory`.

```powershell
azurefactory catalog list --folder <consumer-repo>\azurefactory
azurefactory enrollment prepare-binding --result .\stage.enrollment-result.json --expected-revision <catalog-list-revision> --save-receipt .\stage.binding.receipt.json
# STOP: independently review the exact candidate, factory, revision and API preview.
azurefactory catalog confirm --receipt .\stage.binding.receipt.json --yes
# Equivalent binding-only confirmation, instead of the preceding command:
# azurefactory enrollment publish --receipt .\stage.binding.receipt.json --yes
```

Preparation is `/api/v1/factory-catalog/prepare` with
`action=configure-binding`; publication is the existing catalog confirm API.
The receipt must acknowledge the exact binding, factory and source revision;
confirmation enforces the server's protected payload/concurrency checks.
The CLI never writes `register.json` or silently rewrites a binding. Enrollment
readiness and binding publication are **not** actual deployed-resource readiness;
runtime preparation must still verify live state.

### Convenience: plan and publish with one bounded approval

The source CLI also provides `enrollment plan-and-publish`. The published
**v0.47.1 wizard/release binaries are not updated by this source change**.
Use a CLI installed from this updated checkout and a compatible local catalog API
that can access the same schema-2 consumer. This is enrollment and binding
publication, **not full bootstrap or runtime deployment**.

For a **new** binding, omit all Blob-specific options (including
`public_network_access` from the example above) to default this convenience flow
to `single-writer`. It uses private provider Git state, no Blob account/data RBAC.
An existing binding's mode or explicit Blob options are preserved; the original
`plan` / `ensure` commands keep their existing defaults. A single-writer repository
must be private. The explicit governance attestation covers serialized provisioning,
one designated repository writer and shared-hub changes by other repositories;
it provides no cross-repository exclusion.

The saved factory setting must already match that mode. An absent saved
`coordination_mode` means Blob in the API, not permission to migrate. The wrapper
rejects a mismatch before planning or provisioning; configure the intended
mode through the reviewed catalog API first. It never edits the register to
make publication succeed.

```powershell
# Read-only review, including informational cost drivers; exits 3 (approval required).
azurefactory enrollment plan-and-publish --consumer-root C:\repos\consumer --factory-id <factory-uuid> --scale-set-id <scale-set-uuid> --environment stage --options .\enrollment-options.json --artifact-dir .\stage-review --acknowledge-exclusive-writer-governance

# One explicit approval of the selected scopes/roles, creation and publication.
azurefactory enrollment plan-and-publish --consumer-root C:\repos\consumer --factory-id <factory-uuid> --scale-set-id <scale-set-uuid> --environment stage --options .\enrollment-options.json --artifact-dir .\stage-publish --expected-orchestrator gha --acknowledge-exclusive-writer-governance --yes
```

The artifact directory must not exist and its parent must exist. Without
`create_resource_group_ids` in the **options JSON**, the wrapper derives creation
permission only for the exact selected writable factory RGs and an explicitly
selected new identity RG, excluding dependencies and other registered owners.
These writable selections declare ownership of missing groups; existing factory
groups still require matching factory/scaleset ownership tags. No arbitrary shared
dependency, default shared coordination RG, reusable identity RG or subscription
role grant is silently authorized. Use `"create_resource_group_ids": []` to disable
automatic RG creation. Explicit creation options and explicit RG role definitions
remain subject to the original core validation and live rights/deny checks.
New UAMI creation is already supported by the core; `identity_id` still means
strict reuse, never a create fallback.
Before planning, registered `owned_resource_ids` are also checked across all
factories and scale sets, including those with no binding and no existing Azure
group. Missing resources do not make another registered owner's scope available.

The wrapper persists effective options, the integrity-bound enrollment plan/result,
cost preview, exact API binding receipt, pre-mutation intent files and final outcome.
It prints the cost preview and plan to stderr **before resource writes** and emits
one final result on stdout. Costs are **unpriced informational drivers**, based on
the selected region, coordination mode, requested storage SKU and runner. No price
service or dollar estimate is required; workload services, usage, AI tokens,
discounts and existing/shared infrastructure costs are explicitly excluded and
must be reviewed with effective deployment parameters before runtime deployment.
Pricing links are included; missing pricing never blocks enrollment.

Before ensure, the wrapper reads the current catalog revision (optionally pinned
with `--expected-revision`). It invokes the unchanged reviewed ensure, then prepares
and validates the exact candidate/receipt before confirming that receipt. Cloud
state/register changes, governance/ownership failures, absent GitHub Environments,
private routing failures, repository claims and API blockers remain real stops,
not success fallbacks. GitHub Environments must be provisioned separately;
enrollment may create an absent ADO federated service connection but does not
authorize all pipelines, create/register runners or install networking.

There is **no automatic mutation retry, replan or rollback**. Partial or uncertain
work is saved; inspect artifacts, provider claims and live state before retrying.
After a completed ensure and blocked publication, use the saved `result.json` with
the separate `prepare-binding` / `publish` flow above, refreshing the catalog
revision as needed. An intent without its corresponding result means work may
have happened: do not blindly replay it. `published: true` only means the API
accepted binding publication; `runtime_ready` remains false.

### Equivalent Bash entrypoints and runner helpers

All four routes dispatch `enroll` **before** legacy/layout guards and pin the
provider against the exact core-loaded request:

```bash
bash bootstrap/ADO-azurefactory.sh enroll plan --help
bash bootstrap/GHA-azurefactory.sh enroll plan --help
bash bootstrap/ADO-create-new-aifactory-scaleset.sh enroll ensure --help
bash bootstrap/GHA-create-new-aifactory-scaleset.sh enroll ensure --help
# Each accepts the same explicit core scope/options and optional governance flag:
bash bootstrap/GHA-create-new-aifactory-scaleset.sh enroll plan --consumer-root <consumer-repo> --factory-id <factory-uuid> --scale-set-id <scale-set-uuid> --environment stage --options enrollment-options.json --acknowledge-exclusive-writer-governance
# After a separate review:
bash bootstrap/GHA-create-new-aifactory-scaleset.sh enroll ensure --consumer-root <consumer-repo> --factory-id <factory-uuid> --scale-set-id <scale-set-uuid> --environment stage --options enrollment-options.json --expected-plan <approved-plan_hash> --yes --acknowledge-exclusive-writer-governance
```

Copied control bundles use the same commands without the `bootstrap/` prefix.
`ALL-create-new-aifactory-scaleset.sh --orchestrator ado|gha enroll ...` dispatches
to the corresponding pinned route. Bash does not use CLI saved-plan envelopes;
its `--expected-plan` consumes the separately reviewed core `plan_hash`.
Registered roots still reject all raw legacy create/update options.

The copied/snapshotted control bundle includes `factory_enrollment.py`, its thin
provider adapter, `runner-prerequisites.ps1`, `runner-prerequisites.sh`,
`runner-registration.ps1` and `runner-registration.sh`. Runner registration is
separate from the Azure managed identity: an ADO/GHA agent credential is **not**
the UAMI client/principal identity. Review each runner helper's help and existing
agent state; do not reset/reconfigure agents or pass credentials in options JSON.

**Remaining boundary:** ordinary source/legacy bootstrap creation still follows
its existing route until the API has registered the target. Enrollment cannot
automatically establish a lease for an unregistered legacy destination. Register
first, explicitly enroll the selected target, then prepare/confirm its binding.

### Distributions

Wheel and sdist builds copy the canonical `bootstrap/lib/factory_enrollment.py`
into generated `azurefactory._vendor.factory_enrollment`; no manually maintained
second core exists. Installed CLI packages work independently of repository/cwd.
Source/editable use resolves only anchored repository/copied-template paths, not
the process working directory. `setup.py` travels with copied CLI templates.
No runtime Python dependencies are added.

## Legacy project deployment

```powershell
azurefactory legacy plan --folder C:\legacy --project-number 001 --source-env dev --target-env dev --operation update
azurefactory legacy plan --folder C:\legacy --project-number 001 --source-env dev --target-env stage --operation deploy --patch
azurefactory legacy prepare --folder C:\legacy --draft-id <draft-guid> --save-receipt .\legacy.receipt.json      # preserves saved patch choice
# Alternative when intentionally changing the saved patch choice:
azurefactory legacy prepare --folder C:\legacy --draft-id <draft-guid> --no-patch --save-receipt .\legacy-no-patch.receipt.json
azurefactory legacy start --receipt .\legacy.receipt.json --yes --wait --poll-timeout 900
azurefactory legacy status --folder C:\legacy --job-id <job-guid> --wait --poll-timeout 900
```

Legacy update/promote is separate from catalog placement/runtime. It targets only legacy aifactory roots; catalog roots or nested catalog factory paths must use catalog commands and must not be sent to `/api/v1/operations/project-deployments/*`. Legacy `update` requires same source/target environment; legacy `deploy` promotes to a later environment. Acknowledgements must be contract version 2. `legacy prepare` preserves the saved patch choice unless `--patch` or `--no-patch` is explicit. `submitted` means the local script exited zero, not that provider completion or Azure deployment was verified.

Draft, start and terminal results include an additive `execution_result`:

```json
{"contract_version":1,"completion_scope":"local-script","local_terminal":true,"deployment_verified":false}
```

`local_terminal` is true for `submitted`, `failed` and `interrupted`, and false
for `draft`, `queued` and `running`. It describes the recorded local job boundary,
not proof that all child processes or remote work stopped. `legacy --wait` waits
only for that local boundary. Without `--wait`, queued/running results remain
nonterminal. Neither form nor exit code 0 proves deployed resources.

The SDK's public `legacy_execution_result(response)` and legacy client methods
conservatively interpret older status-only servers using the same fields; this
is a client interpretation, not new server/provider evidence. Present but
contradictory metadata, unknown states or legacy `succeeded` fail closed.
The version-2 `deployment_contract` still binds the reviewed draft, patch and
source version; a review receipt authorizes neither itself nor a retry and is
not a signed approval or deployment-success receipt. Obtain separate exact
provider run/effect evidence before reporting deployment success.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Command succeeded, or a nonterminal status was read successfully. |
| 1 | HTTP/API/transport failure; inspect the structured status and details. |
| 2 | Usage/configuration/client-side safety failure. |
| 3 | Preview or receipt is blocked/expired/not executable. |
| 4 | Request or polling timeout; the server operation is not cancelled. |
| 5 | API returned failed/interrupted/malformed/unknown status or contract mismatch. |
| 6 | Missing API key for secured endpoint. |
| 130 | Interrupted locally. |

## SDK

The public `ConfigurationDraft` helper implements the guarded JSON legacy flow
above. Its `load(client, folder, project_number, changes=...)` retains the full
state in memory; `review(write_variables=True)` returns safe review metadata;
`save(expected_review, write_variables=True)` requires the previously approved
hash. Your application must obtain explicit consent before calling `save`.

For integrations that manage their own preservation and approval lifecycle,
these low-level methods remain available:

| SDK method | Route and consequence |
|---|---|
| `configuration_load(folder, project_number)` | POST `/api/v1/projects/load`; exact legacy project, full state including private metadata |
| `configuration_import(path, format="json")` | POST `/api/v1/import`; persistent **API-host path only**, not an upload/inline content |
| `configuration_validate(state)` | POST `/api/v1/validation`; offline validation, not Azure/deployment preflight |
| `configuration_export(state, format="json", path=None)` | POST `/api/v1/export`; returns rendered content/path/warnings; **supplying a path writes on the API host** |
| `configuration_save(state, write_variables=True)` | POST `/api/v1/projects/save`; writes configuration, requires caller-managed approval |

Pass full preserved state through low-level validation/export/save; never log
that state or rendered content by default. Generic YAML/env use is low-level
only, outside the JSON-origin `ConfigurationDraft` guards. SDK/API-key
authentication does not establish the operator's consent.

Existing catalog deployment integration:

```python
from azurefactory import AzureFactoryClient, validate_preview
from azurefactory.review import load_receipt, write_receipt

client = AzureFactoryClient()  # reads AIFACTORY_API_URL and AIFACTORY_API_KEY
catalog = client.catalog_list(r"C:\factory")
portal_project = client.catalog_parameters(r"C:\factory", "<factory-id>", "<scale-set-id>", "<portal-project-id>")
backend_project = client.catalog_parameters(r"C:\factory", "<factory-id>", "<scale-set-id>", "<backend-project-id>")

body = {
    "folder": r"C:\factory",
    "contract_version": 1,
    "action": "deploy",
    "factory_id": "<factory-id>",
    "scale_set_id": "<scale-set-id>",
    "project_id": "<portal-project-id>",
    "version_ref": "main",
}
preview = client.catalog_prepare(body)
validate_preview(preview)
write_receipt(
    r".\deploy.receipt.json",
    client=client,
    purpose="catalog-confirm",
    operation="runtime-deploy",
    request_body=body,
    preview=preview,
)
# In a separate, authenticated approval handler after explicit human consent:
def approve_deployment(approved_receipt_path):
    receipt = load_receipt(
        approved_receipt_path, client=client, purpose="catalog-confirm",
        operation_mode="runtime",
    )
    return client.catalog_confirm(receipt["folder"], receipt["confirmation_id"])
```

The SDK's direct HTTP methods do not obtain human consent for you. Your backend
must authorize the caller, bind the approved receipt to that caller and the
selected scope, and only then invoke the approval handler. Never put the API key
in browser code. The bundled sidecar is a local worker, not a public multi-tenant
service. Successful launcher/submission status does not prove the downstream
pipeline or Azure deployment succeeded. A timeout or Ctrl+C stops local waiting
and does not cancel the server operation; inspect its recorded job before retrying.

`doctor` checks supported routes, model bindings and contract versions. With
`--local-openapi` it also reports conservative semantic differences; it is not
a guarantee of identical backend behavior or a replacement for coordinated
Tkinter/MAUI releases. Use `python -m azurefactory` if the console script is not
on PATH.

Use `client.request("GET", "/api/v1/...")` for future read resources. Generic CLI writes require `request POST ... --write --yes`.

### Monitoring: canonical reports, not collector jobs

An already-running authorized local API is required. These commands reuse its
canonical calculations and `X-API-Key`; they do not deploy resources, authenticate
to Azure, start a collector, ingest telemetry or upload artifacts.

```powershell
azurefactory monitoring catalog
azurefactory monitoring summary --source sample --factory "Demo AI Factory" --scaleset demo-east --project 001 --environment dev --days 7
azurefactory monitoring report --report showback --source sample --project 001 --days 7
azurefactory monitoring export --report agent-value --source sample --format csv
azurefactory monitoring report --request .\reviewed-monitoring-request.json
```

All organizational filters default to `All`; combine `--factory`, `--scaleset`,
`--project` and `--environment` for an exact compound identity. `001` remains a
string. Sample mode is the default only for generated requests. Live requests
must explicitly supply `"source": "live"` and their observation evidence in the
canonical request file; `--source live` alone cannot collect anything. Output is
the API JSON response with provenance for reports; the CLI writes no files.
Export defaults to the API's CSV response; use
`monitoring export --report showback --format json` for the full canonical JSON
report. Missing evidence is not replaced by a sample.
The live request uses `"rows": [...]` (not `observations`) and only the four
organizational filter keys; `days` controls sample generation, not live time
filtering. Optional `--start-date YYYY-MM-DD --end-date YYYY-MM-DD` (or
`start_date` / `end_date` in a request file) explicitly bound summary, report and
CSV output to 1-90 inclusive UTC calendar days. Both dates are required together.
Dated aggregate intervals must fit entirely inside the window; partial overlaps
and unusable dates are rejected, never prorated or silently included. Omit both
dates to retain the existing unbounded evidence behavior. The API's export body
has no `format` field.
Generated CLI requests explicitly default to **7 sample days**; the API's own
omitted-days default remains 30. Use `--days 1` when comparing one-day sample
values with the reviewed native fixture (whose historical timestamps are fixed).

SDK equivalents are `client.monitoring_catalog()`,
`client.monitoring_summary(request)`, `client.monitoring_report(request)` and
`client.monitoring_export(request)`.
Summary returns `aifactory.monitoring-summary.v1`: six sections with the same
metric/provenance/qualification objects as detailed reports, shared scope/source/
window/coverage, and observation rows once. It omits `report_id` from its request
and does not sum overlapping report sections. The CLI prints summary JSON;
select a detailed report for CSV.
Samples expose their frozen clock rather than implying today's activity. For
the current seven-day scenario, an explicit enclosing window is
`--start-date 2026-09-09 --end-date 2026-09-16`.
The six IDs remain `agent-value`, `showback`, `foundry-tokens`, `foundry-usage`,
`quality-reliability`, `security-governance`. Modeled benefit, quality-qualified
outcomes and verified realized value are distinct; token volume is not value.
Actual/amortized bills and estimates remain separate.

#### Saved evidence: read, summary and report

Use a **matching API release** with `POST /api/v1/monitoring/evidence/read`
(`aifactory.monitoring-evidence.v1`) and the canonical summary/report reducers.
These are the shared backend contracts used by pinkAPI/MAUI, not a copied backend
or a new collection implementation. Updating the CLI alone does not update an
older running API. The installed consumer `azurefactory.sh` wrapper exposes these
same package commands.

Select the registered UUIDs from `catalog list`, not factory labels, scale
suffixes or project numbers. `--folder` is an existing register on the API host;
the host enforces the current authenticated identity and authorized placements.
Omitted UUID selectors include all authorized placements in that folder.

```powershell
azurefactory monitoring saved read --folder $env:FACTORY_FOLDER --factory-id $env:FACTORY_ID
azurefactory monitoring saved summary --folder $env:FACTORY_FOLDER `
  --factory-id $env:FACTORY_ID --scale-set-id $env:SCALE_SET_ID --project-id $env:PROJECT_ID `
  --start-date 2026-09-01 --end-date 2026-09-22
azurefactory monitoring saved report --folder $env:FACTORY_FOLDER `
  --factory-id $env:FACTORY_ID --report showback `
  --start-date 2026-09-01 --end-date 2026-09-22
```

`read` prints the complete canonical evidence envelope: `status`, `rows`,
`scopes`, `snapshots`, `native_bindings`, `window`, `warnings`, `source_errors`
and contract. Saved summary/report first read that envelope, then send only
available `rows`, `native_bindings`, `"source": "live"` and the **unchanged**
date bounds to the existing reducer (plus `report_id` for a report). Output is
`{"status": ..., "evidence": <unchanged envelope>, "summary": <API response>}`
or the same wrapper with `report`. Original row timestamps, snapshot source,
collection/save times, observed windows and source errors remain intact;
`saved_at` and response generation are never substituted for observation time.

`absent` exits 0 as an explicit empty discovery, with a null summary/report and
no reducer call: it is **not a healthy zero**. `incompatible`/`unavailable` exit 5
and also skip reduction. Partial source failures with surviving data remain in
JSON and visible stderr warnings; they do not hide the successful evidence.
HTTP/contract failures are nonzero, with no retry or fallback. No saved command
collects, imports, saves, runs automation/report jobs, uploads or writes files.
Missing evidence never falls back to live Azure collection or sample data.
The existing explicit sample and supplied-row commands remain unchanged.

SDK equivalents (the context accepts only `folder`, optional `factory_id`,
`scale_set_id`, `project_id`, `start_date`, `end_date`):

```python
context = {"folder": factory_folder, "factory_id": factory_id,
           "start_date": "2026-09-01", "end_date": "2026-09-22"}
evidence = client.monitoring_evidence_read(context)
summary = client.monitoring_saved_summary(context)
report = client.monitoring_saved_report(context, report_id="showback")
```

Each SDK pipeline preserves nonavailable states in its returned wrapper; callers
must inspect `status`. Date bounds are paired inclusive UTC dates (1-90 days);
omitting both keeps the server's unbounded saved-source selection, not a live
lookback or a client-generated observation clock.

```powershell
azurefactory request GET /api/v1/schema
azurefactory request POST /api/v1/future/resource --body-json .\payload.json --write --yes
```