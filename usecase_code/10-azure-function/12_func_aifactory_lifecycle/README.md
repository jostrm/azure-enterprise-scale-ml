# AI Factory lifecycle Function

An Azure Functions Python **Consumer → L1 ESAF SDK → L2 Factory API**. Set **`AIF_BACKEND=sdk`** to run each
scenario through **one facade method**, with one Function scope approval. The thin Python SDK sends one approved
`POST /api/v1/esaf/<scenario>`. L2 owns configuration, live reviews, confirmations, enrollment, deletion
authorization, pipeline dispatch and bounded retries; neither the Function nor L1 duplicates that orchestration.

| # | Function route segment | SDK method | Result |
|---|---|---|---|
| 1 | `init-factory` | `esaf.init_factory(creation_request=..., session=...)` | Save a new factory and start its server-owned full-bootstrap workflow |
| 2 | `add-scaleset` | `esaf.add_scale_set(suffix, environment=..., cidr=..., session=...)` | Register, enroll and deploy the scale set's common resources |
| 3 | `add-or-update-project` | `esaf.upsert_project(number, environment=..., scale_set=..., session=...)` | Add or update the selected project, then deploy it |
| 4 | `delete-project` | `esaf.delete_project(number, environment=..., scale_set=..., session=...)` | Delete the project in the selected environment and scale set |
| 5 | `delete-scaleset` | `esaf.delete_scale_set(suffix, environment=..., session=...)` | Delete the scale set's registered resources |
| 6 | `delete-factory` | `esaf.delete_factory(session=...)` | Delete the factory's registered resources; shared hubs and subscriptions stay |

`upsert_project` is canonical; `apply_project` remains a compatibility alias. The folder belongs to an explicit `esaf.Session`,
not the first positional argument of every method. Each session selects the resolved factory ID; project and scale-set
calls require the environment (`dev`, `stage` or `prod`). Scenario 2 does **not** create project001 implicitly:
use Scenario 3 for it.

## Call the Function

The existing HTTP routes remain: `POST /api/v1/lifecycle/{scenario}/prepare`, `GET /api/v1/operations/{id}`,
and `POST /api/v1/operations/{id}/confirm`. Writes return `202`, `Location` and `Retry-After`.

```powershell
# $base ends in /api; $headers contains the function key and, when enabled, an Entra bearer token.
$op = Invoke-RestMethod "$base/v1/lifecycle/add-or-update-project/prepare" -Method Post -Headers $headers `
    -ContentType application/json -Body '{"projectId":"contoso-ai-esml-project002-sdc-dev-001-rg","settings":{}}'
$op = Invoke-RestMethod "$base/v1/operations/$($op.operationId)" -Headers $headers
# With github-runner, read the operation until awaiting_confirmation before continuing.
$review = $op.steps[0].preview
$review
$body = @{ confirmationToken = $review.confirmationToken; confirmationPhrase = $review.confirmationPhrase }
Invoke-RestMethod "$base/v1/operations/$($op.operationId)/confirm" -Method Post -Headers $headers `
    -ContentType application/json -Body ($body | ConvertTo-Json)
```

**SDK prepare is a local scope approval, not an Azure dry-run.** It resolves catalog IDs and validates input but
does not call a mutating facade method or prepare a live deployment. Confirm approves the entire scenario; L1
submits it to L2 and receives `202` with an ESAF job ID. The Function persists `job_kind="esaf"`, the job ID and
selected factory. The reconciler reads `EsafJob.status()` via `GET /api/v1/esaf/jobs/{id}?folder=...` after host
restarts; it does not depend on an in-memory job or thread. The outer ESAF status is authoritative: a failed child
does not end an operation while L2 is retrying. Server failure messages are retained in the operation.

## Architecture and safety

```text
Consumer: HTTP Function -> LifecycleService (scope approval, protection, durable operation)
                       -> local adapter OR signed management-runner hand-off
L1: SdkFactoryBackend -> Python esaf -> one approved POST /api/v1/esaf/<scenario>
L2: Factory API -> durable ESAF job -> reviews/enrollment/dispatch -> L3 pipelines -> L4 Bicep/scripts -> L5 ARM
Consumer <- persisted EsafJob ID/kind <- outer job GET via L1 and the reconciler
```

The Factory API's catalog, deployment and ESAF routes are loopback-only. Choose `AIF_EXECUTOR=inprocess` for a local Function
beside the API, or `github-runner` for an Azure-hosted Function: a signed request runs on the management VM beside
the API, then posts its signed result back. The Function never calls those API routes across the network.
The runner and relay workflows belong in a separate ops repository, not the factory repository.

- **Protected scopes:** `AIF_SELF_PROJECT_ID` and `AIF_PROTECTED_IDS` prevent changing the Function/runner's host.
- **Deletes off:** `AIF_DELETES=refuse` is the default. `simulate` uses a read-only catalog mirror and dummy runs.
  Real deletes require `allow`, plus `AIF_ALLOW_REAL_DELETES=true` on a remote runner.
