# Agent Factory implementation

This directory is a factory-neutral starter for persistent Foundry prompt agents,
framework-based hosted agents, and a hosted multi-agent team that calls separately
persisted knowledge and reviewer agents. Target names are discovered from ARM in
the selected project resource group; Bicep's generated resource-name salts are not
guessed.

Grounded answers must preserve the scope of their evidence. A generic procedure
is not proof that it applies to a named product or feature. When that applicability
is undocumented, the knowledge agent reports the gap instead of supplying generic
steps as a workaround; reviewers and hosted workers retain that limitation.

## Separation and template copying

- Make shared changes here in the purple repository, never in a consumer's submodule.
- `bootstrap/01-aif-copy-aifactory-templates.sh` already copies this entire directory
  to `aifactory-usecase-code/40-agent-factory` in a consumer repository.
- Keep project configuration at `aifactory/agent-factory/config.json`, outside that
  generated directory. The full bootstrap replaces generated use-case code.
- Copy `config.example.json` to that configuration location. Its `variables_file`
  is resolved relative to the config file, not the current working directory.
- Multiple named targets are supported in configuration. Every mutation selects
  exactly one target; there is deliberately no implicit subscription/fleet-wide write.
  Ambiguous accounts/projects require an explicit `selection`.

## Operator commands (PowerShell)

Run from the copied `aifactory-usecase-code\40-agent-factory` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$config = "..\..\aifactory\agent-factory\config.json"
.\.venv\Scripts\python.exe -m agent_factory plan --config $config
.\.venv\Scripts\python.exe -m agent_factory discover --config $config --output target.json
.\.venv\Scripts\python.exe -m agent_factory preflight --config $config
```

Use browser-based `az login --tenant <tenant-id>` only if cached OAuth is
unavailable. Device-code login, stored access tokens, account keys, and changing
the global active subscription are not part of this starter.

Private endpoint DNS and TCP reachability are checked before data-plane work.
`repair-dns` produces a read-only plan; adding `--apply` adds missing Foundry
zones to the existing approved endpoint's DNS zone group while preserving its
name, other zone associations, and ETag concurrency protection. It never changes
`centralDnsZoneByPolicyInHub` or enables public access. In policy-owned mode the
hub policy owner must retain all three Foundry zones in future remediations.

## Data and Foundry IQ

The example configuration selects Data Factory ingestion. Enable Data Factory
through the existing project pipeline first; its project UAMI and managed-VNet
integration runtime must be present. Configure task-owned copy artifacts and
approve only their two Blob private links (ADF and Search) on `2001` storage:

```powershell
.\.venv\Scripts\python.exe -m agent_factory configure-datafactory --config $config --apply
# Approve the specifically reported ADF and Search Blob connections on storage.
.\.venv\Scripts\python.exe -m agent_factory configure-datafactory --config $config --apply
.\.venv\Scripts\python.exe -m agent_factory start-datafactory --config $config --apply
.\.venv\Scripts\python.exe -m agent_factory poll-datafactory --config $config --apply --timeout-seconds 3600
```

Start once, then resume the saved run ID with `poll-datafactory`; do not create
another run while one is active. ADF verifies raw byte count/Content-MD5, projects
knowledge and evaluation columns into separate blobs, and validates row counts.
The private Search indexer reads only the published knowledge directory using
Search's managed identity. Verification compares all indexed knowledge against
the pinned corpus SHA-256 reference; Copy does not pretend to calculate SHA-256
or silently deduplicate. See `43-data/datafactory-guide.txt`.

Alternatively, run `43-data/worker.py` on already-approved Azure compute with the
selected project UAMI attached. Local operator OAuth cannot impersonate a managed
identity. This optional worker refuses unavailable UAMI authentication instead
of falling back to your user account. It uses a separate container/index from
ADF. Select a non-ADF ingestion mode only when intentionally using that path.

The pinned, public MIT Kaggle dataset is downloaded directly on that Azure host.
It writes only to the project's `2001` data storage, never the `1001` Foundry
metadata account. It preserves attribution and hashes, parses multiline CSV,
deduplicates knowledge documents, and keeps evaluation questions/ground truth
separate from the searchable knowledge.

The initial Foundry IQ path uses a semantic text index and an existing-index
knowledge source. This works with an appropriately configured Basic Search
service without embeddings or an automatic paid SKU upgrade. Private
`azureBlob` knowledge-source ingestion is a different capability that currently
requires S2 or above; this starter does not silently select it.

After managed-identity ingestion completes:

```powershell
.\.venv\Scripts\python.exe -m agent_factory configure-knowledge --config $config --apply
.\.venv\Scripts\python.exe -m agent_factory deploy --config $config --apply
.\.venv\Scripts\python.exe -m agent_factory deploy --config $config --agent aif-helpdesk-team --apply
.\.venv\Scripts\python.exe -m agent_factory invoke --config $config --agent aif-knowledge --input "How do I reset my password?"
```

`deploy` without selectors creates the three prompt agents. Use `--agent` to
select a hosted runtime, or `--include-hosted` for all catalog entries after
checking their prerequisites. Anthropic requires a separately configured,
compatible Foundry-hosted Claude deployment; it never falls back to a public
Anthropic endpoint. Hosted source deployment requires the account's supported
private network injection, regional availability, model permissions and allowed
build egress. See the hosted-agent readme for runtime details.

Versions and endpoint routes remain in Foundry; the scripts never delete agents
as sample cleanup. Matching owned definitions are reused; collisions with
unowned agents fail. Generated packages and per-project deployment records live
beside configuration under `.agent-factory`, not inside the replaceable templates.
An error after a partial deployment leaves the completed records for diagnosis.

## Agent Map / Map Agents To Departments

### Offline Monitoring ML reports

`monitoring-export` projects **recorded** results into `aifactory.monitoring/v1`.
It makes no Azure calls, writes only the requested local report/tag files, and
never deploys agents, publishes artifacts, or updates Azure tags. The standalone
entry point `python -m agent_factory.monitoring` accepts the same flags.

```powershell
python -m agent_factory monitoring-export `
  --input .\knowledge-result.json --source-format knowledge `
  --output .\monitoring-agent.json --tags-output .\monitoring-agent-tags.json `
  --aifactory my-factory --project 001 --environment dev `
  --subject aif-knowledge --version 1 `
  --window-start 2026-09-11T10:00:00Z --window-end 2026-09-11T10:05:00Z
```

