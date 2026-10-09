# Anthropic agents

`aif-anthropic` is a template for answering grounded text questions with a
Foundry-hosted Claude model. The shared host obtains evidence from the persisted
knowledge agent; the runtime uses `AsyncAnthropicFoundry` to call the Messages API.
This is the **Anthropic Python Messages SDK**, not Claude Code or the Claude
Agent SDK.

## Use case summary

- Use case type: RAG with LLM (implemented template; compatible model deployment required)
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus when deployed
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json` through `aif-knowledge`. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Anthropic Python SDK | Microsoft Entra ID

Configure `model_overrides.anthropic-agents` with an actual compatible Claude
deployment in the selected Foundry account. The reference rollout left this
agent undeployed because that prerequisite was absent. An implemented template
is not evidence that a Claude deployment or agent exists in a target.

The runtime rejects Anthropic API keys, uses Entra authentication, and never
substitutes GPT or the public Anthropic endpoint. Model availability and terms
must be handled explicitly before `--agent aif-anthropic` deployment.

See [hosted prerequisites](../readme.md#framework-prerequisites-and-boundaries)
and the [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python).

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Python 3.13, PowerShell, Azure CLI OAuth, a configured consumer target,
  private Foundry/Search connectivity and [root prerequisites](../../../readme.md#prerequisites).
- An **approved, compatible Anthropic Claude deployment in this Foundry account**:
  regional/tenant eligibility, model terms, Messages API support, hosted build
  access and runtime identity RBAC must already be established.
  A GPT deployment or external model connection is rejected.
- In the consumer config, add/update just the `anthropic-agents` entry in
  `model_overrides` with the real deployment name, preserving other overrides:

  ```json
  "model_overrides": {
    "anthropic-agents": "<approved-foundry-claude-deployment>"
  }
  ```

  This is a config fragment, not a complete file. Do not substitute a model-family
  name, public Anthropic URL or API key. The knowledge prompt participant still
  needs its own compatible Foundry model from the target/prompt override.
- Follow [hosted prerequisites](../readme.md#prerequisites): verified ingestion
  and `knowledge.json` for this target/storage under the config directory's
  `.agent-factory\<account>\<project>`, then an active knowledge prompt agent.
  Expanded-readonly also needs verified private MCP. Without the approved Claude
  deployment, stop after offline planning: this remains a template, not a runnable
  alternative backed by GPT or a public provider.

## How to set up the Python environment

Use the factory root, **not** `anthropic-agents`. For a copied consumer use
`C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` as the first path.
Replace the config placeholder and target with actual consumer values.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

No activation is needed. This installs the operator, not the Anthropic runtime.
Foundry's Python 3.13 remote build installs [this runtime's requirements](requirements.txt),
including `anthropic`. Do not combine runtime frameworks or install Claude Code/
Claude Agent SDK instead. See [shared setup](../../../readme.md#how-to-set-up-the-python-environment).

## How to run the code

Continue in the same root/session. `aif-anthropic` is the catalog selector.
Replace `aif` in both names if your config customizes `agent_prefix`.

```powershell
# Offline help/plan: this does NOT verify Claude deployment availability.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-anthropic
```

**Only after all prerequisites, including approved Foundry Claude, are met:**

```powershell
# Online, read-only Azure/network preflight; not a Claude compatibility test.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
# MUTATING: after grounding verification, deploy the prompt participant first.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --apply
# MUTATING: validates the explicit local Claude deployment and active participant.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-anthropic --apply
# Online inference, potentially billable.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-anthropic --input "How do I reset my password?"
```

The plan reports `mutations: false`; a successful deployment would report an
`active` hosted version/ID, and invocation would return JSON with `agent`,
`response_id` and grounded `text` retaining source links. Outer `tool_calls`
may be empty because the host verifies its knowledge participant internally.
No Claude deployment or live success is asserted by these instructions.

Do not run raw `main.py` on a workstation. Deployment adds generated
`agent_spec.json` and shared `hosted_common.py`; Foundry supplies
`FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_RESOURCE_ENDPOINT`,
`AZURE_AI_MODEL_DEPLOYMENT_NAME` and managed/workload identity.
The worker excludes local CLI/browser credentials and rejects Anthropic API keys.
Use the [hosted workflow](../readme.md#how-to-run-the-code); there is no public fallback.
