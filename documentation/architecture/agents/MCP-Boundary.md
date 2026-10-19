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
  - usecase_code/40-agent-factory/agent_factory/mcp_gateway.py
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/apim-mcp-server.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/apim-policy-fragments.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/apim-configuration.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/main.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/policy.xml
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/README.md
  - usecase_code/40-agent-factory/45-aifactory-mcp-gateway/deploy.py
  - environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-aifactory-mcp-ai-gateway.yaml
  - environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/job-2-ai-gateway.yaml
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-ai-gateway.yml
  - environment_setup/aifactory/bicep/modules/containerappsEnv.bicep
  - environment_setup/aifactory/bicep/modules/azureMcpServer.bicep
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
  - usecase_code/40-agent-factory/tests/test_mcp_gateway.py
  - usecase_code/40-agent-factory/tests/test_apim_gateway_policies.py
  - environment_setup/unit-tests/test-bicep/unit/test_mcp_ai_gateway_flags.py
graph_symbols:
  - mcp/src/aifactory_mcp/server.py::function:create_server
  - mcp/src/aifactory_mcp/backend.py::class:AgentBackend
  - mcp/src/aifactory_mcp/backend.py::function:AgentBackend.call_tool
  - mcp/src/aifactory_mcp/graph.py::function:call
reviewed_source: '0a0595c9 + working tree; observed 2026-10-19'
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

The 2026-10-16 local source in `agent_factory.mcp_gateway` keeps gateway-only Foundry
discovery separate from MCP runtime dependencies. It rejects missing or mismatched
registration subnet bindings before gateway/MCP writes and carries planned owned
subnet configuration through a read-only plan. Owned tool-server reconciliation
checks the full governed endpoint and tool state, including additional endpoints.
Omitting the optional gateway ID does not prove creation: the deterministic
integration-owned gateway may already exist. Read-only discovery distinguishes
that reuse from a new gateway; existing owned/adopted subnet bindings can satisfy
registration without a subnet parameter. Missing outbound integration fails before
mutations, while only genuinely offline-invalid flags/ID formats promise zero calls.
Offline regression tests establish these boundaries, not production acceptance.

## Classic APIM gateway: policy package and MCP servers

The native AI Gateway SKU registers the MCP as a workspace tool server. A classic or v2 API
Management service gets the same governed entry point from
`esml-common/ai-gateway/apim/apim-mcp-server.bicep`. That module defines a plain HTTP `apis`
resource (POST/GET/DELETE on the MCP endpoint, unbuffered `forward-request`) that passes through
to the existing streamable-HTTP MCP and calls it with the APIM managed identity. A `type: 'mcp'`
API made APIM answer as its own tool-less MCP server on 2026-10-19, so the module avoids it.
The MCP still authorizes that identity itself: the app role
`AiFactory.Mcp.Read` and the container app's allowed-caller list are separate one-time steps,
and the module performs neither. For a pipeline-hosted MCP, `aifactoryMcpClassicApimResourceIds`
names the classic APIM services whose system-assigned identities `agent_factory.mcp_gateway`
adds to the allowed-caller list (read-only GETs of the APIMs, de-duplicated against the
project and native AI Gateway callers). The app role stays an Entra admin step that the run
prints as a prerequisite.

`addAIFactoryMCP2APIM` closes the loop for the APIM that the AI gateway pipeline manages
(`apimGateway*` variables): the project step adds its identity to the callers without listing it,
and the AI gateway pipeline step "Expose the AI Factory MCP on APIM" deploys
`apim-mcp-server.bicep` with parameters from `deploy.py apim-parameters`. That launcher is GET-only
and refuses until the MCP app exists and lists the APIM identity, so the order is fixed by evidence
rather than by convention: project pipeline first, then the AI gateway pipeline. The module's
optional `clientSubscriptionName` issues one client subscription scoped to the MCP API.

An MCP app deployed outside the step (the `mcp/deploy/rollout.py` pilot in Spider) is adopted by
`aifactoryMcpContainerAppResourceId`. Adoption is ownership-safe by construction: the app must be in
the project resource group, must not carry the step's owner tags, and must accept the configured
audience; the step then only appends missing callers and `factory.read` grants (one template PATCH,
new revision suffix) and never changes images, identity, secrets, ingress or tags.

The MCP's Container Apps environment must have an approved private endpoint, which is the network
path for APIM and the AI Gateway. The environment's own Bicep owns that endpoint and its DNS
registration (`containerappsEnv.bicep` `-pend`, `azureMcpServer.bicep` `-pe`, zone
`privatelink.<region>.azurecontainerapps.io`, or the hub DNS policy). `mcp_gateway` verifies them
and does not create a second endpoint, which would compete for the same DNS record; a missing zone
group is a reported prerequisite rather than a failure because hub policy remediation is asynchronous.

`apim-policy-fragments.bicep` holds the throttling, Entra validation, token-metric and
semantic-cache fragments once, and both the LLM API and the MCP API compose them.

- **Per-user limits** use only the `oid` of a token that `validate-azure-ad-token` has checked.
  Forged headers or unvalidated tokens never count.
- **Semantic cache entries** are partitioned per subscription, so cached answers are never
  shared across callers.
- **Opt-in:** every feature is off by default, and unsafe combinations fail when the template
  compiles.

The offline contract tests prove the template shape, not deployed behavior or reachability.

## Locally implemented graph tools

The optional `dual_graph` configuration section is the opt-in; there is no additional `enabled` key. Five tools are implemented: `graph_status`, `graph_query`, `architecture_search`, `architecture_note` and `dual_graph_context`. The normal Factory backend requires base `factory.read`, exact-scope `graph.read`, configured `allowed_scopes`, and a separate explicit tool allowlist for application callers.

The adapter validates closed bounded arguments and calls shared `DualGraphStore.query`; it does not duplicate the parser or expose generation, arbitrary file reads, shell execution or upstream Graphify MCP. Responses wrap core evidence as `{ok, data}` or sanitized errors. Packaging exports an integrity-verified immutable pin with source access disabled; local tests exercise official stdio and signed HTTP flows, not live cloud deployment. The separate graph-only mode was still being finalized at this documentation freeze; see [[dual-graph-lifecycle]] rather than assuming native Scout discovery.

See [[Factory-API-and-SDK]], [[Agent-Factory]], [[Health-Models]], [[Reviewed-Operations]], [[Trust-and-Authorization]], [[ADR-001-Dual-Graph]] and [[Index]].

Authority: [repository MCP contracts and deployment caveats](../../../mcp/readme.md), [private Azure MCP example](../../../usecase_code/40-agent-factory/44-azure-mcp/readme.md).
