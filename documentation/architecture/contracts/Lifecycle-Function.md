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
graph_symbols:
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/service.py::class:LifecycleService
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/domain/operation.py::class:Operation
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/factory_api.py::class:FactoryApiBackend
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/runner_backend.py::class:RunnerBackend
reviewed_source: '98711370 + working tree; observed 2026-10-22'
---
# Lifecycle Function

## Observed

A usecase template (`usecase_code/10-azure-function/12_func_aifactory_lifecycle`) that runs six lifecycle scenarios -
init factory, add scale set, add or update project, delete project, delete scale set, delete factory - as reviewed
two-step operations over the Factory API, through REST or the `AzureFactoryClient` SDK, and follows the resulting
GitHub runs through `workflow_run` events.

- **Readable IDs** (`domain/ids.py`) are purple's resource-group tokens: FactoryId `prefix-loc-env`, ScalesetId plus the
  RG suffix, ProjectId = the project RG name. Azure tokens are `dev/test/prod`; the catalog's `stage` maps to `test`.
  IDs resolve by formatting each catalog entity and matching the whole string; no lookup by key exists in the API.
- **Operations** (`domain/operation.py`) follow the reviewed-operation shape of [[Reviewed-Operations]]: one Function
  confirm per Factory API confirmation, a token bound to the exact preview, CAS-saved `confirming` before the
  non-idempotent call, and `uncertain` as a terminal outcome that is never retried.
- **Backends** share one step-to-call mapping (`adapters/factory_api.py`, Template Method); REST and SDK only differ in
  transport, and a parity test proves they make identical calls. A mock backend keeps a persistent catalog for
  end-to-end tests without Azure. Scenario 1 saves the factory through `/api/v1/creation/prepare|confirm` (full
  bootstrap, dev scale set 001, prefix/region/suffix pinned to the FactoryId) and runs the creation workflow under one
  whole-workflow approval that the API continues by itself; a mid-workflow review request stops the step
  (`action_required`) rather than being auto-confirmed.
- **Executors**: `inprocess` (the API on this host's loopback), `github-dummy` (dummy workflow runs) and
  `github-runner` (the management runner calls the API on 127.0.0.1). The Function never calls the Factory API over
  the network because catalog and deployment routes require a loopback client.
- **Runner executor** (`adapters/runner_backend.py`, `application/runner_protocol.py`, `runner.py`): every Factory API
  call is a hand-off (Asynchronous Request-Reply). The Function dispatches `aif-ops.yml` with a request it signs with
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

- Secrets are read from Key Vault by name with the managed identity. Key Vault references are avoided because Linux
  apps outside Flex need route-all to resolve them against a private vault, which would cut GitHub egress.
- The Function's own name must stay outside purple's `func-prj<NNN>-...` pattern: purple's project pipelines treat such
  an app as the project Function and can delete it (`delete-services-if-disabled.sh`).
- A consumer copy is configuration plus a template copy; the template does not change factory Bicep or pipelines.

See [[Factory-API-and-SDK]], [[Reviewed-Operations]], [[Lifecycle-and-Recovery]], [[Factory-Scope-Model]],
[[Trust-and-Authorization]] and [[Index]].

Authority: [template README](../../../usecase_code/10-azure-function/12_func_aifactory_lifecycle/README.md),
[how-to](../../v2/10-19/22-lifecycle-azure-function.md).
