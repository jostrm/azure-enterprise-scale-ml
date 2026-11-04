# AI Factory MCP

An MCP server, client, and read-only Foundry host for the Enterprise Scale AI
Factory accelerator. It is another client of the existing Factory API, not a
second Azure provisioning implementation.

## Baseline and gap assessment

Assessment began on 3 October 2026 against the actual working files, including
the existing, uncommitted Foundry agent implementation.

| Surface | Confirmed baseline | MCP work |
| --- | --- | --- |
| This folder | Only this README heading existed | Add installable Python package, transports, client, host, examples and tests |
| Python API, Tkinter and MAUI | Existing shared API and reviewed operations | Consume the same API; no UI or API fork |
| Purple SDK/CLI | `environment_setup\azurefactory-cli` provides `AzureFactoryClient` and CLI | Reuse through the existing agent adapter |
| Foundry agent | Six skills, exact-scope grants, durable signed plans, approval and execution already exist | Publish MCP schemas and adapt the same implementation |
| Factory deletion | Existing code preserves Entra groups and enforces reviewed deletion | Retain those safeguards; do not describe historical deletion issues as new defects |
| Example settings | Writes disabled; action profiles, target IDs and HTTP authentication need operator configuration | Report blockers, never invent missing IDs or silently enable actions |
| Model | Example names `aifactory-agent-gpt-6-1-sol` | A read-only Azure query confirmed `gpt-6.1-sol`, version `2026-09-29`, state `Succeeded` |

No new defect in the API or UI was established by this inspection. Existing
governance is not evidence that a particular factory is deployed or writable.
The MCP tests cover the adapter; they do not claim to have deployed or deleted
a real factory.

## OOAD, dependency injection and health models

Health checks use **Strategy** (`HealthModel`), **Adapter**
(`AgentHealthProbe`) and an explicit **factory/composition root**
(`load_runtime(..., health_models_factory=...)`). A health model owns its
evaluation policy; its injected probe owns access to dependencies. The
`HealthRegistry` owns registration, closed argument validation and discovery.
The transport and action dispatcher do not need new branches for new models.

```text
load_runtime(health_models_factory=...)
    -> caller-scoped AgentBackend
    -> HealthRegistry
    -> HealthModel strategy
    -> injected HealthProbe
    -> existing FactoryTools / API
```

`factory_health` and `factory_cli_health` retain their existing response
contracts. Custom models use a `health_` tool name and a strict Pydantic
argument class. Duplicate names and operation-name collisions fail at
composition. Discovery does not run probes. Models are constructed for each
caller-scoped backend; there is no mutable global registry or singleton
holding a caller identity.

Add a model by implementing the `HealthModel` protocol and injecting it:

```python
from aifactory_mcp.health import default_health_models
from aifactory_mcp.runtime import load_runtime

def models(probe):
    return (*default_health_models(probe), ApiVersionHealthModel(probe))

runtime = load_runtime(config_path, health_models_factory=models)
```

See `usecase_code\health_models.py` for the complete `ApiVersionHealthModel`,
including an independent compatibility policy and its argument schema. It
adds `health_api_version` alongside the two defaults:

```powershell
& $Python .\usecase_code\health_models.py `
  --config $Config --scope $Scope --object-id $ObjectId
