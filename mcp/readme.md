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