Supply the actual factory identifier, three-digit project, environment, agent
name/version and **observation** window from your explicitly selected target.
These are never inferred from endpoints, resource names, ambient Azure context,
or an arbitrary first configured target. Existing `FactoryConfig` exposes
`project_number` and `environment`, but no authoritative factory identifier;
provide that explicitly. `stage` normalizes to `test`; `stage_prod` is a variables
section, not a valid environment. All three environments are supported.
If the input includes `scope`/`subject`, they must match the explicit selection.
Shared-service observations are attributed by the operator, not automatically
represented as per-agent measurements.

Supported source formats select narrow allowlists from existing JSON outputs:

| `--source-format` | Exported observations |
| --- | --- |
| `preflight` | `agent_count_on_page`, observed endpoint check/private/reachable counts, `foundry_access` and private endpoint check result |
| `knowledge` | `document_count`, `reference_count`, `retrieval_verified` |
| `ingestion` | `row_count`, `document_count`, `evaluation_count`, `blob_integrity.{raw,knowledge,evaluation}.bytes`, `corpus_sha256_verified` |
| `invocation` | Count of recorded `tool_calls`; never answer text, response IDs, or tool arguments |
| `deployment` | No measured agent metrics: lifecycle states such as active/created are not health checks |
| `metrics-only` | Every numeric/null leaf in a deliberately curated aggregate `metrics` object, with stable dotted names |

