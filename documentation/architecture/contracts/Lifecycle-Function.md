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
reviewed_source: '6df0d00e + working tree; observed 2026-10-22'
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
  without a result) is `uncertain`, and a re-run never submits a confirmation again. Planning uses a catalog snapshot
  that every result refreshes. Because the Factory API refuses to dispatch `factory-lifecycle.yml` while any other
  workflow of the factory repo runs, the Function's workflows live in a separate ops repository, and API-dispatched
  runs are followed through the API's job status.
- **Factory API host** (`scripts/install-factory-api-host.ps1`): the API runs as SYSTEM on the management VM with
  SYSTEM's own logins, because it passes no token variables to `az`, `gh` and `git`. `az` uses the VM's managed
  identity (Owner on the factory subscription, Graph `Group.ReadWrite.All` and `User.Read.All` for the team group);
  `gh` uses a classic PAT from Key Vault with `repo`, `workflow` and `read:org`, checked before the script changes
  anything (observed 2026-10-22: `gh auth login` refused a classic token without `read:org`).
- **Events**: the relay workflow signs `workflow_run` payloads like a GitHub webhook; the Function checks
  `X-Hub-Signature-256`, deduplicates on `X-GitHub-Delivery`, correlates through the run name and can process through a
  storage queue whose messages it signs itself. A timer polls runs whose events are late.
- **Self-protection** refuses any target that contains the Function's own project or the configured management-runner
  scope. `AIF_DELETES=simulate` goes further for test environments: delete scenarios are reviewed for real but their
  confirmation is refused (403 `deletes-simulated`), so the Function never deletes anything. Scenario 6 is limited to single-environment factories because `delete-aifactory` always deletes every
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
