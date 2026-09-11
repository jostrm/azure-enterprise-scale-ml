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
