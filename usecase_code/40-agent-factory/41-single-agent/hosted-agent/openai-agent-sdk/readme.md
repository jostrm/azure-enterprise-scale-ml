# OpenAI Agents SDK helpdesk agent

`aif-openai-sdk` uses the OpenAI Agents SDK's `Agent`, `OpenAIResponsesModel`
and `Runner`, but model inference goes to the explicitly configured Microsoft
Foundry endpoint. The shared host supplies evidence from `aif-knowledge` before
the SDK synthesizes the answer.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json` through the persisted knowledge agent. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | OpenAI Agents SDK | Microsoft Entra ID

Public OpenAI tracing is disabled, and the model client uses Entra credentials
for Foundry rather than a public OpenAI API key. Runner turns are bounded.
The optional expanded profile accepts private Azure inventory from the
knowledge participant; it does not automatically install arbitrary SDK tools.

Deploy with `--agent aif-openai-sdk` using the
[shared hosted lifecycle](../readme.md#persistent-deployment-integration).
Source: [OpenAI Agents SDK](https://github.com/openai/openai-agents-python).

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Python 3.13, PowerShell, Azure CLI OAuth, a configured consumer target and
  private Foundry/Search access; see [root prerequisites](../../../readme.md#prerequisites).
- An existing Foundry Responses-compatible model, hosted build/compute access
  and runtime identity permissions, **not** a public OpenAI API key.
  Complete [hosted prerequisites](../readme.md#prerequisites): verified ingestion
  and `knowledge.json` for the exact target/storage under the config directory's
  `.agent-factory\<account>\<project>`, and an active knowledge prompt participant.
  Expanded-readonly also requires verified private MCP.

## How to set up the Python environment

Use the factory root, **not** `openai-agent-sdk`. For a copied consumer use
`C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` as the first path.
Replace the config placeholder and target with actual consumer values.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

No activation is needed. This installs only the operator; Foundry's Python 3.13
remote build installs [this runtime's requirements](requirements.txt), including
`openai-agents`. Do not merge other framework dependencies into this environment.
See [shared setup](../../../readme.md#how-to-set-up-the-python-environment).

## How to run the code

Continue in the same root/session. The catalog selector is `aif-openai-sdk`
(not `aif-openai-agent-sdk`). Replace `aif` in both names if `agent_prefix` differs.

```powershell
# Offline: help and a config/catalog plan; no Azure calls or runtime validation.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-openai-sdk
# Online, read-only Azure/network preflight.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
# MUTATING: after grounding verification, deploy the prompt participant first.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --apply
# MUTATING: requires an active knowledge participant.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-openai-sdk --apply
# Online inference, potentially billable.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-openai-sdk --input "How do I reset my password?"
```

Expect `mutations: false` in the plan, an `active` hosted version/ID from deploy,
then JSON with `agent`, `response_id` and grounded `text` retaining source links.
The outer `tool_calls` may be empty because knowledge-tool checks occur in the
host. No live deployment or successful invocation is claimed here.

Do not run raw `main.py` locally. The deployment adds generated `agent_spec.json`
and shared `hosted_common.py`; Foundry sets `FOUNDRY_PROJECT_ENDPOINT`,
`FOUNDRY_RESOURCE_ENDPOINT` and `AZURE_AI_MODEL_DEPLOYMENT_NAME`, then starts the
worker with managed/workload identity. It excludes local CLI/browser credential
fallbacks. Follow the [hosted workflow](../readme.md#how-to-run-the-code); supplying
a public provider key is not a substitute.
