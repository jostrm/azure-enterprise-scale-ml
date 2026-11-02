---
id: lifecycle-function
status: observed
sources:
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/function_app.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/http_api.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/service.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/planner.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/resolver.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/guard.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/domain/ids.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/domain/operation.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/factory_api.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/rest_backend.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/sdk_backend.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/trackers.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/runner_backend.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/runner_protocol.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/runner.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/ports.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/composition.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/settings.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/function-app.bicep
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/workflows/aif-event-relay.yml
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/workflows/aif-dummy-step.yml
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/workflows/aif-ops.yml
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/install-lifecycle-runner.ps1
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/install-factory-api-host.ps1
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/simulated_deletes.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/README_More_Info.md
  - environment_setup/azurefactory-cli/src/azurefactory/esaf.py
tests:
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_ids.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_regions.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_operation_state.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_service_scenarios.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_events.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_adapter_parity.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_http_api.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_runner_executor.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_runner_cli.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_workflow_templates.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_api_host_installer.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_simulated_deletes.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_infra_template.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_esaf_scenarios.py
graph_symbols:
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/service.py::class:LifecycleService
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/domain/operation.py::class:Operation
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/factory_api.py::class:FactoryApiBackend
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/runner_backend.py::class:RunnerBackend
reviewed_source: 'a9c597fe + working tree; SDK facade integration observed 2026-11-02'
---
# Lifecycle Function

## Observed

A usecase template (`usecase_code/10-azure-function/12_func_aifactory_lifecycle`) that runs six lifecycle scenarios -
init factory, add scale set, add or update project, delete project, delete scale set, delete factory - as reviewed
operations over the Factory API. `AIF_BACKEND=sdk` calls one `azurefactory.esaf` method per scenario;
`rest` retains the legacy per-step API contract. Jobs are followed through API status; dummy workflow runs use events.

- **Readable IDs** (`domain/ids.py`) are purple's resource-group tokens: FactoryId `prefix-loc-env`, ScalesetId plus the
  RG suffix, ProjectId = the project RG name. Azure tokens are `dev/test/prod`; the catalog's `stage` maps to `test`.
  IDs resolve by formatting each catalog entity and matching the whole string; no lookup by key exists in the API.
- **Operations** (`domain/operation.py`) retain a token bound to the exact preview, CAS-saved `confirming` before the
  non-idempotent call, and terminal `uncertain` outcomes that are never retried. SDK mode has one `scenario` step
  and one local scope approval (not a live Azure preview). Confirm invokes `init_factory`, `add_scale_set`,
  `apply_project`, `delete_project`, `delete_scale_set` or `delete_factory`. Any facade failure may follow partial
  configuration/permission writes, so it is uncertain rather than safely retryable.
- **SDK adapter** (`adapters/sdk_backend.py`) implements the port directly; it does not inherit the REST orchestration.
  Since 2026-11-02 the facade is a thin client of the Factory API's `/api/v1/esaf/*` routes, which own preparation,
  API confirmation phrases, enrollment, deletion permission and retries; it requires `environment` on scale-set and
  project scenarios, and returns `EsafJob` kind `esaf` (earlier kinds stay readable). Updating this adapter and its
  tests to that contract is pending (Joakim, in parallel). Explicit per-call sessions
  select the resolved factory, environment and scale-set suffix. The adapter checks actual target identities again
  before execution, but does not block unrelated revision drift. Job ID, kind and factory are persisted and rebuilt
  as `EsafJob` for status reads, including the dedicated factory-deletion endpoint.
  Project runtime reviews must carry `runtime_scope_authorization` for the exact selected IDs and subscription,
  live enrollment and explicit deletion permission; missing proof prevents SDK confirmation even on an older API
  that incorrectly reports an executable review. This is actual scope/permission evidence, not a version/hash gate.
  Scenario 1 supplies `creation_request`: the facade saves the factory and starts a bounded whole-workflow approval
  whose continuation is server-owned, not a Function/runner daemon thread. A mid-workflow human review stops the step
  (`action_required`). SDK Scenario 2 deploys only the scale set's common resources; Scenario 3 adds projects explicitly.
  `apply_project` retains `upsert_project` compatibility.
- **REST compatibility** keeps the step-to-call mapping in `adapters/factory_api.py`. A mock backend keeps a persistent
  catalog for offline operation. REST Scenario 2 is configure -> add-project001 -> enroll-scaleset
  -> deploy-common -> deploy-project001: `enroll-scaleset` (step kind `enroll`) is the reviewed provider-state
  operation `enroll-scale-set` that extends a single-writer factory's binding and enrollment to the new scale set and
  the projects placed on it at prepare time; the API's exact Blob-coordination blocker marks it not needed
  (PREPARING -> SUCCEEDED, `step-not-needed`), and a missing route is 502 `factory-api-too-old`.
