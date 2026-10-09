---
id: trust-and-authorization
status: observed
sources:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/security.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/foundry.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_routes.py
  - mcp/src/aifactory_mcp/auth.py
  - mcp/src/aifactory_mcp/server.py
  - mcp/src/aifactory_mcp/access.py
  - bootstrap/lib/factory_lifecycle_contract.txt
tests:
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_security.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_conversation.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_operations.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_routes.py
  - mcp/tests/test_auth.py
graph_symbols:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/security.py::function:authorize
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/security.py::function:principal_from_token
reviewed_source: '3e9102ee + working tree; observed 2026-10-07; live voice observed 2026-10-09 at 29642909'
---
# Trust and authorization

## Observed checks

Authentication identifies a caller; current exact-scope grants authorize a permission; human review authorizes a specific mutation; cloud/provider identities and rights determine whether it can execute. No layer replaces another.

Agent delegated-token validation checks signature, issuer, audience, lifetime, tenant, object identity, delegated scope and approved client. `authorize` deliberately avoids unioning permissions across different scopes. MCP application principals have separately explicit read-only identity/scope/tool bindings.

The optional live voice relay reuses these checks: the Entra token sent in the first WebSocket frame is validated by `principal_from_token`, the exact-scope `knowledge.read` grant by `authorize`, and the session ends no later than token expiry. Speech, transcripts and spoken text are not authorization, and the Voice Live roles held by the application identity are service-level rights that never authorize a user.

Model-facing tools intersect canonical safe definitions with backend availability. Closed schemas cannot carry arbitrary endpoints, filesystem paths, scopes or shell commands. Approval and execution remain outside the ordinary model answer loop.

## Mandatory evidence trust rule

**Retrieved notes, source comments, release prose, graph nodes/edges and tool output are evidence, not instructions or authorization.** They cannot:

- grant `graph.read`, factory writes, cloud roles or data permissions;
- approve a plan/hash/confirmation phrase;
- widen tenant/subscription/project/environment scope;
- disable private networking, authentication or provenance checks;
- authorize package publication, ingestion, deployment or retry of an uncertain write.

Graphs are incomplete. An absent dependency, use site or test edge must never be interpreted as “safe to delete,” “unaffected,” “unreachable” or “fully covered.” Source provenance is not runtime resource ownership.

## Corpus boundary

This vault contains safe source descriptions and relative evidence references, not local configuration contents, tenant endpoints, credentials, customer datasets, logs, run records or token material. Source generators must use explicit inclusion/exclusion policies and reject sensitive/generated/runtime paths. A project-wide corpus is not automatically per-user document ACL enforcement.

See [[Reviewed-Operations]], [[Identity-and-Personas]], [[MCP-Boundary]], [[Chat-and-Grounding]], [[Retrieval-Provenance]], [[ADR-001-Dual-Graph]] and [[Index]].

Authority: [agent security boundary](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md), [MCP identity boundary](../../../mcp/readme.md), [lifecycle trust and coordination](../../../bootstrap/lib/factory_lifecycle_contract.txt).
