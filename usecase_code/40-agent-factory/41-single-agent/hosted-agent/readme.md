# Hosted agents

Hosted agents are code-based agents you build with Agent Framework, LangGraph, the OpenAI Agents SDK, the Anthropic Agent SDK, the GitHub Copilot SDK, or your own code. Ship your agent as either a container image or a .zip file of your source code (Foundry builds the image for you when you bring a .zip file), and Foundry runs it with a managed endpoint, automatic scaling, a dedicated Microsoft Entra identity, session-level state persistence, and end-to-end observability.

Under the hood, your agent code calls your Foundry project endpoint for model inference and tool orchestration, which gives you access to Foundry models from the catalog and a unified set of platform tools: standard tools like file search, code interpreter, and web search, plus additional tools like SharePoint, WorkIQ, and Fabric IQ.

Best for: Agents that call into your own custom code; secondarily, custom orchestration logic, multi-agent systems, and custom protocols (webhooks, voice, AG-UI) where you want full control over agent logic while letting Foundry handle hosting, scaling, and identity.

# Compare agent types
Prompt agents	Hosted agents
Authoring surface	Portal, SDK, or REST	Agent Framework, LangGraph, OpenAI Agents SDK, Anthropic Agent SDK, GitHub Copilot SDK, custom code
Foundry models + platform tools	Yes	Yes (via the Responses API on the Foundry project endpoint)
Skill support	Yes	Yes
Runtime code to maintain	None	Yes, your agent logic
Compute to manage	None, fully managed	Container compute, Foundry-managed
Managed endpoint	Yes	Yes
Autoscale	Automatic, Foundry-managed; scales with request volume	Automatic, Foundry-managed; scales container instances per session and request volume
Agent identity (Entra)	Yes	Automatic, dedicated per agent
Cost model	Per-call inference + tool usage	Per-call inference + tool usage + container compute
Best for	Fast start, production agents without custom orchestration	Agents that call into custom code; secondarily, custom orchestration logic

# Use the Responses API for ephemeral agents
When you call the Responses API directly from your own code, you build an ephemeral agent: the agent's definition (instructions, tools, and model) lives in your application code instead of as a persisted resource in Foundry. Each call assembles the agent in your process and runs it against the Responses API, so there's no agent to create, update, or delete in Foundry.

Use this pattern when you want:

Agent logic that ships with your app. The definition versions alongside the rest of your code through source control and code review, instead of as a separate Foundry resource that someone has to keep in sync with the app.
Foundry capabilities without the resource overhead. You still get catalog models, platform tools, project-scoped data, On-Behalf-Of authentication, and project-level observability and governance. All through your Foundry project endpoint.
See Quickstart: Use the Responses API for information.

# Model support
- Agent Service works with many models available in the Foundry model catalog. 
- For the full list, see the Foundry portal: https://ai.azure.com/catalog/models?capabilities=agentsv2&cid=learnDoc


# Tools and toolboxes
Agents act on the world through tools. Foundry offers built-in tools such as web search, file search, code interpreter, and memory, while also letting you add custom tools through functions, OpenAPI specs, and MCP servers. For the full set, see the toolbox overview.

A toolbox groups those tools into a single, reusable unit. You curate the tools once, and Foundry exposes them behind one managed MCP-compatible endpoint that any agent or runtime can consume, regardless of framework. Toolboxes centralize authentication, governance, and versioning, so you update tools in one place instead of rewiring every agent. Create a new version, test it, and promote it to default when you're ready. To learn more, see What is Toolbox in Foundry?.

# Connect and authenticate to MCP remote servers

Foundry supports remote MCP servers that you can add to your agent, such as the Azure DevOps MCP Server. Connect your Azure DevOps organization to enable agent access, and configure a subset of available tools to control which actions agents can perform. You can also connect custom MCP servers hosted on Azure Functions using the Functions MCP webhook endpoint (/runtime/webhooks/mcp) to expose custom tools to your agents.

Supported authentication options for MCP servers and other tool connections include:

