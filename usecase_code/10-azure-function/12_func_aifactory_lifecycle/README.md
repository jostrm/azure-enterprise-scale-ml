# AI Factory lifecycle Function

A reusable Azure Functions template (Python v2 model) that runs six AI Factory lifecycle scenarios through the
Factory API - over REST (option 1) or the `azurefactory` Python SDK (option 2) - and follows every run through
GitHub workflow events until it succeeds or fails.

Every secret and identity, and the full solution with copyable examples: [README_More_Info.md](README_More_Info.md).

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
                                 -> the API dispatches factory-lifecycle.yml in the factory repo
 <- results: the runner POSTs one signed result per call to /api/v1/runner/results (github-runner)
 <- events: aif-event-relay.yml (workflow_run, on the management runner) POSTs the payload, HMAC-signed
 <- fallback: the timer polls runs whose events are late and times out runner calls that never report
```

With `github-runner`, every Factory API call is a hand-off: the step waits in `preparing` or `confirming`
(`waitingFor` on the operation) until the runner's signed result arrives. A review that never reports fails with
`runner-timeout`; a confirmation that never reports, or whose aif-ops run ends without a result, becomes `uncertain`
(never retried). Planning reads a catalog snapshot that every runner result refreshes; the first prepare answers 503
`catalog-pending` while the snapshot is read, and `POST /api/v1/catalog/refresh` reads it again. Job status checks also
run on the runner, one at a time.

| Layer | Code | Patterns |
|---|---|---|
| Entry | `function_app.py` (thin), `aif_lifecycle/http_api.py`, `aif_lifecycle/runner.py` (runner host) | Gatekeeper (HMAC), Asynchronous Request-Reply |
| Application | `application/service.py` (`LifecycleService`), `planner.py`, `resolver.py`, `guard.py`, `events.py`, `runner_protocol.py` (Function-runner contract) | Facade |
| Domain | `domain/ids.py`, `operation.py`, `scenarios.py`, `errors.py` | State (transition table) |
| Ports | `ports.py` | |
| Adapters | `adapters/mock_backend.py`, `factory_api.py` + `rest_backend.py` / `sdk_backend.py`, `runner_backend.py`, `trackers.py`, `github.py`, `stores.py`, `queue.py` | Strategy, Template Method, Adapter, Queue-Based Load Leveling |
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
- **No real deletes by default.** With a real backend (`rest`, `sdk`, `github-runner`), scenarios 4-6 answer 403
  `deletes-disabled` before anything is recorded or sent: the REST and SDK adapters, the Function's runner adapter and
  the runner itself (`AIF_ALLOW_REAL_DELETES` in its `runner.json`, off unless `true`) each refuse a delete on their
  own. `AIF_DELETES=simulate` rehearses scenarios 4-6 end to end instead: the mock backend reviews them over a
  read-only copy of the real catalog and their runs are `aif-dummy-step.yml` workflows, so the Factory API never sees
  a delete. Real deletes need `AIF_DELETES=allow` on the Function and `AIF_ALLOW_REAL_DELETES=true` on the runner.
- **Scenario 6** uses `delete-aifactory`, which always deletes every environment of a factory. The Function accepts a
  FactoryId only when all of the factory's scale sets are in that environment; otherwise 409 `scope-not-supported`
  (delete the scale sets one by one with scenario 5).

## HTTP API

| Method and route | Auth | Answer |
|---|---|---|
| `GET /api/v1/health` | anonymous | 200 `{status, version, backend, executor}` |
| `POST /api/v1/lifecycle/{scenario}/prepare` | function key (+ Entra app role) | 202, `Location`, `Retry-After` |
| `GET /api/v1/operations` | function key (+ Entra app role) | 200 list |
| `GET /api/v1/operations/{id}` | function key (+ Entra app role) | 200 operation with steps, previews, runs, history |
| `POST /api/v1/operations/{id}/confirm` | function key (+ Entra app role) | 202, `Location`, `Retry-After` |
| `POST /api/v1/github/events` | anonymous + `X-Hub-Signature-256` | 202 applied/queued, 200 duplicate/ignored, 401 bad signature |
| `POST /api/v1/runner/results` | anonymous + `X-Hub-Signature-256` | 202 applied, 200 ignored (not the pending hand-off), 401 bad signature |
| `POST /api/v1/catalog/refresh` | function key | 202; `github-runner` only (400 `not-supported` otherwise) |

Prepare bodies: `{"factoryId": "aif-121-sdc-dev"}`, `{"scalesetId": "aif-121-sdc-dev-002"}`,
`{"projectId": "aif-121-esml-project002-sdc-dev-001-rg", "settings": {...}}`. Optional: `wholeWorkflow` (scenario 1,
one bounded approval; required with the real API), `includeProjectSubnets` / `includeKeyvaultAndResourceGroup`
(scenario 4, default true), `scaleSet` `{subscriptionId, tenantId, orchestrator, vnetCidr, maxProjects}` (scenario 2
against the real API), `bootstrapConfig` (scenario 1 against the real API: the API's full bootstrap configuration, for
example `subscription_id`, `tenant_id`, `team_member_email`, `team_group_name`, `github_repository`,
`coordination_mode`, `access_hub_mode`, `setup_hub_access`). Mock only: `simulate` `{failAt, uncertainAt, rejectAt,
dropEventAt}` and `ttlSeconds`.

Against the real API, scenario 1 saves the factory with `POST /api/v1/creation/prepare` and `/confirm` (full
bootstrap, dev scale set 001; the Function pins `factory_prefix`, `location` and `scale_set_number` to the FactoryId),
then runs the creation workflow under one whole-workflow approval, which the API continues by itself between stages.
If the API asks for a new human review mid-workflow (`requires_review`), the step stops with `action_required` and the
API's message.

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
| `AIF_DELETES` | `refuse` (default), `simulate`, `allow` | Real backends only: `refuse` answers 403 `deletes-disabled`, `simulate` runs scenarios 4-6 on the mock and dummy workflows, `allow` deletes for real; health shows the mode (`mock` with the mock backend) |
| `AIF_KEY_VAULT_NAME` | vault name | The Function reads the secrets below by name with its managed identity |
| `AIF_EVENT_SECRET_NAME` | secret name | HMAC secret for the events route and queued messages; a secret value may hold two comma-separated values while rotating |
| `AIF_GITHUB_REPOSITORY`, `AIF_GITHUB_TOKEN_NAME` | `owner/repo`, secret name | Fine-grained token or GitHub App limited to that repo's Actions |
| `AIF_FACTORY_API_URL`, `AIF_FACTORY_API_KEY_NAME`, `AIF_FACTORY_FOLDER` | `http://127.0.0.1:8765`, secret name, path | REST/SDK with `inprocess`; plain http only to loopback. With `github-runner` they belong to the runner (`runner.json`), not the Function |
| `AIF_OPS_WORKFLOW`, `AIF_RUNNER_TIMEOUT_SECONDS` | `aif-ops.yml`, 4200 | `github-runner`: the workflow it dispatches in `AIF_GITHUB_REPOSITORY`, and how long a hand-off may stay silent (longer than `aif-ops.yml`'s 60-minute job) |
| `AIF_FACTORY_API_TIMEOUT_SECONDS` | 2700 | How long one Factory API call may take on the runner: on the real API a runtime deploy review took 13 minutes and its confirmation held the catalog lock for 18 minutes while it built the run. A machine environment variable on the VM overrides `runner.json`, which the installer rewrites. In-process calls are also capped by the Function's `functionTimeout` (10 minutes) |
| `AIF_REQUIRED_ROLE` | app role, for example `Lifecycle.Operator` | Lifecycle routes also need this role in the caller's Entra token; refused at startup unless App Service authentication is on (`authClientId`) |
| `AIF_REVIEW_TTL_SECONDS`, `AIF_POLL_AFTER_SECONDS` | 600, 120 | |

For local development, `AIF_EVENT_SECRET`, `AIF_GITHUB_TOKEN` and `AIF_FACTORY_API_KEY` can hold plain values.
App Service Key Vault *references* are not used: on Linux plans other than Flex they need route-all to reach a private
vault, which would cut the app's GitHub egress. A setting that still holds an unresolved `@Microsoft.KeyVault(...)`
reference is refused with 503 `configuration-invalid` instead of being used as a secret.

The SDK is pinned to a purple commit in `requirements.txt` (`git+https://...@<sha>#subdirectory=...`), not copied.

## Local development

```powershell
python -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt
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
   `-AcceptPurpleFunctionName`. The integration subnet must be delegated to `Microsoft.App/environments`, /27 or
   larger, and not used by Container Apps or private endpoints (a project's `snt-prjNNN-aca` subnets are taken by
   Container Apps, and `snt-prjNNN-webapp` is delegated to Dedicated plans): add one, for example `snt-prj001-func`.
2. Connect to the factory's VPN (the app and its deployment endpoint are private), then run PowerShell 7:

   ```powershell
   .\deploy.ps1 -SettingsFile .\settings.<consumer>.json -WhatIf
   .\deploy.ps1 -SettingsFile .\settings.<consumer>.json
   ```

   `infra/function-app.bicep` creates a private Linux app on the Flex Consumption plan with VNet integration, a
   private endpoint, a deployment package container in the project's storage account (read with the app's identity),
   identity-based storage roles, an optional Key Vault Secrets User grant, diagnostics to Log Analytics and no basic
   publishing credentials. The code is deployed with
   `az functionapp deployment source config-zip --build-remote` (Microsoft Entra), which **replaces every function in
   the app**: give this template its own app.
3. Get the function key with `az functionapp keys list` and call `GET /api/v1/health`.

### Hosting plan

The app runs on the Flex Consumption plan because it needs no Always On. On a Dedicated (App Service) plan the
Functions host goes idle after a few minutes without Always On, and only HTTP requests wake it, so the 2-minute
`reconcile` timer and the GitHub-events queue trigger stop. Subscription governance (MCAPS) switched Always On off on
the Spider app every night at about 01:36 CEST (2026-10-22 and 2026-10-23). Flex Consumption starts instances for
every trigger by itself.

Cost (Sweden Central list prices, October 2026): the Dedicated B1 plan was about USD 13 per month. Flex Consumption
bills execution time only, after a monthly free grant of 100,000 GB-seconds and 250,000 executions; the reconcile
timer runs about 22,000 times a month, so expect roughly USD 0-10 per month. Optional always-ready instances (to avoid
cold starts) cost about USD 5 per month per 512 MB instance, USD 21 per 2,048 MB. Elastic Premium (EP1, about USD 154
per month) is not used.

An existing Dedicated app cannot be moved to Flex Consumption in place: deploy a new app (new name, Flex-delegated
integration subnet), switch its callers (event relay, runner results, operators) to it, then retire the old app.

Use function keys for the mock passes. Before real deployments, add App Service authentication with an Entra app role:

```powershell
.\scripts\register-entra-app.ps1 -DisplayName aif-lifecycle-func-<consumer> -Operator <upn>   # prints authClientId
```

Put `authClientId` in `settings.<consumer>.json` and redeploy with infrastructure; the template then sets
`AIF_REQUIRED_ROLE` (`requiredRole`, default `Lifecycle.Operator`) itself, and never passes `WEBSITE_AUTH_*` settings
through. Clearing `authClientId` turns App Service authentication off again. Tokens are accepted only from the client
applications in `authAllowedClientApplications` (default: Azure CLI); with an empty list, Azure CLI tokens got 403 on
the Spider Function. App Service authentication answers 401 to calls without a valid
token for `api://<authClientId>`, and the Function answers 403 `missing-role` to callers without the role; health,
events and runner results stay anonymous (HMAC-checked). Callers send both the function key and a token:

```powershell
$token = az account get-access-token --resource api://<authClientId> --query accessToken -o tsv
Invoke-RestMethod "$base/v1/operations" -Headers @{ 'x-functions-key' = $key; Authorization = "Bearer $token" }
```

## GitHub events: relay and management runner

- `workflows/aif-dummy-step.yml` (GitHub-hosted runner) simulates one resource-group deployment; its run name starts
  with `aif-step [<operationId>/<step>/<target>]`, which the Function matches as a whole.
- `workflows/aif-event-relay.yml` must be on the default branch of the repository that runs the Function's workflows
  (the ops repository with the runner executor). It forwards only `workflow_dispatch` runs of the same repository (for
  `aif-ops`, only runs that ended without success), signs the payload with the first value of the event secret (the
  Function's rule) and retries transient failures three times. The Function also checks the event, workflow file and repository, keeps the
  first run id bound to a run, and records a delivery only after it was applied or queued. The poller recovers events
  that never arrive (`dropEventAt` simulates that).
- Register the management runner for that repository (user-owned repos can't share runners):
  `scripts/register-management-runner.ps1` gets a one-hour registration token with `gh` and runs
  `scripts/install-github-runner.ps1` on the VM through a VM run command, passing the token as a protected parameter.
  The runner package hash is verified. Use a label of its own (default `aif-lifecycle-mgmt`), never the factory's
  runner label.
- **The label is privileged.** Any workflow that targets it runs on the management VM, which reaches the Function's
  private endpoint and (for the runner executor) the Factory API. Keep fork-pull-request workflows off and limit
  collaborators to trusted admins.
- Repository settings: variable `AIF_LIFECYCLE_EVENTS_URL` (`https://<app>.azurewebsites.net/api/v1/github/events`)
  and secret `AIF_LIFECYCLE_EVENT_SECRET` (one value, no commas).

## Runner executor: the Factory API host

`AIF_EXECUTOR=github-runner` (with `AIF_BACKEND=rest` or `sdk`, the adapter the runner uses) needs:

- **Two repositories.** The Factory API refuses to dispatch `factory-lifecycle.yml` while any other workflow of the
  factory repo is queued or running, so `aif-ops.yml`, `aif-event-relay.yml` (and `aif-dummy-step.yml`) live in a
  separate ops repository with the management runner; `AIF_GITHUB_REPOSITORY` names that ops repository. The factory
  repository holds only what the Factory API writes there. Runs the API dispatches are followed through the API's job
  status, because the factory repository can't run a relay either.
- **The Factory API on the management VM**, loopback only, as a service of one fixed Windows user (its confirmations
  are sealed for that user) with a fixed `AIFACTORY_CATALOG_OWNER`, and with that user's own `az` and `gh` logins: the
  API passes no token variables to the CLIs it runs. Keep a persistent clone of the factory repository outside the
  runner's `_work` folder; the API's `folder` is its `azurefactory` subfolder.
  `scripts/install-factory-api-host.ps1` sets this up with SYSTEM as that user (run it on the VM, for example with
  `az vm run-command invoke --command-id RunPowerShellScript --scripts @install-factory-api-host.ps1 --parameters
  KeyVaultName=<vault>`): a pinned release checked against its `SHA256SUMS.txt`, a startup task, `gh` logged in from Key
  Vault. It needs, before it runs:
  - the VM's managed identity (the installer signs the API's own `az` profile, `C:\aif-api\azure-cli`, in with it at
    every start, so other SYSTEM jobs cannot log the API out) has Owner on the factory subscription and the Microsoft
    Graph app roles `Group.ReadWrite.All` and `User.Read.All` (a Privileged Role
    Administrator grants them; the bootstrap creates the team group);
  - Reader for the same identity on every virtual network in another subscription that is peered with a network in
    the factory subscription, for example a connectivity hub's: the bootstrap's network-foundation stage follows those
    peerings, and an ARM 403 there stops a whole-workflow bootstrap as `uncertain` (recovery steps in
    [README_More_Info.md](README_More_Info.md));
  - Key Vault secret `aif-factory-api-key`: any long random value, the API's `X-API-Key`;
  - Key Vault secret `aif-factory-api-gh-token`: a classic GitHub PAT with `repo`, `workflow` and `read:org`, nothing
    more (`gh auth login` refuses a classic token without `read:org`, and the bootstrap pushes workflow files). The
    script checks the scopes before it changes anything. Classic, because the factory repository doesn't exist yet
    when the bootstrap creates it.
- **The runner entry point** on the same VM: `C:\aif-lifecycle\app` (this folder), `venv\` with `requirements.txt`, and
  `runner.json` with `AIF_FACTORY_API_URL`, `AIF_FACTORY_FOLDER`, `AIF_KEY_VAULT_NAME` and
  `AIF_FACTORY_API_KEY_NAME` (the VM's managed identity reads the key). The ops repository gets variable
  `AIF_LIFECYCLE_RESULTS_URL` (`https://<app>.azurewebsites.net/api/v1/runner/results`); the result is signed with
  `AIF_LIFECYCLE_EVENT_SECRET`.
- One management runner and the Factory API's catalog lock serialize every Factory API call, so run long operations
  (runtime deploys) one at a time: a confirm that waits behind another long call can find its API review expired and
  is rejected (409), never retried.
- Requests travel as workflow inputs, which anyone with read access to the ops repository can see: reviews and catalog
  IDs, never secrets. The Function signs each request with the event secret and an expiry (`AIF_RUNNER_TIMEOUT_SECONDS`);
  the runner refuses a request it can't verify, one that expired, or one whose workflow inputs differ from it. The run
  name ends in `<action>-<nonce>`, so only the run of the pending call can end it. A confirmation is submitted once (a
  re-run of its job does nothing); only the result post is retried. `install-lifecycle-runner.ps1` removes inherited
  rights so the runner account can read and run the install but never change it, and aif-ops runs Python with `-P`
  so the job's working folder can't stand in for the installed code.

## Consumer copy

A consumer repo copies this folder to `aifactory-usecase-code/10-azure-function/12_func_aifactory_lifecycle/` and the
workflow templates from `workflows/` to its `.github/workflows/`, then adds its own `settings.<consumer>.json`.

Upgrading a copy from before the longer Factory API timeouts: set `AIF_RUNNER_TIMEOUT_SECONDS` to 4200 (or remove it)
in `settings.<consumer>.json` and redeploy (the Bicep replaces all app settings), copy `workflows/aif-ops.yml` to the
ops repository again, then reinstall the runner entry point with `scripts/install-lifecycle-runner.ps1`.