```

A host can launch that script instead of the standard `serve` command, then
call `health_api_version` with `{"expected_version":"1.0.0"}`. The same
configured object can be passed to `create_http_app` for HTTP hosting.
`AgentBackend(..., health_models=[...])` also supports direct injection for
unit tests. Dependencies may be replaced without patching globals.

Health plugins are trusted operator code, not a sandbox. They must remain
read-only, bounded and scope-bound. The provided probe exposes only API
health, fixed CLI health and capability reads; it does not expose write
dispatch or accept caller-selected endpoints. Additional dependency adapters
must enforce their own least-privilege access and timeouts. The shared
backend still validates authorization and sanitizes results and known errors.
`ok: true` means the check completed, not that every component is healthy:
inspect the health status and coverage in `data`. Missing evidence is an
error or unknown, never inferred healthy.

The design follows the trade-offs in the
[Azure Well-Architected Framework](https://learn.microsoft.com/en-us/azure/well-architected/),
[Cloud Design Patterns](https://learn.microsoft.com/en-us/azure/architecture/patterns/)
and [Health Endpoint Monitoring](https://learn.microsoft.com/en-us/azure/architecture/patterns/health-endpoint-monitoring):

| Pillar | Applied here |
| --- | --- |
| Reliability | Bounded dependency calls, explicit failure/uncertainty, no automatic write retries |
| Security | Per-request identity and scope, separate human approval, secret redaction, TLS for remote access |
| Cost Optimization | On-demand checks; no cloud resources or background polling introduced by registration |
| Operational Excellence | Testable interfaces, transport regression coverage, explicit observation/operation semantics |
| Performance Efficiency | Lazy dependencies and probe-free discovery; only the requested health model executes |

API liveness/version compatibility is not full deployment readiness. Model
implementations must state what they actually measure. These are design
choices, not a claim of production certification. Additional patterns such
as Composite or Decorator can be used when their concrete use case warrants
them; they are not mandatory layers.

## Architecture

```text
Agent / MCP host
    -> official MCP client
    -> stdio or authenticated Streamable HTTP server
    -> existing aifactory_agent FactoryTools / skills / OperationStore
    -> existing AzureFactoryClient
    -> shared Python Factory API
    -> purple accelerator

Human terminal -> separate approval command -> same signed operation store
Foundry read-only host -> configured model + discovered read-only MCP tools
```

Cost skills reuse the agent's existing Azure billing/retail implementation.
They keep template estimates, actual charges and forecasts separate. Missing
pricing is not zero cost.

All new code is here. The existing agent, SDK, API and .NET repositories are
not copied or modified. A matching purple checkout is a required dependency:
the server loads the actual agent under
`usecase_code\40-agent-factory\40-aifactory-agent` and the actual SDK under
`environment_setup\azurefactory-cli`. An installation outside the checkout
must pass `--repository-root`.

## Install

Python 3.11 or later is required. Run from this folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install `
  -r ..\usecase_code\40-agent-factory\40-aifactory-agent\requirements.txt `
  -e ..\environment_setup\azurefactory-cli `
  -e ".[dev]"

$Python = (Resolve-Path .\.venv\Scripts\python.exe).Path
$Config = (Resolve-Path ..\usecase_code\40-agent-factory\40-aifactory-agent\config.example.json).Path
$Scope = "project001-dev"
$ObjectId = "<your explicitly authorized Entra object UUID>"
```

Use a private configuration based on the existing agent example for real work.
The supplied example already selects tenant
`c157e61b-4a1e-488c-9a0c-d9a23e864a65`
(`mngenvmcap235830.onmicrosoft.com`), subscription
`f0fe8b33-73bf-41e4-9997-e3920d793c06`, resource group
`spider-esml-project001-sdc-dev-001-rg`, account `aif2bltscaae001dev`,
and project `aif2-p001bltdev`. Do not treat an example grant as authority
to impersonate another person.

For API reads beyond health, run the existing API separately and set
`factory.api_url`, `factory.folder`, and exact factory/scale-set/project IDs.
Use the existing API's key via `AIFACTORY_API_KEY` or
`factory.api_key_secret_url`; never put a key in a tool argument or source file.
The MCP server does not launch, upgrade or expose the API. Its catalog and
deployment endpoints remain loopback-only, so co-locate the MCP server with
the API for those operations.

## Local stdio server and client

Local stdio is a **trusted single-user OS boundary**, like the existing CLI.
`--object-id` deliberately selects a configured operator grant; it is not a
claim of network token authentication. Only trusted users may edit the config,
run the process, or access its API credentials. The model cannot change its
scope, identity, endpoints or local paths through tool arguments.

```powershell
# A host normally launches this command and owns its lifetime.
& $Python -m aifactory_mcp serve --config $Config --scope $Scope --object-id $ObjectId

