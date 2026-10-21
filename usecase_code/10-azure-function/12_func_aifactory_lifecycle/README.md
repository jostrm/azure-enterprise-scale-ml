# AI Factory lifecycle Function

A reusable Azure Functions template (Python v2 model) that runs six AI Factory lifecycle scenarios through the
Factory API - over REST (option 1) or the `azurefactory` Python SDK (option 2) - and follows every run through
GitHub workflow events until it succeeds or fails.

| # | Scenario | Route segment | Input | What it does |
|---|---|---|---|---|
| 1 | Init AI Factory | `init-factory` | `factoryId` | Catalog entry, then connectivity, scale set 001 (common RG + vNet) and project001 |
| 2 | Add scale set | `add-scaleset` | `scalesetId` | New common RG, vNet and default project001 |
| 3 | Add or update project | `add-or-update-project` | `projectId` | A new number adds the project; an existing number updates it |
| 4 | Delete project | `delete-project` | `projectId` | Deletes one project in a scale set |
| 5 | Delete scale set | `delete-scaleset` | `scalesetId` | Deletes its projects and its common RG |
| 6 | Delete AI Factory | `delete-factory` | `factoryId` | Deletes all scale sets of a single-environment factory |

## Readable IDs

| ID | Grammar | Example (Spider) |
|---|---|---|
| FactoryId | `prefix-regioncode-env` | `spider-sdc-dev` |
| ScalesetId | `FactoryId-suffix` | `spider-sdc-dev-001` (common RG `spider-esml-common-sdc-dev-001`) |
| ProjectId | the project resource group name | `spider-esml-project001-sdc-dev-001-rg` |

- Tokens follow purple's resource-group naming; Azure names use `dev`/`test`/`prod` (the catalog's `stage` is `test`).
- Region codes come from `bootstrap/lib/create-new-aifactory-scaleset.sh`; `tests/test_regions.py` fails if the copy
  in `aif_lifecycle/domain/regions.py` drifts.
- There is no salt: an ID only has to be unique within one consumer repo's catalog. IDs are resolved by formatting each
  catalog entity (`GET /api/v1/factory-catalog`) and matching the whole string.

## Architecture

The Factory API serves catalog and deployment routes to loopback clients only, so the Function never calls it over the
network. It hands the work to an executor:

```
Caller (VPN)
 -> Function (private endpoint): validate, resolve IDs, self-protect, record the operation, 202 + Location
    -> executor  inprocess     : adapters call the API on this host's loopback (local `func start` next to the API)
                 github-dummy  : one aif-dummy-step.yml run per resource group (mocked API, real GitHub events)
                 github-runner : aif-ops.yml on the management runner -> REST/SDK adapter -> API on 127.0.0.1:8765
                                 -> the API dispatches factory-lifecycle.yml
 <- events: aif-event-relay.yml (workflow_run, on the management runner) POSTs the payload, HMAC-signed
 <- fallback: the timer polls GitHub for runs whose events are late
```

| Layer | Code | Patterns |
|---|---|---|
| Entry | `function_app.py` (thin), `aif_lifecycle/http_api.py` | Gatekeeper (HMAC), Asynchronous Request-Reply |
| Application | `application/service.py` (`LifecycleService`), `planner.py`, `resolver.py`, `guard.py`, `events.py` | Facade |
| Domain | `domain/ids.py`, `operation.py`, `scenarios.py`, `errors.py` | State (transition table) |
| Ports | `ports.py` | |
| Adapters | `adapters/mock_backend.py`, `factory_api.py` + `rest_backend.py` / `sdk_backend.py`, `trackers.py`, `github.py`, `stores.py`, `queue.py` | Strategy, Template Method, Adapter, Queue-Based Load Leveling |
| Composition root | `composition.py`, `settings.py` | |

