# AI Factory lifecycle Function

An Azure Functions Python consumer of `from azurefactory import esaf`. Set **`AIF_BACKEND=sdk`** to run each
scenario through **one facade method**, with one Function scope approval. Each method is one call to the Factory
API's `/api/v1/esaf/*` routes, which own the prepare/confirm calls, enrollment, deletion authorization, server
confirmation phrases and retries (Factory API with the ESAF routes, pink 1b1fed5 or later).

| # | Function route segment | SDK method | Result |
|---|---|---|---|
| 1 | `init-factory` | `esaf.init_factory(creation_request=..., session=...)` | Save a new factory and start its server-owned full-bootstrap workflow |
| 2 | `add-scaleset` | `esaf.add_scale_set(suffix, environment=..., cidr=..., session=...)` | Register, enroll and deploy the scale set's common resources |
| 3 | `add-or-update-project` | `esaf.upsert_project(number, environment=..., scale_set=..., session=...)` | Add or update the selected project, then deploy it |
| 4 | `delete-project` | `esaf.delete_project(number, environment=..., scale_set=..., session=...)` | Delete the project in the selected environment and scale set |
| 5 | `delete-scaleset` | `esaf.delete_scale_set(suffix, environment=..., session=...)` | Delete the scale set's registered resources |
| 6 | `delete-factory` | `esaf.delete_factory(session=...)` | Delete the factory's registered resources; shared hubs and subscriptions stay |

`apply_project` remains an alias of `upsert_project`. The folder belongs to an explicit `esaf.Session`, not an argument
of every method. Each session selects the resolved factory ID; project and scale-set calls always carry the
environment, which the SDK requires. Scenario 2 does **not** create project001 implicitly: use Scenario 3 for it.

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
does not call a mutating facade method or prepare a live deployment. Confirm approves the entire scenario; the
SDK then checks and confirms the live API reviews. The returned SDK job ID and kind are saved in the operation.
The existing reconciler reads `EsafJob.status()` after host restarts; it does not depend on an in-memory job or thread.
Scenario 1 uses the API's bounded whole-workflow approval and stops if the API requires another human review.

## Architecture and safety

```text
HTTP Function -> LifecycleService (scope approval, protection, durable operation)
             -> SdkFactoryBackend -> one esaf method -> Factory API -> lifecycle job
             <- persisted EsafJob ID/kind <- status via the reconciler
```

The Factory API's catalog/deployment routes are loopback-only. Choose `AIF_EXECUTOR=inprocess` for a local Function
beside the API, or `github-runner` for an Azure-hosted Function: a signed request runs on the management VM beside
the API, then posts its signed result back. The Function never calls those API routes across the network.
The runner and relay workflows belong in a separate ops repository, not the factory repository.

- **Protected scopes:** `AIF_SELF_PROJECT_ID` and `AIF_PROTECTED_IDS` prevent changing the Function/runner's host.
- **Deletes off:** `AIF_DELETES=refuse` is the default. `simulate` uses a read-only catalog mirror and dummy runs.
  Real deletes require `allow`, plus `AIF_ALLOW_REAL_DELETES=true` on a remote runner.
- **No uncertain retries:** the operation is saved as `confirming` before execution. A failed facade call may already
  have changed configuration or permissions, so it becomes `uncertain`; inspect the API state before another attempt.
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
Before rollout, update the Factory API to a build that supports existing-scale-set enrollment extension and enforces
project enrollment/deletion permission before `API-2-Pipelines` dispatch. Updating the SDK alone is insufficient;
keep real deletes refused during the upgrade.
Full setup, identities, secrets, deployment and troubleshooting: [README_More_Info.md](README_More_Info.md).

## Local use and upgrades

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
Copy-Item local.settings.example.json local.settings.json
# Set AIF_BACKEND=sdk and the API-host settings; leave deletes refused.
func start
```

New scenario coverage is in `tests/test_esaf_scenarios.py`; run explicit test node IDs for the behavior being changed.
These tests cover all six routes through the local and signed-runner paths, real SDK HTTP integration, restart-safe
job status, scope protection and uncertain outcomes.

Copy this folder into the consumer's `aifactory-usecase-code/10-azure-function/12_func_aifactory_lifecycle/`.
Preserve consumer settings and update the Function and lifecycle runner together. Finish/reconcile old SDK operations
before upgrading: old job handles remain readable, but unconfirmed old per-step requests are refused with
`sdk-operation-upgrade`. Re-prepare them under the new scope-approval contract; never replay an uncertain confirm.

`AIF_BACKEND=rest` intentionally keeps its reviewed per-step behavior, including Scenario 2's project001 creation.
Its transport and tests remain for compatibility; it does not use the esaf facade.