- **No resubmission:** the operation is saved as `confirming` before execution. Definite configuration/auth/scope
  refusals fail the operation. Transport/server failures or a missing job receipt become `uncertain`; inspect the
  API's jobs before another attempt. The Function never retries submission. L2 may retry work inside an accepted
  ESAF job (the current server default is two retries); that is not another Function confirmation.
- **Exact scope:** changed factory/project/scale-set identities require a new approval; unrelated catalog revision
  drift does not block. Scenario 6 refuses a factory containing other environments than the requested FactoryId.
- **Authentication:** lifecycle routes require a function key; enable Entra App Service authentication and
  `Lifecycle.Operator` for real use. Events and runner results require HMAC signatures.

| Layer | Files |
|---|---|
| HTTP / runner entry points | `function_app.py`, `http_api.py`, `runner.py` |
| Application | `application/service.py`, `planner.py`, `resolver.py`, `guard.py` |
| State and contracts | `domain/operation.py`, `ports.py`, `application/runner_protocol.py` |
| SDK adapter | `adapters/sdk_backend.py` (no hand-written API prepare/confirm chain) |
| Persistence / status / transport | `adapters/stores.py`, `trackers.py`, `runner_backend.py` |
| Composition | `composition.py`, `settings.py` |

## IDs and settings

| ID | Example |
|---|---|
| Factory | `contoso-ai-sdc-dev` |
| Scale set | `contoso-ai-sdc-dev-001` |
| Project (resource group name) | `contoso-ai-esml-project002-sdc-dev-001-rg` |

IDs use the accelerator's naming; Azure `test` maps to catalog `stage`.

| Setting | Purpose |
|---|---|
| `AIF_BACKEND` | `sdk` for the simplified facade; default `mock` for offline use; `rest` for the legacy per-step contract |
| `AIF_EXECUTOR` | `inprocess`, `github-runner`; `github-dummy` is mock-only |
| `AIF_FACTORY_FOLDER`, `AIF_FACTORY_API_URL` | Consumer `azurefactory` folder on the API host; loopback URL, default `http://127.0.0.1:8765` |
| `AIF_FACTORY_API_KEY_NAME`, `AIF_KEY_VAULT_NAME` | API key secret name and vault; remote mode configures these on the runner |
| `AIF_STORE` | `memory` for tests, `file` locally, `table` in Azure |
| `AIF_DELETES` | `refuse`, `simulate`, `allow` |
| `AIF_REVIEW_TTL_SECONDS` | Scope approval lifetime, default 600 seconds |

The SDK is installed from the exact published purple commit in `requirements.txt`, not copied into the Function.
**A live, compatible L2 API on the same host as L1 is a prerequisite.** Before rollout, verify the installed API
supports `/api/v1/esaf/*`, durable job status, exact environment/scale-set/project selection and enrollment/deletion
guards. Missing facade routes fail closed (`sdk-config`); there is no fallback to legacy prepare/confirm endpoints.
Update/verify the API first, then the Function and runner together; keep real deletes refused during the upgrade.
Source HEAD and the SDK pin do not prove which API or SDK is installed.
Full setup, identities, secrets, deployment and troubleshooting: [README_More_Info.md](README_More_Info.md).

## Local use and upgrades

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
Copy-Item local.settings.example.json local.settings.json
# Set AIF_BACKEND=sdk and the API-host settings; leave deletes refused.
func start
```

New thin-SDK coverage is in `tests/test_esaf_l1_contract.py` and `tests/test_upsert_project_dispatch.py`; run explicit
test node IDs for the behavior being changed. These tests use an ephemeral loopback HTTP fake, not a live API, for
all six routes, both executors, restart-safe outer job status, legacy job reads and refusal/uncertain outcomes.

The [onion V2 document](../../../documentation/v2/10-19/10-factory-onion-architecture-v2.md) describes the layer
boundaries. Its older generated L1 review sequence and add-scale-set project-deployment examples predate the
server facade; the current L1/L2 contract above takes precedence. Generated diagrams are not changed here.

Copy this folder into the consumer's `aifactory-usecase-code/10-azure-function/12_func_aifactory_lifecycle/`.
Preserve consumer settings and update the Function and lifecycle runner together. Finish/reconcile old SDK operations
before upgrading: old job handles remain readable, but unconfirmed old per-step requests are refused with
`sdk-operation-upgrade`. Re-prepare them under the new scope-approval contract; never replay an uncertain confirm.

`AIF_BACKEND=rest` intentionally keeps its reviewed per-step behavior, including Scenario 2's project001 creation.
Its transport and tests remain for compatibility; it does not use the esaf facade.