Example `metrics-only` input shape (illustrative values, **not live telemetry**):

```json
{
  "metrics": {
    "sample_count": 12,
    "error_count": 1,
    "latency": {"p95_ms": 420},
    "usage": {"input_tokens": 1200, "output_tokens": 300}
  },
  "units": {
    "sample_count": "count",
    "error_count": "count",
    "latency.p95_ms": "ms",
    "usage.input_tokens": "tokens",
    "usage.output_tokens": "tokens"
  },
  "checks": {"invocation_completed": true}
}
```

Only supply measurements already produced by your evaluation/usage/performance
collector. Current invocation/hosted summaries do **not** persist token usage or
latency, and ingestion evaluation counts are corpus sizes, not quality scores.
No sample counts, errors, durations, costs or scores are invented. Infrastructure
MCP/deployment details and raw SDK/tracing/billing payloads are not automatically
flattened: first select aggregate numeric fields into `metrics-only`. This
explicit coverage boundary avoids exporting prompts, responses, credentials,
user data, identifiers and arbitrary dimensions. Its only allowed top-level
keys are `metrics`, `units`, `checks`, and optional matching `scope`/`subject`.
Use stable aggregate names without embedded identifiers; do not put sensitive
numeric data into the curated metrics object.

Checks must be recorded booleans named `invocation_completed`,
`grounding_verified`, `retrieval_verified`, `foundry_access`,
`private_endpoints`, or `corpus_sha256_verified`. No checks means health
`unknown`, including when error count is zero. Failed checks mean `warning`,
never concept drift. Data drift and concept drift are always `not_supported`.
Metric status is `unknown` without a metric-specific assessment; null means
`insufficient_data`. Missing units are `unknown`; accepted units are `count`,
`ms`, `s`, `tokens`, `bytes`, `percent`, `ratio`, `USD`, `unitless`, `unknown`.

Inputs are bounded to 1 MiB, 128 metrics, six nested levels, and numeric/null
leaves only. Invalid names, duplicate keys, non-finite values and unsafe integers
are rejected rather than silently dropped. `details` contains only the projected
numeric aggregates and allowlisted checks. The report never copies raw input.
Timestamps require timezones and serialize to UTC `Z`; future observations and
inverted windows are rejected. `--generated-at` is optional; expiration is based
on **window end**, using `--ttl-hours` (default 24, maximum 720), not regeneration
time. Old observations remain `stale`.

`--tags-output` creates compact `mon_*` tags plus explicit
`aifactory`/`project`/`environment` identity. Optionally add `--report-uri` for an
**already published** credential-free Azure Blob or
`azureml://jobs/<job>/outputs/<output>/paths/<report>` artifact URI. Signed links,
queries, fragments and userinfo are rejected; no upload/tag write is performed.
The local contract fixture `tests/fixtures/monitoring-agent-v1.json` is generated
from fixture data, not Azure measurements. Run offline tests with
`python -m unittest discover -s tests -p test_monitoring.py`.

Every independently mappable participant is a persisted Foundry agent with a
stable name. Register the factory scope in the Config Wizard and refresh live
inventory in "Map Agents To Departments"; these examples do not alter local
department assignments or force the map out of mock mode.

String metadata records framework, execution kind, solution, participant role,
and an IT department hint. The current Wizard discovers these agents but does
not consume custom framework/solution metadata or draw true inter-agent edges.
Hosted tool discovery can therefore remain incomplete. Runtime orchestration
does not fabricate connected-agent tools to make the map look connected.

## Scope and prerequisites