# These commands launch and close a child stdio server via the official client.
& $Python -m aifactory_mcp tools --config $Config --scope $Scope --object-id $ObjectId
& $Python -m aifactory_mcp call factory_skills --config $Config --scope $Scope --object-id $ObjectId
& $Python -m aifactory_mcp call factory_health --config $Config --scope $Scope --object-id $ObjectId
```

Standard MCP host configuration shape (replace paths and identity):

```json
{
  "mcpServers": {
    "enterprise-scale-ai-factory": {
      "command": "C:\\path\\to\\purple\\mcp\\.venv\\Scripts\\python.exe",
      "args": [
        "-m", "aifactory_mcp", "serve",
        "--config", "C:\\private\\agent-config.json",
        "--scope", "project001-dev",
        "--object-id", "<authorized-object-uuid>"
      ]
    }
  }
}
```

Use your host's secret/environment mechanism for credentials. Protocol output
alone goes to stdout; diagnostics go to stderr.

## Tools and existing skills

MCP tool names must fit the protocol's name limit, so long skill commands map
to shorter tool names. Schemas come from the existing Pydantic skill models,
not a separate hand-maintained provisioning contract.

| Existing skill | MCP tool |
| --- | --- |
| `create-private-aifactory-full-bootstrap-private-with-own-hub-vpn-and-default-proj` | `factory_prepare_create` |
| `delete-aifactory` | `factory_prepare_delete` |
| `add-project-to-aifactory` | `factory_prepare_add_project` |
| `get-default-project-estimated-azure-idle-running-cost` | `cost_default_project_idle` |
| `get-aifactory-common-estimated-azure-idle-running-cost` | `cost_common_idle` |
| `get-monthtly-forecasted-project-estimated-azure-cost` (existing spelling) | `cost_monthly_project_forecast` |

Other tools: `factory_health`, `factory_capabilities`, `factory_catalog`,
`factory_settings`, `factory_cli_health`, `factory_skills`,
`factory_operations`, `factory_operation`, `factory_operation_status`,
`factory_execute_operation`, and `factory_cancel_operation`.

`factory_skills` reports the actual skill names, argument schemas, permissions
and configuration blockers. Cost discovery requires the existing `cost.read`
grant. Disabled actions remain discoverable but fail explicitly. Status
observation can persist audit/state updates, so it is not advertised as a
strictly read-only tool. No arbitrary shell, URL, filesystem or approval tool
is exposed. The fixed CLI health tool is excluded from the model host.

### Optional dual-graph evidence

The existing MCP server can expose the shared agent's `DualGraphStore`; no new
server, model, endpoint, Graphify production dependency or startup indexing is
introduced. Absent or disabled configuration leaves legacy tools unchanged.
Enable only a reviewed corpus in the private agent configuration:

```json
{
  "dual_graph": {
    "snapshot_root": "C:\\reviewed\\meta\\graphify",
    "expected_snapshot_id": "<reviewed-64-lowercase-hex-snapshot-id>",
    "allowed_scopes": ["project001-dev"],
    "allow_source_access": false
  }
}
```

This fragment does **not** grant access. The exact caller/scope needs both the
existing `factory.read` gate and a separate `graph.read` grant.
`factory.read`, `knowledge.read`, Entra app roles and registration plans alone
never authorize corpus reads. Application identities additionally need each
graph tool in their explicit `allowed_tools`; existing identities and default
allowlists remain unchanged. Discovery and dispatch recheck these boundaries.
Omit `dual_graph` or set it to `null` to disable it; a complete explicit section
is the opt-in (there is no separate `enabled` switch).

| Tool | Closed arguments / operation |
| --- | --- |
| `graph_status` | No arguments; snapshot provenance/freshness, not service health |
| `graph_query` | `operation`: `symbols`, `usages`, `callers`, `dependencies`, `dependents`, `trace`, `pipeline`, `impact`; optional `query`, `node_id`, `depth`, `limit` |
| `architecture_search` | Optional `operation`: `notes` (default) or `adrs`; `query`, `limit` |
| `architecture_note` | Required `node_id`; optional `operation`: `note` (default) or `backlinks`; `limit`; **never writes a note** |
| `dual_graph_context` | Required `query`; optional `depth`, `limit` |

Query text is bounded to 2,000 characters, node IDs to 512, depth to 0–5,
and results to 1–100 (default 20). Caller-supplied paths, roots, URLs and unknown
arguments are rejected. Results use a structured `{ok, data}` envelope retaining
the shared snapshot ID, citations, warnings, freshness and truncation evidence.
Unavailable or invalid snapshots return a sanitized structured tool error;
legacy Factory discovery/startup does not require graph files.
All five tools are read-only and cannot approve or execute actions.

Source freshness is checked only with explicit `allow_source_access: true`
and an existing operator-configured `knowledge.repository_root`; no automatic
fallback to the checkout occurs. With source access disabled, report the
snapshot's freshness uncertainty, not inferred current source state.
The host treats graph/architecture output as untrusted static evidence, never
live deployment health or authorization. Impact/trace results are bounded
analysis, not permission to change infrastructure.

#### Corpus-only local registration

Use the **existing** server's explicit `--graph-only` mode when registering a
local corpus connection with Scout or another MCP host:

```powershell
& $Python -m aifactory_mcp serve --config $Config --scope $Scope `
  --object-id $ObjectId --graph-only
```

