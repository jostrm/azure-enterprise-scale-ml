---
id: system-context
status: observed
sources:
  - README.md
  - bootstrap/lib/registered_creation.py
  - bootstrap/lib/factory_lifecycle.py
  - environment_setup/azurefactory-cli/src/azurefactory/client.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/tools.py
  - mcp/src/aifactory_mcp/backend.py
tests:
  - environment_setup/azurefactory-cli/tests/test_client.py
  - mcp/tests/test_backend.py
graph_symbols:
  - environment_setup/azurefactory-cli/src/azurefactory/client.py::class:AzureFactoryClient
  - bootstrap/lib/factory_lifecycle.py::function:validate_manifest
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# System context

## Observed boundaries

```text
Operator / external desktop / CLI
  -> shared Factory API contract -> reviewed configuration and runtime orchestration
  -> pinned accelerator helpers -> ADO/GHA workers -> Bicep -> Azure resources

Authenticated Chat or MCP caller
  -> exact-scope authorization -> existing agent tools -> AzureFactoryClient -> API

ML and Agent Factory examples
  -> reusable workload engines -> explicitly selected existing Azure services
```

The repository is both an application-landing-zone accelerator and a collection of workload engines/templates. It is not one continuously running service. `registered_creation.py` is a configure-first API adapter, while `factory_lifecycle.py` is a scoped execution engine. Keeping those roles separate prevents a saved catalog draft from being treated as deployed infrastructure.

The stdlib SDK consumes the shared HTTP API. The maintained Tkinter API and MAUI source/build system are external to this checkout; their contracts are documented here, not reimplemented or verified by this vault. Chat and repository MCP reuse the agent/SDK boundary instead of introducing another provisioning engine.

Cloud identity, API authentication, application grants and human approval are independent checks. Common network resources and project workload resources cross resource-group boundaries; a project read or management grant does not implicitly cover the hub, common lake or another environment.

## Intended constraints

Use explicit target identity, capability discovery, reviewed plans and observed execution evidence. Neither a feature flag nor a successful local render is Azure deployment evidence. Model inference and ingestion are separate paid operations from source packaging and graph generation.

Continue through [[Factory-Scope-Model]], [[Repository-Boundaries]], [[Factory-API-and-SDK]], [[Agent-Factory]] and [[MCP-Boundary]]. Return to [[Index]].

Authority: [platform concepts](../../../README.md), [API/CLI boundary](../../../environment_setup/azurefactory-cli/readme.md), [agent boundary](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
