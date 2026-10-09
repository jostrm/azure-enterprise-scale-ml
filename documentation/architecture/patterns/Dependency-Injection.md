---
id: dependency-injection
status: observed
sources:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/ports.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/services.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/foundry.py
  - healthmodel/src/aifactory_healthmodel/bootstrap.py
  - healthmodel/src/aifactory_healthmodel/application/ports.py
  - mcp/src/aifactory_mcp/health.py
  - mcp/src/aifactory_mcp/runtime.py
  - esml-v2/azure_esml/base_layer/contracts.py
tests:
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_services.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_conversation.py
  - healthmodel/tests/test_bootstrap.py
  - healthmodel/tests/test_container.py
  - mcp/tests/test_health.py
  - esml-v2/tests/test_esml_backends.py
graph_symbols:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/services.py::class:AgentServiceFactory
  - healthmodel/src/aifactory_healthmodel/application/service.py::class:HealthModelService
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Dependency injection

## Observed composition boundaries

- Agent `AgentDependencies`, `AgentServices` and `AgentServiceFactory` compose per-configuration services. `Conversation` accepts knowledge, tools, model gateway and audit dependencies; tests can exercise behavior without cloud constructors.
- Health-model `bootstrap.py` composes domain/application services with Azure or offline infrastructure. Read-only proxies enforce plan-mode restrictions, and resilience decorators surround transport behavior rather than altering domain policy.
- MCP `HealthModel` strategies use injected probes, registered through `HealthRegistry` and the runtime composition root. Discovery is probe-free and per-caller composition avoids a global mutable identity.
- ESML base-layer contracts abstract backend/folder operations; domain code holds ESML naming/data/pipeline policy; app examples select configuration and transport.

Dependency injection is not an authorization bypass. Source tests deliberately exercise current grants and canonical tool schemas even when tools/model services are injected. Trusted plugins/adapters remain responsible for their own bounded access; this is not a sandbox for arbitrary code.

## Architectural consequence

Adapters should reuse existing contracts, not fork provisioning or training logic. Offline fakes establish contract behavior and failure handling, not live endpoint compatibility. Lazy construction reduces unnecessary dependencies but cannot convert unavailable evidence into success.

The locally implemented shared graph runtime follows this composition style: Chat uses an injected immutable scoped query service and MCP calls the same store, with no implicit cloud client or duplicated parser. [[dual-graph-lifecycle]] records the implementation boundary while the ADR remains proposed.

See [[Agent-Factory]], [[Chat-and-Grounding]], [[Health-Models]], [[MCP-Boundary]], [[Engines-and-Pipelines]], [[ADR-001-Dual-Graph]] and [[Index]].

Authority: [health-model OO design](../../../healthmodel/readme.md), [MCP strategy and probe contracts](../../../mcp/readme.md).