This mode requires only the explicit exact-scope `graph.read` grant and matching
`dual_graph.allowed_scopes`; it does not require or inherit `factory.read`.
Both discovery and dispatch are fixed to the five graph tools above. It never
constructs Factory tools or operation storage and exposes no approval method.
Even broader caller grants cannot expose Factory tools on this connection.
It uses the same runtime, stdio/HTTP transport and server identity, not a separate
ungoverned Graphify server. Removing the flag restores the original Factory
server behavior; **do not omit it** from a corpus-only registration.

`tools` and `call` also accept `--graph-only` for their local child server.
Remote clients cannot select this policy: the HTTP operator must set it on
`serve`. Graph-only application HTTP additionally requires a graph-only explicit
application tool allowlist. The mode does not grant permissions, edit host
registration state, or hot-load tools into an already running host. For this
mode `/health/ready` has no Factory API probe; inspect authorized `graph_status`
instead of treating process liveness as graph readiness.

## Governed actions: prepare, human approval, execute, observe

Action prerequisites remain those of the existing agent:

- Exact-scope grants, `factory.writes_enabled`, allowed environment and enabled skill.
- Server-reviewed bootstrap profile / deletion resource groups / target configuration.
- Durable Blob storage and a dedicated Key Vault operation-signing secret.
- A compatible running API, its credential, and the required Azure permissions.

Do not enable these just to make a smoke test pass. There is no production
in-memory store or automatic fallback.

```powershell
# Preparation creates a reviewable plan, not Azure resources.
& $Python -m aifactory_mcp call factory_prepare_create `
  --config $Config --scope $Scope --object-id $ObjectId --arguments '{}'

# Review the returned operation, effects, risks, expiry and exact plan_hash.
$OperationId = "<returned-operation-uuid>"

# Human-only: requires an interactive terminal and typing the exact hash.
# Deletion additionally requires typing the exact phrase shown in its plan.
& $Python -m aifactory_mcp approve --config $Config --scope $Scope `
  --object-id $ObjectId --operation-id $OperationId

# The client or agent may now consume that approved plan exactly once.
$ArgsJson = @{ operation_id = $OperationId } | ConvertTo-Json -Compress
& $Python -m aifactory_mcp call factory_execute_operation `
  --config $Config --scope $Scope --object-id $ObjectId --arguments $ArgsJson