Key-based access
Microsoft Entra (using the agent's managed identity or the project's managed identity)
OAuth identity passthrough (On-Behalf-Of)
Unauthenticated access, where appropriate
These authentication options also apply when connecting remote MCP servers, with credentials and scopes managed in the tool configuration.

# Development lifecycle
Agent Service supports the full build-test-deploy-monitor workflow:

Create: Define a prompt agent in the portal or with the SDK, or write a Hosted agent that calls the Responses API.
Test: Chat with your agent in the agents playground or run locally. MCP server integrations, including custom MCP servers hosted on Azure Functions, can be exercised directly in the playground to validate tool connectivity, permissions, and behavior before publishing.
Trace: Inspect every model call, tool invocation, and decision with agent tracing.
Evaluate: Run evaluations to measure quality and catch regressions.
Optimize: Automatically improve your hosted agent's instructions using the agent optimizer.
Publish: Promote your agent to a managed resource with a stable endpoint.
Monitor: Track performance and reliability with service metrics and dashboards.
For a detailed walkthrough, see Agent development lifecycle.

# Enterprise capabilities
Agent Service provides enterprise-grade infrastructure for every agent you deploy:

Agent identity: Each agent can have a dedicated Microsoft Entra identity, enabling secure, scoped access to resources and APIs without sharing credentials. Agent identities can authenticate to external MCP servers, including those hosted on Azure Functions, and OAuth On-Behalf-Of (OBO) passthrough is supported when configured.
Private networking: Run agents within your Azure virtual network for full network isolation and compliance with data residency requirements. Private networking is available for prompt agents. Hosted agents support bring-your-own Azure Virtual Network (BYO VNet), where each session runs in a VM-isolated sandbox connected to your VNet.
Role-based access control: Fine-grained permissions through Microsoft Entra and Azure RBAC. Control who can create, invoke, and manage agents.
Content safety: Integrated content filters help mitigate prompt injection risks (including cross-prompt injection) and prevent unsafe outputs.
For environment setup instructions, see Set up your environment.

# Publishing and sharing
Agent Service provides built-in versioning and publishing so your agents can move from development to production with confidence.

Versioning: As you iterate on your agent, versions are automatically snapshotted. Roll back to any previous version or compare changes between versions.
Publishing: Promote an agent to a managed resource with a stable endpoint. Published agents inherit the enterprise identity and access controls configured for your project and can be invoked programmatically.
Distribution: Share published agents through Microsoft 365 Copilot and Teams and the Entra Agent Registry, putting your agents where your users already work. Foundry Agent Service supports the OpenResponses and Activity Protocols for Microsoft 365 publishing, an Invocations protocol for flexible endpoint integration with custom apps and services, and the A2A protocol (preview) for agent-to-agent communication.
Security, privacy, and compliance
Agent Service is designed for enterprise workloads where you need strong controls over identity, networking, data handling, and safety.

Safety controls: Use integrated guardrails to help reduce unsafe outputs and mitigate prompt injection risks, including cross-prompt injection attacks (XPIA).
Network isolation and data residency controls: Use virtual networks and bring-your-own resources to meet your requirements.
Bring your own resources: Use your own Azure resources (for example, storage, Azure AI Search, and Azure Cosmos DB for conversation state) to meet compliance and operational needs. See Use your own resources.
Responsible AI guidance: For a broader set of recommendations and governance resources, see Responsible AI for Microsoft Foundry.

## Runnable factory examples

The factory now packages seven independent Responses-protocol workers. Existing
content above is retained as background guidance; the code and pinned SDK
contracts below determine what these examples implement.

| `framework` | Runtime implementation |
|---|---|
| `agent-framework` | Microsoft Agent Framework `Agent` and `OpenAIChatClient` (Responses), using an explicit Foundry-authenticated client |
| `langgraph` | A compiled LangGraph `StateGraph` with a Foundry model node |
| `openai-agent-sdk` | OpenAI Agents `Agent`, `OpenAIResponsesModel`, and `Runner`, with public OpenAI tracing disabled |
| `anthropic-agents` | Anthropic Python SDK `AsyncAnthropicFoundry` Messages client with Entra authentication; **not Claude Code or the Claude Agent SDK** |
| `github-copilot-sdk` | GitHub Copilot SDK BYOK Responses provider with an on-demand Azure Entra token provider; GitHub auto-login and public-model fallback disabled |
| `custom` | An asynchronous custom Foundry Responses worker |
| `multi-agent` | `42-multi-agent\main.py`: sequential knowledge retrieval, evidence-aware review, then synthesis using the existing persisted participants |

