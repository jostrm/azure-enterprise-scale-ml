# AI Factory lifecycle Function: SDK setup, identities and operations

The [README](README.md) describes the template. This page puts every secret, identity and step of the complete
solution in one place, with examples you can copy. All names and IDs below are examples (`contoso`, dummy GUIDs):
replace them with your own.

Use `AIF_BACKEND=sdk` for **Consumer → L1 Python ESAF SDK → L2 Factory API**: one Function confirmation invokes
one `esaf` method, which sends one approved POST to `/api/v1/esaf/<scenario>`. The Function's prepare is a
**scope approval**, not a live Azure deployment review. L2 owns the underlying reviews, configuration, enrollment,
deletion authorization, dispatch and retries. `AIF_BACKEND=rest` remains the legacy per-step alternative.

| Example | Meaning |
|---|---|
| `contoso` | The home factory. Its project001 hosts the Function, its common resource group hosts the management VM |
| `contoso-ai-sdc-dev` | The factory the Function creates and changes (FactoryId: prefix `contoso-ai`, Sweden Central, dev) |
| `aiflc-prj001-sdc-dev-abcde-001` | The Function app, in `contoso-esml-project001-sdc-dev-001-rg` |
| `dsvm-cmn-sdc-dev-001` | The management VM: Factory API, management runner, lifecycle runner entry point |
| `kv-p001-sdc-dev-abcde01` | The project Key Vault (RBAC) that holds every secret |
| `contoso/aif-ops` | The ops repository: `aif-ops.yml`, `aif-event-relay.yml`, `aif-dummy-step.yml` |
| `contoso/aif-factory-contoso-ai` | The factory repository the Factory API creates and writes |
| `11111111-1111-1111-1111-111111111111` | The factory subscription |
| `22222222-2222-2222-2222-222222222222` | The Entra app of the Function (App Service authentication) |

## Quick start

1. **Secrets.** Create these six values once. None of them ever goes into a settings file, a workflow input or a log.

   | Secret | Where | Value |
   |---|---|---|
   | `aif-lifecycle-event-secret` | Key Vault | A long random string: signs events, runner results and queued messages |
   | `AIF_LIFECYCLE_EVENT_SECRET` | Ops repository secret | The same value as `aif-lifecycle-event-secret` |
   | `aif-lifecycle-github-token` | Key Vault | A GitHub token with Actions read and write on the ops repository only |
   | `aif-factory-api-key` | Key Vault | A long random string: the Factory API's `X-API-Key` |
   | `aif-factory-api-gh-token` | Key Vault | A classic GitHub PAT with `repo`, `workflow` and `read:org` for the Factory API host |
   | Function key | App Service (created for you) | Read it with `az functionapp keys list` when you call the Function |

   ```powershell
   $subscription = '11111111-1111-1111-1111-111111111111'
   $kv = 'kv-p001-sdc-dev-abcde01'
   $secret = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
   $expires = (Get-Date).ToUniversalTime().AddYears(1).ToString('yyyy-MM-ddTHH:mm:ssZ')
   az keyvault secret set --subscription $subscription --vault-name $kv --name aif-lifecycle-event-secret --value $secret --expires $expires --output none
   gh secret set AIF_LIFECYCLE_EVENT_SECRET --repo contoso/aif-ops --body $secret
   $secret = $null
   ```

2. **Deploy** the Function into project001 over the factory's VPN, with `settings.contoso.json` (copied from
   `settings.example.json`, no secret values):

   ```powershell
   .\deploy.ps1 -SettingsFile .\settings.contoso.json -WhatIf
   .\deploy.ps1 -SettingsFile .\settings.contoso.json
   ```

   Use a dedicated Function app: deployment replaces every function in that app. Keep its name outside purple's
   `func-prj<NNN>-...` pattern so project deployments do not treat it as the project's managed Function.
   The template uses Flex Consumption, a private endpoint and VNet integration; its separate /27-or-larger
   integration subnet must be delegated to `Microsoft.App/environments`, not occupied by Container Apps or private
   endpoints. Deployment and calls need the VPN/private DNS. Flex starts timers without Always On.

