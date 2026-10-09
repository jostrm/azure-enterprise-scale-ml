---
id: health-models
status: observed
sources:
  - healthmodel/readme.md
  - healthmodel/src/aifactory_healthmodel/bootstrap.py
  - healthmodel/src/aifactory_healthmodel/application/service.py
  - healthmodel/src/aifactory_healthmodel/domain/definitions.py
  - healthmodel/src/aifactory_healthmodel/infrastructure/proxies.py
  - healthmodel/bicep/main.bicep
tests:
  - healthmodel/tests/test_application.py
  - healthmodel/tests/test_definitions.py
  - healthmodel/tests/test_infrastructure.py
graph_symbols:
  - healthmodel/src/aifactory_healthmodel/application/service.py::class:HealthModelService
  - healthmodel/src/aifactory_healthmodel/infrastructure/proxies.py::class:ReadOnlyTransport
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Health models

## Observed

`HealthModelService` composes account verification, provider/region checks, one scoped resource discovery, definition ordering, domain planning, parameter rendering and explicit deployment commands. `definitions` select workload views; the signal catalog describes resource classification and signals. Project, common and agent definitions are data-driven rather than separate transport implementations.

Read-only proxies protect plan-mode services. The offline infrastructure family can plan from an inventory but refuses deployment. Planning may produce local parameter files; “read-only” here means no cloud mutation, not necessarily no filesystem writes.

Optional provider pipelines deploy `Microsoft.CloudHealth` health models using the documented preview API. The model identity is Monitoring Reader, not Contributor/Owner. Pruning is an explicit owned-object operation, not general cleanup.

Health is state-based (`healthy`, `degraded`, `unhealthy`, `unknown`). Layer propagation and limited-impact shared dependencies avoid treating every common-resource problem as total workload failure. Missing telemetry and incomplete coverage must not become inferred healthy.

## Separate health concepts

- Health-model platform signals describe discovered infrastructure/workload state.
- MCP `HealthRegistry` strategies describe bounded checks such as API liveness/compatibility.
- ML monitoring evaluates observed feature windows and labeled performance.

These are related observability surfaces, not interchangeable proofs of deployment readiness. Existing documentation includes dated live findings; this vault did not repeat those experiments or copy runtime data.

See [[Dependency-Injection]], [[Monitoring-and-Retraining]], [[MCP-Boundary]], [[IaC-and-Private-Networking]] and [[Index]].

Authority: [health-model design, definitions, limitations and use cases](../../../healthmodel/readme.md).