The optional `expanded-readonly` tool profile adds a private, project-scoped
Azure MCP inventory service and role-appropriate evidence tools. See
[the Agent Factory tool reference](../../documentation/v2/30-39/agent-factory.md#optional-expanded-read-only-profile)
for the identity boundary, pinned image, MCP-only pipeline and approval behavior.
Use `44-azure-mcp/deploy.py plan` before identity preparation or deployment;
`configure-azure-mcp` must verify live private infrastructure before agent rollout.

No infrastructure SKU, model deployment, service-enable flag, shared VM identity,
or role assignment is changed implicitly. If infrastructure is missing, update
the consumer's reviewed `enable...` values and use its
`ADO-update-aifactory-and-run-project.sh` project pipeline. Do not run its broad
commit/copy path over unrelated dirty files. Any reusable infrastructure fixes
belong in the central purple templates.

API baseline: `azure-ai-projects==2.6.0`, Foundry API `v1`; hosted protocol and
framework dependencies are isolated per runtime. Search knowledge operations use
`2026-08-01-preview`. Preview region, quota, policy, and capability-host failures
are surfaced rather than presented as successful agent creation.

## Original design brief

# Creates agents in one to many AI Factory instances. 

- Single agents. And both prompt agents, and single agents
    - Foundry Agent Service will be used: https://learn.microsoft.com/en-us/azure/foundry/agents/overview
        -  Agent runtime: Hosts and scales prompt agents and Hosted agents. Manages conversations, tool calls, and agent lifecycle.
        -  Toolboxes: Curate a set of tools once, such as: web search, file search, code interpreter, MCP servers, and custom functions. Then share them across agents through a single managed MCP endpoint with centralized authentication, governance, and versioning.
        - Models: Works with many models from the Foundry model catalog, such as GPT-5.4, Llama, and DeepSeek. Swap models without changing your agent code.
        - Observability: End-to-end tracing, metrics, evaluations, and Application Insights integration. See every decision your agent makes and measure its quality.
        - Optimization:Agent optimizer (preview) evaluates agent behavior and automatically generates better instructions, skills, tool descriptions, and model selections for prompt agents and Hosted agents.
        - Identity and security: Microsoft Entra identity, RBAC, content filters, and virtual network isolation. Enterprise-grade trust built in.
        - Publishing: Version agents, create stable endpoints, and share through Microsoft Teams, Microsoft 365 Copilot, and the Entra Agent Registry.
        - Docs: https://learn.microsoft.com/en-us/azure/foundry/agents/overview
    - Types of agents: 
        - Prompt agents: You define prompt agents entirely through configuration, including instructions, model selection, and tools. Author them in the Foundry portal for a quick start, or define them programmatically with the SDKs or REST API to integrate with your CI/CD workflows. Either way, Foundry runs the agent for you. There's no application code to maintain, and no containers or packages to optimize, scale, or monitor for security.
            - Code first approach. using the SDK or REST API in your deployment pipeline, enabling version control, code review, and automated rollout.
        - Hosted agents: Hosted agents are code-based agents you build with Agent Framework, LangGraph, the OpenAI Agents SDK, the Anthropic Agent SDK, the GitHub Copilot SDK, or your own code. Ship your agent as either a container image or a .zip file of your source code (Foundry builds the image for you when you bring a .zip file), and Foundry runs it with a managed endpoint, automatic scaling, a dedicated Microsoft Entra identity, session-level state persistence, and end-to-end observability.
            - https://github.com/microsoft/agent-framework
            - https://github.com/openai/openai-agents-python
            - https://github.com/anthropics/anthropic-sdk-python
            - https://github.com/langchain-ai/langgraph
- Multi-agent scenarios, that uses the single agents created. 

# Data - Defaults in bootstrapping 
- Kaggle data right as demo, copied to Azure projects storage account with "2001" in its name. Not "1001", since dedicated for Foundry and its meta data
    - https://www.kaggle.com/datasets/dkhundley/sample-rag-knowledge-item-dataset

# Tools - RAG: Defaulst to use Foundry IQ
- The AI Search resource in each project resource group, next to Foundry

# Tools - MCP: Defaults to use MCP from Microsoft
- Foundry Agent service contains toolbox for: web search, file search, code interpreter, MCP servers, and custom functions
- 