3. **Call it.** Every lifecycle route needs the function key and an Entra token with the app role
   `Lifecycle.Operator`:

   ```powershell
   $base = 'https://aiflc-prj001-sdc-dev-abcde-001.azurewebsites.net/api'
   $key = az functionapp keys list --subscription $subscription -g contoso-esml-project001-sdc-dev-001-rg -n aiflc-prj001-sdc-dev-abcde-001 --query functionKeys.default -o tsv
   $token = az account get-access-token --subscription $subscription --resource api://22222222-2222-2222-2222-222222222222 --query accessToken -o tsv
   $h = @{ 'x-functions-key' = $key; Authorization = "Bearer $token" }

   Invoke-RestMethod "$base/v1/health"                                   # anonymous: status, backend, executor, deletes

   # Scenario 3: add project002 to scale set 001
   $op = Invoke-RestMethod "$base/v1/lifecycle/add-or-update-project/prepare" -Method Post -Headers $h `
         -ContentType application/json -Body '{"projectId":"contoso-ai-esml-project002-sdc-dev-001-rg"}'
   $op = Invoke-RestMethod "$base/v1/operations/$($op.operationId)" -Headers $h   # repeat until a step awaits you
   $step = $op.steps[$op.currentStep]
   $step.preview                                                         # plan, resource groups, blockers, canExecute
   Invoke-RestMethod "$base/v1/operations/$($op.operationId)/confirm" -Method Post -Headers $h `
         -ContentType application/json -Body (@{ confirmationToken = $step.preview.confirmationToken } | ConvertTo-Json)
   ```

   With `sdk`, there is one `scenario` step: confirm once to configure and deploy through `esaf.upsert_project`.
   Read the operation until it succeeds or stops. Definite submission refusals fail the operation; unknown outcomes
   (transport/server failures or missing job receipts) become `uncertain`: inspect the Factory API before another
   attempt. The Function never resubmits; L2 can perform bounded retries inside an accepted job. The `rest`
   alternative still confirms configure and deploy separately.

<details>
<summary><b>More info: every secret and identity</b></summary>

### Secrets

| Secret or credential | Lives in | Read by | Used for | Rotate |
|---|---|---|---|---|
| Function key | App Service | The caller | `x-functions-key` on lifecycle routes | `az functionapp keys set` with a new value, then update callers |
| Entra access token | Issued per call | The caller | `Authorization: Bearer`, audience `api://<authClientId>`, app role `Lifecycle.Operator` | Short-lived; nothing to rotate |
| `aif-lifecycle-event-secret` | Key Vault (`AIF_EVENT_SECRET_NAME`) | The Function's managed identity | Checks `X-Hub-Signature-256` on `/api/v1/github/events` and `/api/v1/runner/results`; signs runner requests and queued events | Store `new,old` (two comma-separated values), update the repository secret to `new`, then store `new` alone |
| `AIF_LIFECYCLE_EVENT_SECRET` | Ops repository secret | `aif-event-relay.yml`, `aif-ops.yml` | Signs relayed events and runner results; checks the Function's signed requests | One value, no commas |
| `aif-lifecycle-github-token` | Key Vault (`AIF_GITHUB_TOKEN_NAME`) | The Function's managed identity | `workflow_dispatch` of `aif-ops.yml` / `aif-dummy-step.yml` and polling run status in the ops repository | A fine-grained token or GitHub App limited to the ops repository's Actions |
| `aif-factory-api-key` | Key Vault | The management VM's managed identity | The Factory API's `X-API-Key`: `start-api.ps1` reads it at every start, the runner at every call (`runner.json` `AIF_FACTORY_API_KEY_NAME`) | New value, then restart the `AIFactoryApi` task |
| `aif-factory-api-gh-token` | Key Vault | `install-factory-api-host.ps1` (VM identity) | `gh auth login` for the Factory API's Windows user (SYSTEM): the API creates the factory repository, pushes workflows and dispatches runs | Store the new PAT, run the installer again |
| Runner registration token | Nowhere | `register-management-runner.ps1` | Registers the management runner; valid one hour, passed as a protected run-command parameter | Not stored |

Local development only: `AIF_EVENT_SECRET`, `AIF_GITHUB_TOKEN` and `AIF_FACTORY_API_KEY` may hold plain values in the
git-ignored `local.settings.json`. In Azure, settings name secrets; the Function never takes a value from a setting
that still holds an unresolved `@Microsoft.KeyVault(...)` reference (503 `configuration-invalid`).

What is never secret, and therefore never protected: runner requests travel as workflow inputs, which anyone who
can read the ops repository can see. They hold reviews and catalog IDs only, signed with an expiry.