& $Python -m aifactory_mcp call factory_operation_status `
  --config $Config --scope $Scope --object-id $ObjectId --arguments $ArgsJson
```

Approval is deliberately absent from MCP discovery and dispatch. There is no
`--yes` switch or piped approval. Existing exact-hash checks, caller/scope
binding, expiry, signed records, drift detection and atomic execution claims
remain authoritative.

`running` and `awaiting_continuation` are not completion. Failed and uncertain
results set MCP `isError` and retain the operation record when available.
The client preserves that structured failure through stdio/HTTP task-group
cleanup, so the CLI reports the retained operation rather than a nested
exception traceback. It does not retry the call.
Read persisted state after a timeout; never blindly retry a confirmation.
Cancel only invalidates an unexecuted plan, not an Azure job. Paused workflows
requiring additional review must use the existing approved API/UI workflow;
MCP does not invent a continuation or expand the original approval.

`factory_operation` and `factory_operations` return non-mutating, scope-bound
snapshots. They do not expire plans or append audit events, including for
plans in another scope. Their persisted `pending` or `approved` status must
be read together with `expires_at`; snapshots never extend an approval's
lifetime. Approval and execution still enforce expiry in the shared store.
The adapter reuses its verified loader instead of the shared `read/list`
methods, which can persist expiration.

Full deletion retains the existing Entra group preservation and Search shared
private-link cleanup behavior. Project configuration creation must not be
presented as a completed Azure deployment.

## Authenticated Streamable HTTP

HTTP never accepts `--object-id`. Every request validates a delegated Entra
token with the existing verifier: signature, issuer, tenant, audience, lifetime,
scope and authorized-client checks. A token must target the configured MCP
app registration, not ARM, Graph or an unrelated service. The example's
`auth.client_id` and `auth.audience` are unconfigured; configure the registration
before enabling HTTP. The inherited verifier currently supports one client
registration; generic automatic client registration is not implemented.

### Foundry project identity (opt-in and read-only)

For a Foundry `ProjectManagedIdentity` connection, supply a separate
`--application-auth` policy file. This is an additional application-token
authentication path; it does not replace or relax delegated user validation.
The policy must use a **different API application/audience** from the existing
browser registration.

```json
{
  "audience": "<new-mcp-api-application-uuid>",
  "required_role": "AiFactory.Mcp.Read",
  "identities": [{
    "object_id": "<foundry-project-managed-identity-object-uuid>",
    "client_id": "<foundry-project-managed-identity-client-uuid>",
    "scope_keys": ["project001-dev"],
    "allowed_tools": ["factory_health", "factory_capabilities", "factory_skills"]
  }]
}
```

Replace placeholders with actual reviewed identifiers. The same identity
also needs an explicit `factory.read` grant for `project001-dev` in the agent
configuration. Application grants cannot include write permissions. Cost
tools additionally require `cost.read`; they are not enabled by the example.

The new API registration must issue v2 access tokens, emit the `idtyp`
optional access-token claim, and expose the application role
`AiFactory.Mcp.Read` assigned only to the reviewed Foundry project identity.
Validation checks signature, issuer, audience, tenant, lifetime, `idtyp=app`,
`ver=2.0`, the exact role, `oid` and `azp`. Delegated tokens cannot masquerade
as application tokens. Audience routing is only a dispatch hint: the
selected verifier always performs full cryptographic validation, with no
fallback after failure.

```powershell
& $Python -m aifactory_mcp serve --config $Config --scope $Scope `
  --transport streamable-http --host 127.0.0.1 --port 8899 `
  --resource-url https://factory-mcp.example.com/mcp `
  --application-auth C:\private\application-auth.json
