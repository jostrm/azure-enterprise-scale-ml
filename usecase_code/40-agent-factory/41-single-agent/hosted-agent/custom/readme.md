# Custom Responses helpdesk agent

`aif-custom` is the minimal Python implementation of the grounded hosted-agent
pattern. The shared host asks `aif-knowledge` for evidence, then this worker calls
Foundry's Responses API directly. Use it to understand the boundary between
hosting, retrieval and model inference without another agent framework.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json` through `aif-knowledge` and Foundry IQ. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Python / OpenAI client library | Microsoft Entra ID

There is no model-training job, batch-inference scheduler or streaming-event
consumer in this sample. The common host handles bounded history, cancellation,
managed identity and source-link preservation. The optional expanded profile
also permits evidence from the private Azure inventory tool.

Deploy with `--agent aif-custom` using the
[shared hosted lifecycle](../readme.md#persistent-deployment-integration).

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Python 3.13, PowerShell, Azure CLI OAuth, a configured consumer target and
  private Foundry/Search access; see [root prerequisites](../../../readme.md#prerequisites).
- An existing Foundry Responses-compatible model, hosted build/compute access
  and runtime identity permissions. Follow [hosted prerequisites](../readme.md#prerequisites):
  verify ingestion and `knowledge.json` for the same target/storage under the
  config directory's `.agent-factory\<account>\<project>`, then deploy the active
  knowledge prompt participant. Expanded-readonly additionally needs verified
  private MCP; a public OpenAI key is not used.

## How to set up the Python environment

Use the factory root, **not** this `custom` directory. For a copied consumer,
substitute `C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` for the
first path. Replace the config placeholder and target with real consumer values.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

No activation is needed. The root requirements are operator dependencies.
Foundry's Python 3.13 remote build installs [this runtime's requirements](requirements.txt):
the Responses host, Azure identity and OpenAI client, with no extra agent framework.
Keep runtime environments isolated; see [shared setup](../../../readme.md#how-to-set-up-the-python-environment).

## How to run the code

Continue in the same root/session. `aif` is the default `agent_prefix`; replace
both agent-name prefixes if your consumer uses another value.

```powershell
# Offline help/plan; no Azure calls or runtime/model validation.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-custom
# Online, read-only Azure/network preflight.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
# MUTATING: after grounding verification, deploy the prompt participant first.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --apply
# MUTATING: requires an active knowledge participant.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-custom --apply
# Online inference, potentially billable.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-custom --input "How do I reset my password?"
```

Expect a `mutations: false` plan, an `active` hosted version/ID from deployment,
and invocation JSON with `agent`, `response_id` and grounded `text` retaining
source links. Outer `tool_calls` may be empty; the host validates its knowledge
participant's call internally. These instructions do not assert live success.

Raw `main.py` is not a standalone workstation script. Deployment adds generated
`agent_spec.json` and shared `hosted_common.py`; Foundry supplies
`FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_RESOURCE_ENDPOINT`,
`AZURE_AI_MODEL_DEPLOYMENT_NAME` and managed/workload identity. Local CLI/browser
credentials are excluded. Use the [hosted workflow](../readme.md#how-to-run-the-code)
instead of trying to run the unprepared template locally.