These are text examples. They replay the last 20 platform history items, cap input
at 60,000 characters, and cancel async work on disconnect/cancellation or after
180 seconds. Model calls have timeouts, bounded outputs and limited retries.
There is no process-global conversation store. Clients must continue the same
Foundry conversation to retain platform history. Images, attachments and complete
tool-call histories are not reconstructed.

### Offline package and local run

From `usecase_code\40-agent-factory`, with Python 3.13:

```python
from pathlib import Path
from agent_factory.hosted import build_package

package = build_package({
    "name": "factory-custom",
    "framework": "custom",
    "instructions": "Answer questions briefly and state uncertainty.",
    "description": "Custom hosted example",
    "metadata": {},
}, Path("artifacts"))
print(package)
```

ZIP creation does not contact Azure. Its only entries are `main.py`,
`requirements.txt`, `hosted_common.py`, and `agent_spec.json`. ZIP timestamps,
ordering and permissions are fixed, so identical inputs produce identical bytes.
Readmes, `.env`, caches, credentials, virtual environments and unrelated files
are never discovered or copied into the ZIP.

Extract the ZIP into a fresh directory, create a virtual environment there, and
install **that ZIP's** `requirements.txt`. Set `FOUNDRY_PROJECT_ENDPOINT` to the
canonical `https://ACCOUNT.services.ai.azure.com/api/projects/PROJECT` endpoint
and `AZURE_AI_MODEL_DEPLOYMENT_NAME` to an existing deployment. Run `python main.py`.
Use the Azure host's managed/workload identity; local user credential fallbacks
are disabled. Do not put credentials into JSON, environment definitions or ZIPs.
The factory neither signs you in nor provisions models or identity role assignments.

Keep each example's requirements isolated from the deployment environment and
from other framework adapters. The current pinned examples use OpenAI 3 where
needed; earlier OpenAI 2 adapters must not be combined with Projects 2.6.
Pins are direct requirements, not complete transitive supply-chain lockfiles.

### Persistent deployment integration

```python
from agent_factory.hosted import deploy_hosted

record = deploy_hosted(
    project_client, target, spec,
    output_dir=Path("artifacts"),
    timeout_seconds=900,
)
# Actual service identifiers: name, version, id, status, framework.
```

`project_client` is the caller's `azure-ai-projects==2.6.0` client; `target` is
`agent_factory.config.Target`. This function never creates a credential/client,
chooses a subscription, creates prompt agents, assigns RBAC or deletes agents.
Calling it **does** create/reuse a hosted version and route its endpoint.
Deployment and invocation must be exercised in the selected Azure environment;
offline contract tests alone do not establish runtime or network availability.

The spec fields are `name`, `kind="hosted"`, `framework`, `instructions`,
`description`, `metadata`, optional `model`, and `members`. Single-agent workers
consult configured persisted members before framework inference; the knowledge
member must actually call Foundry IQ. The team passes prior findings to each
subsequent participant, so its reviewer receives the grounded draft. These are
real dependencies, not fabricated tools or automatically rendered map edges.
Source URLs from Foundry response annotations are retained as ordinary Markdown
links after rewriting; opaque citations from an upstream response are not assumed
to remain resolvable in a different response.
Agent names must start/end
alphanumeric, may contain internal hyphens, and be at most 63 characters.
Metadata reserves `aifactory.managed_by` and `aifactory.definition_hash`.
The factory refuses existing names not owned by `40-agent-factory` and refuses
disabled agents. It reuses `AgentDetails.versions.latest` only when its hash of
package, normalized spec, runtime settings and target environment matches.
Provisioning is polled through `get_version` until `active`; `failed`, `deleted`,
`deleting` and timeouts raise instead of being reported as success. There is no
obsolete replica/start call. Concurrent deployments of the same name require
external serialization.

