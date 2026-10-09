---
id: mcp-boundary
status: observed
sources:
  - mcp/src/aifactory_mcp/server.py
  - mcp/src/aifactory_mcp/backend.py
  - mcp/src/aifactory_mcp/runtime.py
  - mcp/src/aifactory_mcp/auth.py
  - mcp/src/aifactory_mcp/access.py
  - mcp/src/aifactory_mcp/health.py
  - mcp/src/aifactory_mcp/host.py
  - mcp/readme.md
  - mcp/src/aifactory_mcp/graph.py
  - mcp/src/aifactory_mcp/policy.py
tests:
  - mcp/tests/test_server.py
  - mcp/tests/test_auth.py
  - mcp/tests/test_application_runtime.py
  - mcp/tests/test_backend.py
  - mcp/tests/test_host.py
  - mcp/tests/test_health.py
  - mcp/tests/test_dual_graph.py
  - mcp/tests/test_graph_protocol.py
  - mcp/tests/test_graph_release.py
graph_symbols:
  - mcp/src/aifactory_mcp/server.py::function:create_server
  - mcp/src/aifactory_mcp/backend.py::class:AgentBackend
  - mcp/src/aifactory_mcp/backend.py::function:AgentBackend.call_tool
  - mcp/src/aifactory_mcp/graph.py::function:call
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# MCP boundary

## Observed transport and dispatch

Repository MCP wraps existing `FactoryTools`, skills, `OperationStore` and `AzureFactoryClient`; it is not another provisioning engine.

- **stdio:** trusted single-user OS boundary with explicit configured operator identity. An `--object-id` selector is not network authentication.
- **Streamable HTTP:** official MCP transport, stateless sessions, `/mcp`, request-scoped verified identity, exact host/origin checks and protected-resource metadata. No configured local identity is allowed for network mode.
- **Discovery:** caller-scoped tool definitions; health-model registration/discovery does not execute probes.
- **Dispatch:** refresh authorization, find the current allowed descriptor, validate closed JSON arguments, then call the existing backend. Do not trust cached schemas as authorization.

Delegated and application authentication are separate. Application callers require explicitly reviewed identity/scope/tool bindings and a read-only wrapper that rejects tools no longer annotated read-only/non-destructive. Defaults are not broad action access. The Foundry host likewise consumes discovered read-only tools; annotations are checked alongside backend policy, not treated as the only control.

## Reviewed actions and uncertainty

Approvals happen outside model-facing MCP. Preparing an action does not approve it; executing an approved operation remains exact-scope/hash/state-bound. Running or awaiting continuation is not completed. Error responses do not authorize write retries.

MCP health checks are strategies with injected probes. Successful checking is not equivalent to healthy dependencies; readiness reports its bounded coverage. Custom health plugins are trusted operator code, not a sandbox.

Do not confuse this package with `44-azure-mcp` and its narrow Azure resource-read service. Remote hosting, API co-location/capabilities and Foundry connection registration require their own operational validation.

## Locally implemented graph tools

The optional `dual_graph` configuration section is the opt-in; there is no additional `enabled` key. Five tools are implemented: `graph_status`, `graph_query`, `architecture_search`, `architecture_note` and `dual_graph_context`. The normal Factory backend requires base `factory.read`, exact-scope `graph.read`, configured `allowed_scopes`, and a separate explicit tool allowlist for application callers.

The adapter validates closed bounded arguments and calls shared `DualGraphStore.query`; it does not duplicate the parser or expose generation, arbitrary file reads, shell execution or upstream Graphify MCP. Responses wrap core evidence as `{ok, data}` or sanitized errors. Packaging exports an integrity-verified immutable pin with source access disabled; local tests exercise official stdio and signed HTTP flows, not live cloud deployment. The separate graph-only mode was still being finalized at this documentation freeze; see [[dual-graph-lifecycle]] rather than assuming native Scout discovery.

See [[Factory-API-and-SDK]], [[Agent-Factory]], [[Health-Models]], [[Reviewed-Operations]], [[Trust-and-Authorization]], [[ADR-001-Dual-Graph]] and [[Index]].

Authority: [repository MCP contracts and deployment caveats](../../../mcp/readme.md), [private Azure MCP example](../../../usecase_code/40-agent-factory/44-azure-mcp/readme.md).