- **Two steps everywhere.** `POST .../prepare` returns 202; the preview (plan, affected resource groups, blockers,
  `canExecute`, `expiresAt`, `confirmationToken`) is on `GET /api/v1/operations/{id}`; `POST .../confirm` sends the
  token, plus the phrase for deletes. One Function confirm per Factory API confirmation; nothing is auto-confirmed.
- **Never retry an uncertain confirm.** The operation is saved as `confirming` (compare-and-swap) before the
  non-idempotent call. A timeout or 5xx makes it `uncertain`, which is terminal: reconcile the API job first.
- **Chained steps** advance on `completed/success`: the next step is prepared automatically and waits for its own
  confirmation. A failed run stops the chain with the run link and a log excerpt.
- **Self-protection.** Targets that contain `AIF_SELF_PROJECT_ID` or any `AIF_PROTECTED_IDS` entry (for example the
  management runner's scale set) are refused with 403, so scenario 5 or 6 can never delete the host.
- **Scenario 6** uses `delete-aifactory`, which always deletes every environment of a factory. The Function accepts a
  FactoryId only when all of the factory's scale sets are in that environment; otherwise 409 `scope-not-supported`
  (delete the scale sets one by one with scenario 5).

## HTTP API

| Method and route | Auth | Answer |
|---|---|---|
| `GET /api/v1/health` | anonymous | 200 `{status, version, backend, executor}` |
| `POST /api/v1/lifecycle/{scenario}/prepare` | function key | 202, `Location`, `Retry-After` |
| `GET /api/v1/operations` | function key | 200 list |
| `GET /api/v1/operations/{id}` | function key | 200 operation with steps, previews, runs, history |
| `POST /api/v1/operations/{id}/confirm` | function key | 202, `Location`, `Retry-After` |
| `POST /api/v1/github/events` | anonymous + `X-Hub-Signature-256` | 202 applied/queued, 200 duplicate/ignored, 401 bad signature |

Prepare bodies: `{"factoryId": "aif-121-sdc-dev"}`, `{"scalesetId": "aif-121-sdc-dev-002"}`,
`{"projectId": "aif-121-esml-project002-sdc-dev-001-rg", "settings": {...}}`. Optional: `wholeWorkflow` (scenario 1,
one bounded approval), `includeProjectSubnets` / `includeKeyvaultAndResourceGroup` (scenario 4, default true),
`scaleSet` `{subscriptionId, tenantId, orchestrator, vnetCidr, maxProjects}` (scenarios 1-2 against the real API),
`bootstrapConfig` (scenario 1 against the real API). Mock only: `simulate` `{failAt, uncertainAt, rejectAt,
dropEventAt}` and `ttlSeconds`.

Errors are RFC 9457 `application/problem+json` with `code` and `correlationId`, never stack traces or secrets:
400 `validation-failed` / `invalid-id` / `invalid-json` / `unsupported-scenario` / `confirmation-mismatch` /
`confirmation-phrase-mismatch`, 401 `invalid-signature`, 403 `protected-target`, 404 `unknown-id` /
`operation-not-found`, 409 `already-exists` / `in-progress` / `revision-mismatch` / `invalid-state` /
`scope-not-supported`, 410 `confirmation-expired`, 502 `upstream-error` / `upstream-refused`, 503 `upstream-unavailable`
/ `configuration-invalid`, 504 `upstream-timeout`.

## Settings

| Setting | Values (default first) | Notes |
|---|---|---|
| `AIF_BACKEND` | `mock`, `rest`, `sdk` | Mock keeps a persistent catalog in the state store |
| `AIF_EXECUTOR` | `inprocess`, `github-dummy`, `github-runner` | See Architecture |
| `AIF_STORE` | `memory`, `file`, `table` | `table` uses the Function's managed identity (`AIF_TABLE_ACCOUNT`, `AIF_TABLE_NAME`) |
| `AIF_EVENT_PROCESSING` | `inline`, `queue` | `queue` answers fast and applies events from `AIF_EVENT_QUEUE` |
| `AIF_SELF_PROJECT_ID`, `AIF_PROTECTED_IDS` | IDs | Deny list for self-protection |
| `AIF_KEY_VAULT_NAME` | vault name | The Function reads the secrets below by name with its managed identity |
| `AIF_EVENT_SECRET_NAME` | secret name | HMAC secret for the events route and queued messages; a secret value may hold two comma-separated values while rotating |
| `AIF_GITHUB_REPOSITORY`, `AIF_GITHUB_TOKEN_NAME` | `owner/repo`, secret name | Fine-grained token or GitHub App limited to that repo's Actions |
| `AIF_FACTORY_API_URL`, `AIF_FACTORY_API_KEY_NAME`, `AIF_FACTORY_FOLDER` | `http://127.0.0.1:8765`, secret name, path | REST/SDK; plain http only to loopback |
| `AIF_REVIEW_TTL_SECONDS`, `AIF_POLL_AFTER_SECONDS` | 600, 120 | |

For local development, `AIF_EVENT_SECRET`, `AIF_GITHUB_TOKEN` and `AIF_FACTORY_API_KEY` can hold plain values.
App Service Key Vault *references* are not used: on Linux plans other than Flex they need route-all to reach a private
vault, which would cut the app's GitHub egress. A setting that still holds an unresolved `@Microsoft.KeyVault(...)`
reference is refused with 503 `configuration-invalid` instead of being used as a secret.

The SDK is pinned to a purple commit in `requirements.txt` (`git+https://...@<sha>#subdirectory=...`), not copied.

## Local development

```powershell
python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt pytest
.\.venv\Scripts\python -m pytest tests -q
Copy-Item local.settings.example.json local.settings.json   # git-ignored; mock backend, file store
func start   # timers and queues need Azurite or a real storage account
```

With the wizard's Factory API on the same machine, set `AIF_BACKEND=rest` (or `sdk`), `AIF_FACTORY_FOLDER`,
`AIF_FACTORY_API_KEY` and keep `AIF_EXECUTOR=inprocess`: that is the fast dev loop.

## Deploy to an AI Factory project

1. Copy `settings.example.json` to `settings.<consumer>.json` and fill in the project's subnets, storage account,
   Application Insights, Log Analytics, Key Vault and DNS zone. Never put secret values in it. Name the app outside
   purple's `func-prj<NNN>-...` pattern (for example `aiflc-prj001-sdc-dev-<uniq5>-001`): purple's project pipelines
   treat such an app as the project Function and can delete it; `deploy.ps1` refuses such a name unless you pass
   `-AcceptPurpleFunctionName`. The integration subnet needs /26 or more when several plans share it.
2. Connect to the factory's VPN (the app and its deployment endpoint are private), then run PowerShell 7:

   ```powershell
   .\deploy.ps1 -SettingsFile .\settings.<consumer>.json -WhatIf
   .\deploy.ps1 -SettingsFile .\settings.<consumer>.json
   ```

   `infra/function-app.bicep` creates a private dedicated Linux plan (B1 by default; Elastic Premium is not supported
   because it needs a key-based content share) and app with VNet integration, a private endpoint, identity-based
   storage roles, an optional Key Vault Secrets User grant, diagnostics to Log Analytics and no basic publishing
   credentials. The code is deployed with
   `az functionapp deployment source config-zip --build-remote` (Microsoft Entra), which **replaces every function in
   the app**: give this template its own app.
3. Get the function key with `az functionapp keys list` and call `GET /api/v1/health`.

Use function keys for the mock passes. Before real deployments, add App Service authentication with an Entra app role.

## Consumer copy

A consumer repo copies this folder to `aifactory-usecase-code/10-azure-function/12_func_aifactory_lifecycle/` and the
workflow templates from `workflows/` to its `.github/workflows/`, then adds its own `settings.<consumer>.json`.