```

The injected verifier produces a distinct application principal. A separate
read-only backend filters discovery **and** dispatch, so application callers
cannot prepare, approve, execute, cancel, inspect operations, invoke shell/CLI
tools or select another scope. The existing delegated operator path retains
its same-caller, exact-hash human approval controls. No managed identity is
mapped to a human user's identity.

`usecase_code\foundry_connection_plan.py` produces a **plan only** for the
new project connection, Entra role requirements, application policy and MCP
tool attachment. It has no apply mode. The generated tool attachment requires
Foundry tool-call approval and an explicit allowlist; that approval is not
a Factory action approval. Inspect the existing agent version and preserve
its existing tools before publishing an attachment.

Do not overwrite the existing `aif-azure-mcp` connection or
`aif-mcp-project001-dev` Container App: they belong to Microsoft's Azure MCP,
not this Python Factory MCP. Use distinct names for this service.

### Deployment probes

HTTP hosting exposes `/health/live` for process liveness and `/health/ready`
for the configured Factory API's credential-free `/health` contract. The CLI
wires an injected `ApiReadinessProbe` with a two-second HTTP timeout, no
redirects/proxy credentials, and bounded response size. Dependency failure
returns 503 without leaking exception details. These endpoints do not grant
access to `/mcp`, and API health does not prove action readiness or successful
Azure provisioning. A programmatic host without a readiness dependency
returns 503 rather than claiming readiness.

```powershell
& $Python -m aifactory_mcp serve --config $Config --scope $Scope `
  --transport streamable-http --host 127.0.0.1 --port 8899 `
  --resource-url https://factory-mcp.example.com/mcp
```

Place a TLS reverse proxy on that hostname in front of the loopback listener.
Preserve its external Host header. Do not expose the cleartext listener or
Factory API directly. Plain HTTP resource URLs are allowed only for loopback
development. Host/Origin checks remain enabled, and clients do not follow
redirects carrying credentials.

The server publishes
`/.well-known/oauth-protected-resource/mcp` and advertises it in a 401
challenge. Obtain a delegated token for the configured registration through
your approved sign-in flow and provide it through the environment:

```powershell
# Set AIFACTORY_MCP_TOKEN securely outside command history.
& $Python -m aifactory_mcp tools --config $Config --scope $Scope `
  --url https://factory-mcp.example.com/mcp
```

The server's scope is authoritative; client configuration flags do not
override a remote scope. HTTP is stateless at the protocol layer; approved
operations remain durable in the shared agent store across process restarts.
The token is not forwarded to the Factory API; its service credential and
the existing exact-scope grants remain distinct.

## Use-case code and Foundry

`usecase_code\read_only_client.py` performs actual MCP discovery and API
health/capability reads. `usecase_code\foundry_readonly.py` runs the existing
agent's instructions and configured credential/model through a bounded
Responses-to-MCP loop. It uses `aifactory_agent.foundry.INSTRUCTIONS` and
`aifactory_agent.config.credential`, rather than a replacement agent prompt.

```powershell
& $Python .\usecase_code\read_only_client.py `
  --config $Config --scope $Scope --object-id $ObjectId

# Default: local preview, no paid model request.
& $Python .\usecase_code\foundry_readonly.py `
  --config $Config --scope $Scope --object-id $ObjectId `
  --question "Use factory_health once to report the Factory API health."

# Explicitly opt into inference on the existing configured GPT 6.1 Sol deployment.
& $Python .\usecase_code\foundry_readonly.py `
  --config $Config --scope $Scope --object-id $ObjectId `
  --question "Use factory_health once to report the Factory API health. Do not call any other tools." `
  --live-read-only
```

This is a client-side host using the existing agent code and model deployment.
It does **not** modify the deployed agent definition or register a remote MCP
tool in Foundry. No model, agent, resource group or factory is provisioned.
Only the supplied question, agent instructions, tool schemas and requested
read results are sent to the configured Azure model.

The host excludes prepare/approve/execute/cancel tools, validates model-selected
names against discovery, preserves Responses reasoning items, and bounds
rounds. It returns a trace distinguishing model output from MCP observations.
No tool errors are converted into successful observations.