### Identities and roles

| Identity | Role | Scope | Why |
|---|---|---|---|
| The Function's managed identity | Storage Blob Data Owner, Storage Table Data Contributor, Storage Queue Data Contributor | The project storage account | Identity-based `AzureWebJobsStorage`, the operation table, the event queue (`infra/roles.bicep`) |
| The Function's managed identity | Key Vault Secrets User | The project Key Vault | The event secret and the GitHub token |
| The management VM's managed identity (the Factory API's own `az` profile, signed in with `az login --identity`) | Owner | The factory subscription | The bootstrap creates resource groups, identities, roles and networks |
| The same identity | Microsoft Graph app roles `Group.ReadWrite.All`, `User.Read.All` | Tenant (granted by a Privileged Role Administrator) | The bootstrap creates the team group and adds its members |
| The same identity | Key Vault Secrets User | The project Key Vault | `aif-factory-api-key`, `aif-factory-api-gh-token` |
| The same identity | Reader | Every virtual network in another subscription that is peered with a virtual network in the factory subscription, for example `vnet-contoso-access-hub-sdc-001` | The bootstrap's network-foundation stage reads every network in the factory subscription and follows their peerings to check address overlaps. Without it the stage is blocked by an ARM 403 (see Troubleshooting) |
| Operators | App role `Lifecycle.Operator` | The Function's Entra app | Lifecycle routes answer 403 `missing-role` without it |

```powershell
# Reader on one peered hub network only (least privilege), for the management VM's identity
$vmIdentity = az vm show --subscription $subscription -g contoso-esml-common-sdc-dev-001 -n dsvm-cmn-sdc-dev-001 --query identity.principalId -o tsv
az role assignment create --subscription 33333333-3333-3333-3333-333333333333 --assignee-object-id $vmIdentity --assignee-principal-type ServicePrincipal --role Reader `
   --scope /subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/contoso-connectivity/providers/Microsoft.Network/virtualNetworks/vnet-contoso-access-hub-sdc-001
```

List the peerings that need it:

```powershell
az network vnet list --subscription 11111111-1111-1111-1111-111111111111 `
   --query "[].virtualNetworkPeerings[].remoteVirtualNetwork.id" -o tsv | Where-Object { $_ -notmatch '/11111111-1111-1111-1111-111111111111/' }
```

</details>

<details>
<summary><b>More info: the management VM (Factory API host and runner)</b></summary>

The Factory API answers catalog, deployment and ESAF routes on loopback only, so the hosted Function never calls
those routes over the network: it dispatches `aif-ops.yml` to a management runner on the **same host as the API**,
which calls the explicitly configured API loopback URL and posts a
signed result back. Keep the VM outside every factory the Function can create or delete, and protect its scale set
with `AIF_PROTECTED_IDS`.

`inprocess` is only for a local Function on that API host. The L1 submission returns an ESAF job receipt; L2
continues orchestration independently, and subsequent runner calls only read its status. The legacy REST mode
can still require long prepare/confirm calls. The runner's API timeout defaults to 2700 seconds per call; its
60-minute workflow job is bounded by the Function's 4200-second hand-off timeout. A timed-out confirmation is
uncertain, never a reason to submit the facade method again. `127.0.0.1:8765` below is an example, not discovery
of a live endpoint; use the operator-configured host URL.

1. **No manual Azure CLI login**: the installer gives the Factory API its own `az` profile (`C:\aif-api\azure-cli`)
   and signs it in with the VM's managed identity at every start, so an Azure DevOps agent or another job running as
   SYSTEM, which clears SYSTEM's shared `az` profile after its Azure CLI tasks, cannot log the API out.
