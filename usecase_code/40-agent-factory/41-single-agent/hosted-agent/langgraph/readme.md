# LangGraph helpdesk agent

`aif-langgraph` runs a small compiled `StateGraph`: a model node receives the
conversation and the evidence already retrieved by the shared host, calls the
Foundry Responses API, and returns the answer. It demonstrates graph-based
execution without pretending that a single model node is a multi-agent team.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json` through `aif-knowledge` and Foundry IQ. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | LangGraph | Microsoft Entra ID

Foundry conversation history is authoritative; this sample does not use a
process-global LangGraph checkpointer. The expanded profile adds read-only Azure
inventory through the same knowledge participant, not unrestricted tool access.
It does not train a model or process streaming events.

Deploy with `--agent aif-langgraph` using the
[shared hosted lifecycle](../readme.md#persistent-deployment-integration).
Source: [LangGraph](https://github.com/langchain-ai/langgraph).

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Python 3.13, PowerShell, Azure CLI OAuth, a configured consumer target and
  private Foundry/Search access; see [root prerequisites](../../../readme.md#prerequisites).
- An existing Foundry Responses-compatible model, hosted build/compute access,
  and runtime identity permissions. Follow [hosted prerequisites](../readme.md#prerequisites):
  verify ingestion and `knowledge.json` for this exact target/storage under the
  config directory's `.agent-factory\<account>\<project>`, then deploy the active
  knowledge prompt participant. Expanded-readonly needs verified private MCP too.

## How to set up the Python environment

Run at the factory root, **not** the `langgraph` directory. For a copied consumer,
substitute `C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` for the
first path. Replace the config placeholder and target with your actual values.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

No activation is needed. The root requirements install only the operator;
Foundry's Python 3.13 remote build installs [this runtime's requirements](requirements.txt),
including `langgraph`. Do not merge framework dependencies into the operator venv.
See [shared setup](../../../readme.md#how-to-set-up-the-python-environment).

## How to run the code

Use the same root/session. `aif` is the default `agent_prefix`; replace both agent
names' prefixes if the consumer config customizes it.

```powershell
# Offline help/plan; no Azure calls or model/runtime validation.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-langgraph
# Online, read-only Azure/network preflight.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
# MUTATING: after grounding verification, deploy the prompt participant first.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --apply
# MUTATING: requires an active knowledge participant.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-langgraph --apply
# Online inference, potentially billable.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-langgraph --input "How do I reset my password?"
```

Expect `mutations: false` from the plan, an `active` hosted version/ID from deploy,
and invocation JSON with `agent`, `response_id` and grounded `text` preserving
source links. The outer `tool_calls` can be empty because participant tool checks
run inside the host. These instructions do not claim a successful live run.

The raw `main.py` is not a workstation entry point. Deployment packages generated
`agent_spec.json` and shared `hosted_common.py`, and Foundry supplies
`FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_RESOURCE_ENDPOINT`,
`AZURE_AI_MODEL_DEPLOYMENT_NAME` plus managed/workload identity. Local CLI/browser
credentials are excluded. Use the [hosted workflow](../readme.md#how-to-run-the-code)
instead of executing the unprepared template locally.
