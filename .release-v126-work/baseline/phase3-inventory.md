# Phase 3 step 1: inventory (base ebd300db), written before the compaction

## Idle waits: 91 sleeps in 27 script and pipeline files (Bash, PowerShell, YAML; tests excluded)

Classes: pure idle 24, readiness poll 50 (intervals 2 to 60 s), failure backoff 14, rate-limit pacing 3.
Full list with file and line: /home/user/results/phase1/sleeps-classified.json.

| File | Pure idle (seconds) | Readiness polls (interval s) | Failure backoff | Pacing |
|---|---|---|---|---|
| github-actions/infra-project-phase.yml | 5: 15, 10, 300, 600 (10-min loop), 300 | 8: 10, 10, 10, 20, 20, 2, 10, 10 | 2 | |
| azure-devops/.../job-2-genai-services.yaml | 6: 300, 600 (10-min loop), 15, 30, 30, 600 or 900 (initial wait) | 8: 10, 10, 10, 10, 60, 60, 20, 20 | 2 | |
| scripts/delete-services-if-disabled.sh | 6: 10, 15, 15, 15, 15, 300 | 5: 15, 5, 5, 5, 5 | 2 | |
| scripts/ado/79_Purge_If_SoftDeleted_71_72_After5minutes.sh | 1: 300 | | | |
| scripts/ado/74_Cleanup_CapabilityHosts.sh | 2: 60, 60 | 1: 15 | 1 | |
| scripts/delete-caphost-and-foundry-and-its-subnet.sh | 2: 10, 60 | | 1 | |
| scripts/delete-capHost-command.sh | 1: 60 | | | |
| bootstrap/lib/create-new-aifactory-scaleset.sh | | 12: 2 to 30 | 2 | |
| github-actions/03a-GH-create-or-update-github-variables.sh | | | | 2 |
| 16 other files | 1 (test dummy step) | 16 | 5 | 1 |

The pure idle waits on the scenario paths:

| Wait | Where | Fixed seconds | Real condition to poll instead |
|---|---|---|---|
| "69-Rehydrate" before the account update | GHA phase file line 3820 (every first Foundry creation: scenarios 1 and 3) | 300 | Foundry account `provisioningState` is Succeeded; the next step already polls the capability host, and 69b retries `RequestConflict` |
| Initial wait before the first Foundry deployment status check | ADO job-2 line 5006 | 600 without network injection, 900 with | The deployment's `provisioningState` (poll from the start) |
| Subnet release after a Foundry purge (06c2) | GHA line 1945, ADO line 2609 (delete and re-create paths) | 600 | The agent subnet has no service association link left |
| Soft-delete settle before purge | GHA line 1806, ADO line 2225, 79_Purge...sh:47, delete-services-if-disabled.sh:2631 | 300 each | The deleted account is listed by `az cognitiveservices account list-deleted` |
| Key Vault firewall rule propagation | GHA lines 908 and 1289 | 15 and 10 | A data-plane read of the vault succeeds |
| ACR network rule propagation and image check | ADO job-2 lines 2798, 2897, 2937 | 15, 30, 30 | `az acr repository show` answers |
| Project capability host gone before the account capability host is deleted | delete-capHost-command.sh:91, delete-caphost-and-foundry-and-its-subnet.sh:645, 74_Cleanup_CapabilityHosts.sh:192,196 | 60 each | GET on the project capability host returns 404 |
| Private endpoint deletions settle | delete-services-if-disabled.sh:237,384,410,2196,2216; delete-caphost-and-foundry-and-its-subnet.sh:542 | 10 to 15 each | The private endpoint list no longer names them |

## Retry helpers per language

| Language | What exists | Verdict |
|---|---|---|
| Bash | `az_capture` in scripts/preflight.sh:537 (bounded attempts, linear backoff, transient classification: 429, 5xx, timeouts, throttling, connection reset; read-only calls). Otherwise inline loops: `for attempt in 1 2 3`, attempt-1/2/3 steps, `_wait_vnet_idle` defined twice (delete-services-if-disabled.sh:2705, delete-subnets-for-projects.sh:139) | Best existing one is `az_capture`; it has no jitter and does not print the last error with the attempt count |
| PowerShell | None. `Invoke-AzJson` is defined twice (Invoke-ProjectLakeAccess.ps1:49, prepareSeedingKeyVaultPrivateDns.ps1:33); shared module scripts/modules/pipelineFunctions.psm1 has no retry | A first helper is needed, in pipelineFunctions.psm1 |
| Python | bootstrap/lib/factory_lifecycle.py (`ThrottledReadHandler`, `throttled_read_delay`, state-read retry), scripts/deploy-integration-with-retry.py, scripts/deploy-capacity-resource.py, scripts/dashboard_usage.py `_retry_delay`, CLI `poll()` (cli.py:1966) | Several, in separately shipped units (bootstrap/lib is vendored by pink; the CLI is stdlib-only) |

## Self-heal and recovery that exists

GHA phase file and ADO job-2: delete capability hosts first (06a), delete services that were disabled (18), purge soft-deleted Foundry, hub and AML (18, 69-Purge), clean orphan role assignments (step plus scripts/cleanup-project-orphan-roles.py), AI Search capacity retry with region fallback (63b attempts 1 to 3), PostgreSQL and Container Apps attempts 1 to 3, `RequestConflict` wait in 69b, shared-private-link approval and re-delete, ADO scripts 71/72/73 (delete after error), 74 (capability hosts), 79 (purge). Lifecycle worker (factory_lifecycle.py): throttled reads, state-read retry, resumed deletions, single-writer claims.

Gaps to verify in source in phase 3 (candidates, not yet proven):
1. Soft-deleted Key Vault blocking a project's vault name: no `az keyvault recover`, `purge` or `list-deleted` anywhere in the workflows, pipelines, scripts or bootstrap, while vaults default to purge protection.
2. No shared retry around `az deployment sub create` for transient ARM errors (429, 5xx, `AnotherOperationInProgress`, `PrincipalNotFound`): only one script names `AnotherOperationInProgress`, one names `PrincipalNotFound`.
3. A failed or still-running deployment left behind under the same name is not detected before a re-run.

## Repeated az calls and checkout settings

- GHA infra-project-phase.yml: 157 inline `az` calls per phase job, 43 of them `az account set`; ADO job-2: 181 and 38.
- Checkout: GHA uses `actions/checkout@v4` with `submodules: true` or `recursive` (depth 1 by default). ADO `infra-project-genai.yaml` checks out with `submodules: recursive` and `fetchDepth: 0` in all 9 jobs (full history of the consumer repo and of the submodule), as do `gov-cross-charging.yaml` (3) and `stage-private-azure-mcp.yaml`; `add-factory-agent.yaml` already uses `fetchDepth: 1`; the common and gateway pipelines set no depth.
- Purple's own CI spends about 97 to 100 s per job in "Check out code" on main (run 43402589145), 4 jobs per push.

## CLI start-up (installed package, compiled bytecode, Python 3.12, sandbox under load)

`azurefactory --help`: median 103 ms (interpreter alone 15 ms), 167 modules imported, import total about 73 ms; `from azurefactory import esaf`: 79 ms. `urllib.request`, `http.client`, `email`, `dataclasses` and `inspect` load before any command runs. The client already passes a timeout (default 90 s) on every call; it builds a new opener per request.