## Read-only pilot deployment scaffold

The scaffold lives in `infra\` and `deploy\`. It targets only the separately
named `aifactory-mcp-project001-dev` app and `mi-aifactory-mcp-dev` identity.
It references the existing private environment, Premium registry and Key
Vault without replacing them. The two containers share a network namespace:
MCP listens on 8080 and the API remains on `127.0.0.1:8765`. Each runs as UID
10001 with 0.5 vCPU / 1 GiB; the app has one replica.

The pilot launcher rejects writes, action skills and privileged grants. By
default Foundry tools are health, capabilities and skill discovery only. It creates
no customer catalog. Persistent single-writer catalog/worktree storage and
signed operation storage remain prerequisites for a later action rollout.

### Prepare and validate images locally

The reviewed release uses purple commit
`3e9102ee07c959d91e5ac508432bd1545d258a15` and API v0.47.7 commit
`d4e2c7a1eda7f3d331b52bffe3646433ebf8680d`. The newer local API revision and
dirty sibling agent/UI files are not silently included. MCP changes are
included as an explicit per-file-hashed source snapshot.

```powershell
& $Python -m pip download --no-deps --only-binary=:all: `
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 `
  --platform manylinux_2_17_x86_64 --python-version 313 --implementation cp --abi cp313 `
  --dest .build\linux-wheels -r deploy\requirements.linux.lock.txt

& $Python deploy\prepare-release.py --purple-root .. `
  --purple-ref 3e9102ee07c959d91e5ac508432bd1545d258a15 `
  --api-root C:\code\code_py_25\008_aifactory_admin_ux_tkinter `
  --api-ref d4e2c7a1eda7f3d331b52bffe3646433ebf8680d `
  --wheelhouse .build\linux-wheels --output .build\my-pilot-release

$Release = ".build\my-pilot-release"
$ReleaseHash = (Get-Content "$Release\release.json" -Raw | ConvertFrom-Json).release_hash
docker build --platform linux/amd64 -f deploy\Dockerfile.mcp `
  --build-arg "RELEASE_HASH=$ReleaseHash" -t aifactory-mcp-pilot:review $Release
docker build --platform linux/amd64 -f deploy\Dockerfile.api `
  --build-arg "RELEASE_HASH=$ReleaseHash" -t aifactory-api-pilot:review $Release
& $Python deploy\smoke-images.py --mcp-image aifactory-mcp-pilot:review `
  --api-image aifactory-api-pilot:review --config $Config
```

The base Linux image is pinned by digest. Python dependencies install offline
from the hash-recorded Linux wheel bundle; TLS verification is never disabled.
The API includes the Tcl/Tk runtime libraries needed by its existing imports.
Each image records its release manifest and installed package versions.
The smoke runner exercises both actual containers, authentication rejection
and MCP-to-agent-to-API health/capabilities. It uses synthetic local identities,
does not request Azure tokens, and removes its containers afterward.

#### Package an explicitly pinned graph

`deploy\prepare-release.py` accepts optional `--graph-config <private-agent.json>`.
Only an explicitly enabled `dual_graph` section with a valid
`expected_snapshot_id`, nonempty `allowed_scopes` and source access disabled is
packaged. The reviewed purple commit must include the shared `dual_graph.py`
runtime and matching agent configuration support; the older pilot commit above
cannot supply this feature. The packager does not silently copy dirty agent
sources or generate graph data.

The exact archived runtime validates and exports the snapshot's manifest-bound
files into `repository\meta\graphify\snapshots\<snapshot-id>` in the existing
release context. No mutable `current.json`, arbitrary sibling files or source
corpus are added. Release hashes bind the files and selected snapshot ID.
The existing Dockerfile already copies this repository directory.
Without the explicit option, no graph corpus is included.

At startup the launcher requires an explicitly enabled configuration to match
the packaged pin and binds it to that immutable container path; it never
generates, downloads or selects a newer graph. Existing pilot tools remain the
default. Opted-in graph tools still need separate read-only grants, exact
configured scopes and application allowlists. Packaging and registration
planning do not deploy, assign permissions, modify resources or enable current
identities. `/health/ready` remains Factory API health only; use authorized
`graph_status` for graph evidence.

### Plan, approve and execute one stage at a time

```powershell
.\deploy\rollout.ps1 -Phase plan -Release $Release -BaseConfig $Config `
  -McpImage aifactory-mcp-pilot:review -ApiImage aifactory-api-pilot:review `
  -Plan .build\reviewed-rollout.json
