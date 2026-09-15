# azurefactory-cli

Stdlib-only Python SDK and CLI for the local AzureFactory configuration API. It targets the Tkinter/MAUI Python server API, not Azure directly. Start with the [runnable API scenarios](../install_config_wizard/api-usage-examples/readme.md) for complete prerequisites, exact UUID selection and central-cloud-team integration guidance.

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

Server reference paths used by this implementation: canonical Tkinter API source `<tkinter-admin-ux>\src\api.py`; MAUI bundles the same Python server through `build-api.ps1` with a random loopback port and per-process key. Local API authentication is distinct from the Azure CLI identity on the host.

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