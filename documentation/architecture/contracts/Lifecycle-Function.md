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
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/settings.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/function-app.bicep
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/workflows/aif-event-relay.yml
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/workflows/aif-dummy-step.yml
tests:
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_ids.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_regions.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_operation_state.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_service_scenarios.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_events.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_adapter_parity.py
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/tests/test_http_api.py
graph_symbols:
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/service.py::class:LifecycleService
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/domain/operation.py::class:Operation
  - usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/factory_api.py::class:FactoryApiBackend
reviewed_source: '01f06fa1 + working tree; observed 2026-10-21'
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
  end-to-end tests without Azure.
- **Executors**: `inprocess` (the API on this host's loopback), `github-dummy` (dummy workflow runs) and
  `github-runner` (the management runner calls the API on 127.0.0.1). The Function never calls the Factory API over
  the network because catalog and deployment routes require a loopback client.
- **Events**: the relay workflow signs `workflow_run` payloads like a GitHub webhook; the Function checks
  `X-Hub-Signature-256`, deduplicates on `X-GitHub-Delivery`, correlates through the run name and can process through a
  storage queue whose messages it signs itself. A timer polls runs whose events are late.
- **Self-protection** refuses any target that contains the Function's own project or the configured management-runner
  scope. Scenario 6 is limited to single-environment factories because `delete-aifactory` always deletes every
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