.\deploy\rollout.ps1 -Phase preflight -Plan .build\reviewed-rollout.json
```

Both commands are non-mutating in Azure. Review the generated `plan_hash`,
source hashes, image IDs, exact scopes and effects. The write phases each
require `-ApprovalHash` matching that reviewed plan and must run in order:
`identity`, `secret`, `foundation`, `publish`, `application`, `connection`.
Do not supply approval until resource deployment and permissions have been
explicitly approved.

The `identity` phase creates a dedicated Entra API app/SP and project read
role; `secret` creates the dedicated API key in the existing vault; `foundation`
creates only the new hosting identity and scoped pull/secret-read grants.
`publish` pushes the already reviewed image IDs; `application` deploys their
confirmed registry digests; `connection` creates the distinct Foundry
connection after readiness and authentication checks. It **does not change
the existing agent**: its output includes the tool attachment for separate
review before publishing a new agent version.

The deployment operator must already have the required Azure, Entra and
Key Vault permissions. Bicep does not grant the operator broad Secrets
Officer access. Existing names with unexpected ownership fail closed.
Every stage is durably claimed in a local journal before its first write.
A failed or uncertain stage is not automatically retried; inspect its
journal and scoped resources before preparing a recovery plan. Keep these
journals in an operator-controlled location.

`infra\main.bicep` uses `deployApplication=false` for the foundation, not a
placeholder application. Real deployment uses separate `mcpImage` and
`apiImage` digest parameters. The generic AppOnboard single-image and
new-vault/deployer-role checks do not describe this approved design; the
actual two-image wiring and secret-scoped access have dedicated checks.

### Rollback is containment, not deletion

```powershell
.\deploy\rollback.ps1 -Plan .build\reviewed-rollout.json
```

This prints a separate rollback approval hash. With explicit approval,
rollback disables only the newly created MCP service principal and requests
stop of the new Container App after live ownership checks. It does not
delete resources, groups, secrets, connections or agents. It remains
available if source files change or the build context is removed. Cloud
job completion and a later cleanup inventory require separate observation
and approval.

## Tests

```powershell
& $Python -m pytest -q
```

Tests were written and run failing before their corresponding implementation.
Coverage includes actual agent/SDK reuse, all six skills, strict argument
schemas, denied scopes, disabled writes, human approval separation, exact
hashes, deletion phrases, expiry/drift, single-use execution, uncertainty,
token verification, official MCP protocol sessions, client errors and the
Foundry model/tool loop. Azure dependencies are fake in the unit tests;
the Foundry host tests replace only the model boundary where appropriate.

The existing agent's test fixtures are reused intentionally, keeping contract
coverage aligned with the source implementation. Run from a matching checkout.
Test operation storage is in-memory only by explicit injection; production
continues to use the existing signed durable backend.

Live billing reads, destructive execution and full Azure provisioning require
their own configured scope, authorization and human-reviewed plans. A passing
local suite is not evidence that those permissions or resources exist.

The live read-only acceptance run used the supplied GPT 6.1 Sol deployment and
the existing agent instructions. The model called `factory_health` once through
a real stdio MCP subprocess, the actual agent adapter and the shared Python
API, then reported `status: ok`, API version `1.0.0`. It made no other tool
calls and changed no Azure deployment. The temporary loopback API process was
stopped after the run.