- **Executors**: `inprocess` (the API on this host's loopback), `github-dummy` (dummy workflow runs) and
  `github-runner` (the management runner calls the API on 127.0.0.1). The Function never calls the Factory API over
  the network because catalog and deployment routes require a loopback client.
- **Runner executor** (`adapters/runner_backend.py`, `application/runner_protocol.py`, `runner.py`): every backend
  prepare/confirm/status call is a hand-off (Asynchronous Request-Reply); one SDK confirm covers the complete scenario
  submission. The Function dispatches `aif-ops.yml` with a request it signs with
  the event secret and an expiry; the runner verifies it, checks that the workflow inputs describe it, makes the one
  call through the REST or SDK adapter and posts one signed result to `/api/v1/runner/results`. The step waits in
  `preparing` or `confirming`; a review that never reports fails, a confirmation that never reports (or whose run ends
  without a result) is `uncertain`, and a re-run never submits a confirmation again. One Factory API call may take
  `AIF_FACTORY_API_TIMEOUT_SECONDS` (2700 s): on the real API a runtime review took 13 minutes and its confirmation
  held the catalog lock for 18 minutes while it built the run, so the `aif-ops` job (60 minutes) outlasts one call
  and the Function's hand-off window (`AIF_RUNNER_TIMEOUT_SECONDS`, 4200 s) outlasts the job. Planning uses a catalog snapshot
  that every result refreshes. Because the Factory API refuses to dispatch `factory-lifecycle.yml` while any other
  workflow of the factory repo runs, the Function's workflows live in a separate ops repository, and API-dispatched
  runs are followed through the API's job status.
- **Factory API host** (`scripts/install-factory-api-host.ps1`): the API runs as SYSTEM on the management VM with
  SYSTEM's own logins, because it passes no token variables to `az`, `gh` and `git`. `az` uses the VM's managed
  identity (Owner on the factory subscription, Graph `Group.ReadWrite.All` and `User.Read.All` for the team group);
  `gh` uses a classic PAT from Key Vault with `repo`, `workflow` and `read:org`, checked before the script changes
  anything (observed 2026-10-22: `gh auth login` refused a classic token without `read:org`). The same identity needs
  Reader on every network in another subscription that is peered with a network in the factory subscription
  (observed 2026-10-22 on the real pass): the bootstrap's network-foundation review follows those peerings to check
  address overlaps, an ARM 403 makes it a blocked review, and under whole-workflow consent the API's own continuation
  then stops as `uncertain` with only `stage-execution-interrupted` in phase `authorization-continuation` (the API logs
  nothing). Reader on the one peered hub network fixed it; the API's verified-boundary recovery resumed the workflow
  without repeating verified stages. The Function's scenario 1 operation stays terminal and does not follow it.
  Observed the same day: the first COMMON run's `azure/login` failed (`AADSTS700213`) for a factory repository created
  after July 15, 2026, because GitHub then issues the immutable OIDC subject (owner and repository IDs), while the
  bootstrap's federated credential and the API's ownership handoff used the classic `repo:OWNER/REPO:environment:ENV`
  subject. Fixed in the bootstrap (`factory_enrollment.github_subject_prefix`, see [[Identity-and-Personas]]) and in
  Factory API v0.47.32; a factory bootstrapped before keeps its classic credential. The Factory API v0.47.31 has no
  HTTP surface to retire such a dispatched COMMON attempt (`terminal-common-before-azure-mutation-v1` exists only
  internally).
- **Events**: the relay workflow signs `workflow_run` payloads like a GitHub webhook; the Function checks
  `X-Hub-Signature-256`, deduplicates on `X-GitHub-Delivery`, correlates through the run name and can process through a
  storage queue whose messages it signs itself. A timer polls runs whose events are late.
- **Self-protection** refuses any target that contains the Function's own project or the configured management-runner
  scope. Real deletes need an explicit opt-in on both hosts (decided 2026-10-22, next to the real Spider factory):
  `AIF_DELETES` defaults to `refuse` (403 `deletes-disabled` before anything is recorded), every real adapter refuses
  a delete on its own, and the runner also needs `AIF_ALLOW_REAL_DELETES=true`. `AIF_DELETES=simulate` routes
  scenarios 4-6 to the mock backend over a read-only catalog mirror (Decorator `DeleteSimulation`) and runs them as
  dummy workflows (`DeleteRoutingTracker`), so the Factory API never gets a delete. Scenario 6 is limited to single-environment factories because `delete-aifactory` always deletes every
  environment.

## Constraints

- Hosting is the Flex Consumption plan (`infra/function-app.bicep`): no Always On, an integration subnet delegated to
  `Microsoft.App/environments` and a deployment package container read with the app's identity. Why: on the Dedicated
  B1 plan subscription governance switched Always On off every night (about 01:36 CEST, 2026-10-22 and 2026-10-23),
  after which the host idles and the reconcile timer and the event queue stop until an HTTP request wakes it. A
  Dedicated app cannot move to Flex in place: a new app (name, subnet) replaces it.
- Secrets are read from Key Vault by name with the managed identity. Key Vault references were avoided because Linux
  apps outside Flex need route-all to resolve them against a private vault, which would cut GitHub egress; reading by
  name stays on Flex.
- The Function's own name must stay outside purple's `func-prj<NNN>-...` pattern: purple's project pipelines treat such
  an app as the project Function and can delete it (`delete-services-if-disabled.sh`).
- A consumer copy is configuration plus a template copy; the template does not change factory Bicep or pipelines.
- Upgrade the Function and lifecycle runner together using the SDK commit pinned in requirements.txt. Old SDK jobs
  remain readable, but unconfirmed old per-step requests fail with `sdk-operation-upgrade`; reconcile before starting
  a new operation. Local fake/HTTP tests are not evidence of live Azure deployment.
- The server must include existing-target enrollment extension and project scope/deletion checks before
  `API-2-Pipelines` dispatch and again before queueing. Install the updated API before the SDK/Function; retain
  real-delete refusal during rollout. Project scope proof is produced by those live server checks.

See [[Factory-API-and-SDK]], [[Reviewed-Operations]], [[Lifecycle-and-Recovery]], [[Factory-Scope-Model]],
[[Trust-and-Authorization]] and [[Index]].

Authority: [template README](../../../usecase_code/10-azure-function/12_func_aifactory_lifecycle/README.md),
[how-to](../../v2/10-19/22-lifecycle-azure-function.md).
