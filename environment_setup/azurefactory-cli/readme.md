# azurefactory-cli

Stdlib-only Python SDK and CLI for the local AzureFactory configuration API, plus reviewed Azure/provider enrollment. Catalog/configuration commands target the Tkinter/MAUI Python server API; `enrollment plan|ensure` instead use the canonical local enrollment core and explicit Azure/provider authentication. Start with the [runnable API scenarios](../install_config_wizard/api-usage-examples/readme.md) for complete prerequisites, exact UUID selection and central-cloud-team integration guidance.

## Install

```powershell
cd <repo>\environment_setup\azurefactory-cli
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:AIFACTORY_API_URL = "http://127.0.0.1:64979"   # or omit for http://127.0.0.1:8765
$env:AIFACTORY_API_KEY = "<per-process local API key>"
```

The API key is sent only as `X-API-Key`; the CLI does not log or store it. Plain `http` is accepted only for loopback hosts. `https` is also accepted. Redirects, URL credentials and absolute endpoint escapes are rejected.

Server reference: canonical Tkinter API source `<tkinter-repository>\src\api.py`; MAUI's
`build-windows.ps1` invokes Tkinter's `build-api.ps1` and packages the resulting
`aifactory-api.exe`, not a separate REST implementation. The packaged host uses
a random loopback port and per-process key. This source/build relationship does
not certify a running binary: the example port 64979 was not listening during
this update. Obtain the actual URL/key from your operator and run `doctor`
against that host. Local API authentication is distinct from both the Azure CLI
identity on the host and a user's approval to save or deploy.

## Core commands

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
azurefactory factory create --folder C:\factory --prefix aif-prod --region swedencentral --environment dev --suffix 001 --subscription-id <uuid> --tenant-id <uuid> --orchestrator ado --vnet-cidr 172.16.0.0/18 --save-receipt .\factory.receipt.json
azurefactory catalog confirm --receipt .\factory.receipt.json --yes

azurefactory project add --folder C:\factory --factory-id <uuid> --number 001 --display-name "Portal backend" --placement dev=<scale-set-uuid> --save-receipt .\project.receipt.json
azurefactory catalog confirm --receipt .\project.receipt.json --yes

azurefactory factory clone --folder C:\factory --factory-id <uuid> --prefix aif-copy --region swedencentral --include-projects all --save-receipt .\clone.receipt.json
azurefactory scaleset add --folder C:\factory --factory-id <uuid> --environment stage --suffix 002 --subscription-id <uuid> --tenant-id <uuid> --orchestrator ado --vnet-cidr 172.20.0.0/18 --save-receipt .\scaleset.receipt.json
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

For a project in a **new DEV scale set 002**, first run `scaleset add` with
`--environment dev --suffix 002` and an approved non-overlapping CIDR, confirm
that configuration, then refresh `catalog list`. Pass the returned DEV/002 UUID
to `project add --number 002 --placement dev=<new-scale-set-uuid>`. For an existing
DEV/001 use that scale set's UUID instead. The two writes are not atomic.

Catalog placements register where a logical project may live (`project add-placements`). They do not run update/promote. Catalog runtime deployment is `runtime deploy` and uses `/api/v1/factory-catalog/prepare` with `action=deploy`, then `runtime confirm`; it never uses legacy deployment endpoints. Current server runtime blockers are preserved in CLI output, including common-only deploy unsupported, GHA atomic dispatch missing, and shared-remote deploy unsupported. Some configuration templates default to GHA, but deployment still surfaces these blockers instead of switching route.

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

Full bootstrap is separate from catalog create and includes common infrastructure plus the initial project:

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

First create/add the exact target through `factory create` / `scaleset add` and
the separate `catalog confirm` flow. Refresh `catalog list` and select its UUIDs.
Enrollment requires a **schema-2 consumer repository containing
`azurefactory/register.json`**; an inactive starter, legacy `aifactory` folder,
subscription from the active `az` context, or `.env` defaults are not substitutes.
Neither enrollment command needs a running local API or API key. `plan` makes
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
azurefactory enrollment prepare-binding --result .\stage.enrollment-result.json --expected-revision <catalog-source-revision> --save-receipt .\stage.binding.receipt.json
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

Legacy update/promote is separate from catalog placement/runtime. It targets only legacy aifactory roots; catalog roots or nested catalog factory paths must use catalog commands and must not be sent to `/api/v1/operations/project-deployments/*`. Legacy `update` requires same source/target environment; legacy `deploy` promotes to a later environment. Acknowledgements must be contract version 2. `legacy prepare` preserves the saved patch choice unless `--patch` or `--no-patch` is explicit. `submitted` means the local pipeline was submitted, not that Azure deployment completed.

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

```powershell
azurefactory request GET /api/v1/schema
azurefactory request POST /api/v1/future/resource --body-json .\payload.json --write --yes
```