2. **The Factory API**, a pinned AI Factory Config Wizard release in API-only mode, as SYSTEM:

   ```powershell
   az vm run-command invoke --subscription $subscription -g contoso-esml-common-sdc-dev-001 -n dsvm-cmn-sdc-dev-001 --command-id RunPowerShellScript `
      --scripts '@scripts/install-factory-api-host.ps1' --parameters KeyVaultName=kv-p001-sdc-dev-abcde01 Release=v0.47.32 SubscriptionId=<factory subscription ID>
   ```

   Pass `Release` explicitly: v0.47.32 or later federates the OIDC subject GitHub signs for repositories created after
   July 15, 2026, and reads a new Entra group back until Microsoft Graph has replicated it.
   That historical release example is **not** proof of ESAF compatibility. SDK mode additionally needs the live
   `/api/v1/esaf/*` facade and scope guards described below; select an operator-verified compatible build.
   Logs: `C:\aif-api\logs`. The API's `folder` is the factory repository's `azurefactory` subfolder, for example
   `C:\aif\aif-factory-contoso-ai\azurefactory`.
3. **The management runner** for the ops repository, with a label of its own (never the factory runner's label):

   ```powershell
   .\scripts\register-management-runner.ps1 -Repository contoso/aif-ops -SubscriptionId 11111111-1111-1111-1111-111111111111 `
      -ResourceGroup contoso-esml-common-sdc-dev-001 -VmName dsvm-cmn-sdc-dev-001
   ```

4. **The lifecycle runner entry point** at a pinned commit of this template:

   ```powershell
   az vm run-command invoke --subscription $subscription -g contoso-esml-common-sdc-dev-001 -n dsvm-cmn-sdc-dev-001 --command-id RunPowerShellScript `
      --scripts '@scripts/install-lifecycle-runner.ps1' `
      --parameters Commit=<40-character sha> FactoryFolder=C:\aif\aif-factory-contoso-ai\azurefactory KeyVaultName=kv-p001-sdc-dev-abcde01
   ```

   It writes `C:\aif-lifecycle\runner.json`:

   ```json
   {
     "AIF_FACTORY_API_URL": "http://127.0.0.1:8765",
     "AIF_FACTORY_FOLDER": "C:\\aif\\aif-factory-contoso-ai\\azurefactory",
     "AIF_KEY_VAULT_NAME": "kv-p001-sdc-dev-abcde01",
     "AIF_FACTORY_API_KEY_NAME": "aif-factory-api-key",
     "AIF_ALLOW_REAL_DELETES": "false"
   }
   ```

   `AIF_ALLOW_REAL_DELETES` stays `false` unless you really want the runner to send deletes to the Factory API.

</details>

<details>
<summary><b>More info: the ops repository and the event relay</b></summary>

- Copy `workflows/aif-ops.yml`, `workflows/aif-event-relay.yml` and `workflows/aif-dummy-step.yml` to the ops
  repository's `.github/workflows/` on its default branch. The factory repository holds only what the Factory API
  writes there: the API refuses to dispatch its own runs while another workflow of the factory repository runs.
- Repository variables and secret:

  ```powershell
  gh variable set AIF_LIFECYCLE_EVENTS_URL  --repo contoso/aif-ops --body https://aiflc-prj001-sdc-dev-abcde-001.azurewebsites.net/api/v1/github/events
  gh variable set AIF_LIFECYCLE_RESULTS_URL --repo contoso/aif-ops --body https://aiflc-prj001-sdc-dev-abcde-001.azurewebsites.net/api/v1/runner/results
  # AIF_LIFECYCLE_EVENT_SECRET: see Quick start
  ```

- Keep fork pull-request workflows off and limit collaborators to trusted admins: any workflow that targets the
  management label runs on the VM that reaches the Factory API.
- The relay forwards `workflow_run` events of the same repository, signed, to the Function's private endpoint. The
  Function deduplicates on `X-GitHub-Delivery`; its timer polls runs whose events are late.

Function settings for the real API (in `settings.contoso.json` `appSettings`):

```json
{
  "AIF_BACKEND": "sdk",
  "AIF_EXECUTOR": "github-runner",
  "AIF_EVENT_PROCESSING": "queue",
  "AIF_DELETES": "simulate",
  "AIF_SELF_PROJECT_ID": "contoso-esml-project001-sdc-dev-001-rg",
  "AIF_PROTECTED_IDS": "contoso-sdc-dev-001",
  "AIF_KEY_VAULT_NAME": "kv-p001-sdc-dev-abcde01",
  "AIF_EVENT_SECRET_NAME": "aif-lifecycle-event-secret",
  "AIF_GITHUB_REPOSITORY": "contoso/aif-ops",
  "AIF_GITHUB_TOKEN_NAME": "aif-lifecycle-github-token",
  "AIF_OPS_WORKFLOW": "aif-ops.yml",
  "AIF_RUNNER_TIMEOUT_SECONDS": "4200",
  "AIF_REVIEW_TTL_SECONDS": "600"
}
```

`deploy.ps1` sets `AIF_STORE=table` and `AIF_TABLE_ACCOUNT` (the project storage account) itself. With
`"authClientId": "22222222-2222-2222-2222-222222222222"` at the top of the settings file it also turns App Service
authentication on and sets `AIF_REQUIRED_ROLE`. Register the app first:
`.\scripts\register-entra-app.ps1 -DisplayName aif-lifecycle-func-contoso -Operator operator@contoso.com`.

</details>

<details>
<summary><b>More info: the six scenarios</b></summary>

`POST /api/v1/lifecycle/<scenario>/prepare` answers 202 with `Location` (the operation) and `Retry-After`. The
Function resolves the target and prepares one scope approval for `sdk`. No mutating facade call is made until you
confirm. The SDK submits one scenario and returns an `EsafJob(kind="esaf")`; L2 orchestrates the actual operations.

| # | Route segment | Body | One SDK invocation |
|---|---|---|---|
| 1 | `init-factory` | `{"factoryId":"contoso-ai-sdc-dev","bootstrapConfig":{...}}` | `esaf.init_factory(creation_request=...)`: save the factory and start server-owned full bootstrap |
| 2 | `add-scaleset` | `{"scalesetId":"contoso-ai-sdc-dev-002","scaleSet":{"vnetCidr":"10.20.64.0/18","maxProjects":7}}` | `esaf.add_scale_set("002", "dev", cidr=...)`: register, enroll and deploy common resources |
| 3 | `add-or-update-project` | `{"projectId":"contoso-ai-esml-project002-sdc-dev-001-rg","settings":{...}}` | `esaf.upsert_project("002", scale_set="001", environment="dev", settings=...)` |
| 4 | `delete-project` | `{"projectId":"contoso-ai-esml-project002-sdc-dev-001-rg"}` | `esaf.delete_project("002", scale_set="001", environment="dev", ...)` |
| 5 | `delete-scaleset` | `{"scalesetId":"contoso-ai-sdc-dev-002"}` | `esaf.delete_scale_set("002", environment="dev")` |
| 6 | `delete-factory` | `{"factoryId":"contoso-ai-sdc-dev"}` | `esaf.delete_factory()`: every scale set must be in the requested environment |

Every call also receives an explicit session with the configured folder and resolved factory ID; no global session
is used by the Function. Scale-set/project methods require `dev`, `stage` or `prod`; the Function maps Azure `test`
to catalog `stage`. `scaleSet` can additionally override `subscriptionId`, `tenantId` and `orchestrator`; omitted
values come from the factory. SDK mode rejects unsupported `scaleSet` fields such as `commonSubnets`, rather than
ignoring them. Scenario 2 does not implicitly create project001; call Scenario 3 separately for that project.
Scenario 4 preserves the Function defaults `includeProjectSubnets=true` and `includeKeyvaultAndResourceGroup=true`,
passing both explicitly instead of inheriting server defaults.

With `rest`, the legacy steps remain: Scenario 1 configure/bootstrap, Scenario 2 configure/add-project001/enroll/
deploy-common/deploy-project001, Scenario 3 configure/deploy-project, and one delete step for Scenarios 4-6.

Scenario 1 against the real API: `bootstrapConfig` is the API's full bootstrap configuration, for example

```json
{
  "coordination_mode": "single-writer", "access_hub_mode": "integrated", "setup_hub_access": true,
  "subscription_id": "11111111-1111-1111-1111-111111111111", "tenant_id": "00000000-0000-0000-0000-000000000000",
  "repo_root": "C:\\aif\\aif-factory-contoso-ai", "github_repository": "contoso/aif-factory-contoso-ai",
  "team_member_email": "operator@contoso.com", "team_group_name": "contoso-ai-team",
  "dev_vnet_cidr": "10.20.0.0/18", "vpn_client_cidr": "172.31.250.0/24"
}
```

The API then runs repository-initialization, minimum-foundation, prerequisites, network-foundation, runner,
connection, provider-handoff, publication, common-deployment, project-deployment and complete by itself under that
one approval. New SDK jobs are followed through the outer ESAF status, not individual child workflow phases.
For saved legacy workflow jobs only, `awaiting-review` with `requires_review=true` stops the Function step with
`action_required` and the API's message.

Deletes depend on `AIF_DELETES`:

| `AIF_DELETES` | Scenarios 4-6 |
|---|---|
| `refuse` (default) | 403 `deletes-disabled` before anything is recorded or sent |
| `simulate` | The full flow on a mock backend over a read-only copy of the real catalog, with `aif-dummy-step.yml` runs; the Factory API never sees a delete |
| `allow` | Real deletes, and only if the runner's `runner.json` also has `AIF_ALLOW_REAL_DELETES` `true` |

Confirm a delete with its phrase:

For `sdk` the Function phrase is `DELETE <readable target ID>`; L1 submits `approved=true` only after that approval.
L2 owns reviewed confirmation phrases and deletion grants. Do not duplicate those calls in the Function or L1.

```powershell
$step = (Invoke-RestMethod "$base/v1/operations/$id" -Headers $h).steps[0]
$body = @{ confirmationToken = $step.preview.confirmationToken; confirmationPhrase = $step.preview.confirmationPhrase } | ConvertTo-Json
Invoke-RestMethod "$base/v1/operations/$id/confirm" -Method Post -Headers $h -ContentType application/json -Body $body
```

</details>

<details>
<summary><b>More info: reading an operation</b></summary>

`GET /api/v1/operations/{id}` (shortened):

```json
{
  "operationId": "a1b2c3d4-0000-4000-8000-000000000001",
  "scenario": "add-or-update-project", "scenarioNumber": 3,
  "target": "contoso-ai-esml-project002-sdc-dev-001-rg",
  "status": "running", "backend": "sdk", "executor": "github-runner", "currentStep": 0,
  "steps": [
    {"index": 0, "name": "add-or-update-project", "kind": "scenario", "status": "running",
     "preview": {"plan": ["Deploy ..."], "affectedResourceGroups": [], "blockers": [], "canExecute": true,
                 "expiresAt": "2026-01-01T10:10:00+00:00", "confirmationToken": null},
     "runs": [{"target": "api-catalog-5e6f7a8b-0000-4000-8000-000000000002", "status": "in_progress",
               "url": "https://github.com/contoso/aif-factory-contoso-ai/actions/runs/1234567890", "source": "runner"}],
     "waitingFor": {"action": "status", "since": "2026-01-01T10:05:00+00:00"}}
  ],
  "history": [{"at": "2026-01-01T10:04:00+00:00", "event": "confirming", "step": 0, "detail": "add-or-update-project"}]
}
```

- Status: `pending`, `preparing`, `awaiting_confirmation`, `confirming`, `running`, then one of `succeeded`,
  `failed`, `uncertain`, `expired`, `blocked`.
- `waitingFor` (runner executor): the Function handed a call to `aif-ops.yml` and waits for its signed result.
  A review that never reports fails with `runner-timeout`; a confirm that never reports becomes `uncertain`.
- `uncertain` is final and never retried: check the Factory API's job or workflow before anything else.
- A failed step carries `failure.runUrl` and the last lines of the run's log (`failure.logExcerpt`).

Errors are `application/problem+json`, for example:

```json
{"type": "urn:aifactory:lifecycle:problem:already-exists", "title": "The target already exists", "status": 409,
 "code": "already-exists", "detail": "Scale set contoso-ai-sdc-dev-002 is already in the catalog.",
 "correlationId": "c0ffee00-0000-4000-8000-000000000003", "instance": "/api/v1/lifecycle/add-scaleset/prepare"}
```

</details>

<details>
<summary><b>More info: the esaf SDK facade</b></summary>

`adapters/sdk_backend.py` implements the backend port directly: it no longer inherits the REST step-to-call
orchestration. The composition root selects it for `AIF_BACKEND=sdk` both in-process and on the management runner.
The Function retains its safety and persistence layer. L1 is only the Python HTTP client; lifecycle orchestration
runs in L2, not in the SDK or a Function background thread.

On the API host:

```python
from azurefactory import AzureFactoryClient, esaf

client = AzureFactoryClient(base_url="http://127.0.0.1:8765", api_key=api_key)  # key read from Key Vault
folder = r"C:\aif\aif-factory-contoso-ai\azurefactory"
session = esaf.Session(folder, client, factory="<resolved factory ID>")
# This call IS approval and can mutate Azure. It is not a read-only test.
job = esaf.upsert_project("002", "dev", scale_set="001", settings={}, session=session)
print(job.id)
print(job.status())  # one read; no polling thread required
```

The Function persists the returned ID, `job_kind="esaf"` and selected factory. `EsafJob.status()` performs
`GET /api/v1/esaf/jobs/{id}?folder=...` and can be reconstructed after a Function restart or separate runner invocation.
`accepted`, `preparing`, `confirming`, `running` and `retrying` keep the operation active; `succeeded` completes it,
while `blocked`, `failed` and `interrupted` fail it with the server message. A child's failure is not terminal while
the outer job is retrying. Saved `catalog`, `workflow` and `factory-deletion` handles still use their original
status endpoints, including records labelled `apply_project`; no scenario is redispatched to read them.

`job.wait()` defaults to one-second polling in direct SDK clients. The Function does not call `wait()` or hold an
invocation open: its existing reconciler uses `AIF_POLL_AFTER_SECONDS` (default 120 seconds, also bounded by its
timer/runner scheduling). L2 owns bounded retries inside the accepted job (currently two by default); the Function
does not submit another job or duplicate prepare/confirm steps.

Use the exact SDK pin in `requirements.txt`; an older installed SDK does not acquire new methods merely because
purple main changed. Update both the Function and runner packages together. Reconcile/finish old SDK operations
before upgrading; unconfirmed old step requests are refused with `sdk-operation-upgrade`, not replayed.
`upsert_project` is the canonical scenario method; `apply_project` remains a compatibility alias for existing callers.

**A running, compatible L2 API is required**, on the same host as L1. It must provide the six `/api/v1/esaf/*`
submission routes and durable job GET route, enforce exact environment/scale-set/project selection, extend
enrollment for newly registered project groups and enforce deployment/deletion guards before dispatch.
The thin SDK no longer performs these reviews locally. A missing facade route fails with `sdk-config` and no
legacy-route fallback. **Update/verify the API first**, then the Function and runner, with real deletes refused.
Installing the SDK pin does not upgrade the server or prove its installed version.

Typed config/auth/blocked/conflict submission refusals fail the Function operation before an accepted job.
Transport/server failures and malformed receipts are uncertain, never success or an automatic resubmission.
After acceptance, follow the server's outer job status; inspect any partial changes before preparing another operation.

### Read-only consumer check

Read `GET /api/v1/health`, `GET /api/v1/operations` and `GET /api/v1/operations/{id}` on the configured Function endpoint
with the required authentication; do not infer the installed SDK from the health backend label. On the API host,
`GET /health`, `GET /openapi.json`, `client.catalog_list(folder)` and an existing `job.status()` are reads.
Use the configured API URL/key; never probe unrelated API instances. Check the OpenAPI paths for ESAF support,
and verify installed package/build provenance separately. The Function's SDK `/prepare` only
produces a scope approval and does not prove that the API will permit a deployment. Do not call any of the six
facade methods for a read-only check, including `upsert_project` with empty settings: it deploys.
Check the installed Factory API's support for the consumer's Azure DevOps organization before live execution;
the Spider consumer's cross-tenant ADO setup has previously been refused by catalog runtime.

</details>

<details>
<summary><b>More info: troubleshooting</b></summary>

| Symptom | Cause | What to do |
|---|---|---|
| 503 `catalog-pending` on the first prepare | The Function has no catalog snapshot yet | Wait a minute, or `POST /api/v1/catalog/refresh` |
| 403 `deletes-disabled` | `AIF_DELETES=refuse` (the default) | Set `simulate` to rehearse; `allow` only for real deletes |
| 403 `protected-target` | The target contains `AIF_SELF_PROJECT_ID` or an `AIF_PROTECTED_IDS` entry | By design: the Function never deletes its own host |
| A step fails with `runner-timeout` | No `aif-ops` result arrived in `AIF_RUNNER_TIMEOUT_SECONDS` | Check the ops repository's runs and that the management runner is online |
| The first COMMON run fails at `azure/login`: `AADSTS700213: No matching federated identity record found for presented assertion subject 'repo:OWNER@OWNER_ID/REPO@REPO_ID:environment:Dev'` | GitHub repositories created after July 15, 2026 use the immutable OIDC subject (owner and repository IDs), and that format can't be turned off for them. Factory API v0.47.31 and older bootstrap the federated credential with the classic subject `repo:OWNER/REPO:environment:Dev` | Bootstrap with Factory API v0.47.32 or later: the bootstrap then federates the subject GitHub signs (`sub_claim_prefix` of `gh api repos/contoso/aif-factory-contoso-ai/actions/oidc/customization/sub`). A factory bootstrapped before keeps its classic credential. Don't add a second federated credential by hand: the ownership handoff treats it as an unregistered resource |
| A deploy review fails with `upstream-timeout` (or its confirm becomes `uncertain`) | The Factory API call took longer than `AIF_FACTORY_API_TIMEOUT_SECONDS` on the runner | Keep it at the default 2700 s or more (a machine environment variable on the VM overrides `runner.json`, which the installer rewrites), `aif-ops.yml`'s job timeout above it and `AIF_RUNNER_TIMEOUT_SECONDS` above that. Never retry an uncertain confirm: check the API's jobs first |
| A step is `uncertain` | A confirm's outcome is unknown | Never retry it: check the Factory API's job or creation workflow first |
| Scenario 1 stops as `uncertain` after a verified stage, diagnostic `stage-execution-interrupted`, phase `authorization-continuation` | The API's own continuation failed before the next stage started, for example the network-foundation review got an ARM 403 reading a peered network in another subscription | Grant the missing access (Reader on that network), then recover at the verified boundary below |
| The same stop after `publication` (single-writer), and a read-only `POST /api/v1/factory-catalog/prepare` with `action: deploy` for the scale set shows "Bootstrap ownership handoff blocked: unregistered actual resources lack bootstrap receipt proof" | The private DNS zones' SOA records and the runner's registration run command have no creation receipt. The whole-workflow continuation pauses for these consents before PROJECT, not before COMMON | Recover at the verified boundary, then confirm `bootstrap-dns-soa-preservation` (stage `common-deployment`) and `bootstrap-preservation` (the runner's `MDE.Linux` extension and its registration command), then prepare-next and start. The runner review needs the Defender extension: on a subscription with Defender for Servers it appears about an hour after the runner VM is created |

**Legacy workflow recovery only:** the examples below describe the older workflow contract. For a new ESAF job,
first inspect its outer status and L2 diagnostics; do not recover or restart a child while L2 is still active or
retrying. A new accepted ESAF failure is recorded as `failed`, not as an unknown submission outcome.

**Recover a legacy whole-workflow bootstrap at its verified boundary** (on the API host, loopback, `X-API-Key`;
nothing runs until the last call):

```powershell
$api = 'http://127.0.0.1:8765/api/v1/creation/workflows'; $id = '<workflow id>'
$folder = 'C:\aif\aif-factory-contoso-ai\azurefactory'
$status = Invoke-RestMethod "$api/$id`?folder=$([uri]::EscapeDataString($folder))" -Headers $apiHeaders
$review = Invoke-RestMethod "$api/$id/prepare-verified-boundary-recovery" -Method Post -Headers $apiHeaders -ContentType application/json -Body (@{
    contract_version = 1; folder = $folder; factory_id = $status.scope.factory_id
    expected_revision = $status.source_revision; expected_authorization_hash = $status.authorization.authorization_hash
    resolution = 'review-fresh-next-stage-after-interrupted-continuation' } | ConvertTo-Json)
# Check: can_execute, no blockers, review.next_stage, review.cloud_writes = false. Confirm within 5 minutes:
Invoke-RestMethod "$api/$id/confirm-verified-boundary-recovery" -Method Post -Headers $apiHeaders -ContentType application/json `
    -Body (@{ folder = $folder; confirmation_id = $review.confirmation_id; input_hash = $review.input_hash } | ConvertTo-Json)
# A fresh review of the next stage with a new bounded authorization for the remaining stages:
$next = Invoke-RestMethod "$api/$id/prepare-next" -Method Post -Headers $apiHeaders -ContentType application/json -Body (@{ folder = $folder } | ConvertTo-Json)
# Check: can_execute, no blockers, review.workflow_authorization (stages, resumption, target resource groups, expires_at).
Invoke-RestMethod "$api/start" -Method Post -Headers $apiHeaders -ContentType application/json -Body (@{
    folder = $folder; workflow_id = $id; confirmation_id = $next.confirmation_id
    authorization_hash = $next.review.workflow_authorization.authorization_hash } | ConvertTo-Json)
```

The verified stages are not repeated. The Function's scenario 1 operation stays `failed` (terminal) and does not
follow the recovered workflow: watch the workflow on the API, then `POST /api/v1/catalog/refresh` before the next
scenario.

</details>