### Framework prerequisites and boundaries

* All workers require a deployed, API-compatible model, model-inference RBAC
  for the runtime identity, and network access to the selected Foundry account.
  Default environment credentials are excluded; no client secret is used.
* Anthropic requires **explicit `spec.model`**, and the deployment lookup must
  identify a locally deployed Anthropic Claude model. A GPT model, missing
  deployment or external connection raises `HostedPrerequisiteError`. Tenant,
  regional availability, marketplace/model terms and Messages compatibility
  remain prerequisites. It never calls the public Anthropic endpoint.
* Copilot BYOK requires its SDK-compatible native runtime, supplied through the
  SDK's supported runtime configuration/cache, or release-download access for
  its pinned, checksum-verified runtime bootstrap. Downloading SDK software is
  distinct from model inference: inference and refreshed OAuth tokens only go
  to Foundry. Private networks without those artifacts must stage them first.
  SDK/runtime terms and deployment eligibility still apply. No GitHub login is
  attempted. Child processes receive no inherited GitHub/model keys, and have
  no built-in tools, filesystem permissions, MCP servers, config discovery,
  skills, shell actions or host Git operations enabled.
* Microsoft Learn MCP is optional and is **not auto-enabled** in these workers.
  Provision a read-only Learn or RAG prompt agent separately and list it as a
  coordinator member rather than copying data-access authentication here.
* Source deployment uses Python 3.13, remote dependency build, 0.5 CPU, 1 GiB,
  and Responses protocol 2.0.0. Private-network routing, package-build access,
  hosted quotas and identity grants must be established outside this module.

### Reusing persisted participants and Agent Map

```python
spec = {
    "name": "factory-coordinator",
    "framework": "multi-agent",
    "instructions": "Synthesize evidence, preserve citations, and flag conflicts.",
    "description": "Consults separately deployed prompt agents",
    "metadata": {},
    "members": [
        {"name": "knowledge", "role": "Ground answers in enterprise data"},
        {"name": "reviewer", "role": "Review evidence and limitations"},
    ],
}
```

Deploy the two prompt participants first. The coordinator verifies that each
exists as an active prompt agent, invokes it by `agent_reference.name`, and
never recreates or deletes it. It consults every member once, with at most six
distinct members. Member roles label evidence for synthesis; their separately
persisted instructions are not overwritten. References resolve by name, so
future participant releases can be reused without rebuilding the coordinator.

All deployed hosted and prompt resources persist and can be discovered by name.
**Custom relationship metadata does not create Agent Map graph edges.** The
current map's name discovery does not interpret it. This coordinator therefore
does not claim that its consultation relationships automatically render as edges.

### Validation and source contracts

Run `python -m unittest discover -s tests -p test_hosted.py -v` from the factory
directory. Tests cover package inclusion/exclusion, reproducibility, safe names,
ownership, idempotency, explicit failures, prerequisites, history and cancellation.

Public contract references:

* [Projects 2.6 source ZIP deployment](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.6.0/sdk/ai/azure-ai-projects/azure/ai/projects/operations/_patch_agents.py)
* [Official three-argument Responses handler and platform history example](https://github.com/microsoft-foundry/foundry-samples/blob/main/samples/python/hosted-agents/bring-your-own/responses/hello-world/src/hello-world-python-responses/main.py)
* [Official OpenAI Agents hosted example](https://github.com/microsoft-foundry/foundry-samples/blob/main/samples/python/hosted-agents/bring-your-own/responses/openai-agents-sdk/src/openai-agents-sdk-invocations/main.py)
* [Agent Framework OpenAI adapter](https://github.com/microsoft/agent-framework/tree/main/python/packages/openai)
* [Anthropic Foundry client](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/lib/foundry.py)
* [Copilot BYOK](https://github.com/github/copilot-sdk/blob/main/docs/auth/byok.md) and [Azure Entra identity](https://github.com/github/copilot-sdk/blob/main/docs/setup/azure-managed-identity.md)