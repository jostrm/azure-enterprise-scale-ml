# Single-agent examples

These examples answer text questions using Microsoft Foundry. Prompt agents keep
their instructions and tools in Foundry; hosted agents run a selected Python
framework and consult the persisted knowledge agent before generating an answer.
They demonstrate retrieval-augmented generation, not model training.

All prompt and hosted frameworks inherit the
[root common/project storage selection](../readme.md#one-storage-selection-for-every-example)
through ingestion and Foundry IQ; there are no per-framework account/container
paths to edit. Foundry, Search and runtime identities remain project-scoped.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (the source CSV contains Markdown knowledge articles)
- Number of source data sets: 1 shared helpdesk corpus; 0 for a standalone reviewer or documentation-only agent
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json`, through Azure AI Search and Foundry IQ. See [source paths](../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Microsoft Entra ID | Python framework for hosted variants

The pipe-separated entries are applicable values, not a claim that every
available technology or data type is used. The dataset count is a count of
distinct source corpora, not files, agents, chunks or evaluation rows.

For an explicit common/project storage profile, `<ADF-prefix>` is
`kaggle-rag-v1/adf/<project-id-hash>`; use the ingestion result's actual prefix.
Only legacy omitted-flag ADF mode uses `kaggle-rag-v1` without that project suffix.

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Follow the [root prerequisites](../readme.md#prerequisites): Python 3.13,
  PowerShell, Azure CLI with browser-based OAuth for the selected tenant, and
  private Foundry/Search connectivity and required operator/runtime RBAC.
- Use the consumer's `aifactory\agent-factory\config.json` and its referenced
  variables file, with an existing Foundry project and compatible model deployment.
- For the knowledge example below, complete [data ingestion](../43-data/readme.md)
  and the [root grounding workflow](../readme.md#how-to-run-the-code) first.
  `ingestion.json` (ADF mode) and `knowledge.json` must verify this exact target
  and storage selection under the config directory's
  `.agent-factory\<account>\<project>`; do not copy journals from another target.
- Hosted choices additionally need hosted compute/build access, runtime identity
  permissions and an active knowledge prompt participant; see their linked guides.

## How to set up the Python environment

Use the **factory root**, not this subfolder. For a copied consumer tree, substitute
`C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` for the first path.
Replace the config placeholder and target with your real consumer settings.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

This installs only the operator dependencies. No shell activation is needed.
Hosted framework requirements stay isolated in their deployment packages.
See [shared Python setup](../readme.md#how-to-set-up-the-python-environment).

## How to run the code

This concrete first run selects the prompt-based knowledge agent. `aif` is the
default `agent_prefix`; replace it in every agent name if your config customizes it.
Run in the same PowerShell session and factory-root directory as above:

```powershell
# Offline: help and a config/catalog plan; no Azure calls or deployment.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge

# Online, read-only Azure/network preflight; requires OAuth and private access.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target

# MUTATING: only after ingestion and Foundry IQ verification; creates/routes the agent.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --apply

# Online inference, potentially billable; exactly one agent per invocation.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-knowledge --input "How do I reset my password?"
```

Expect an offline plan with `mutations: false`, then deployment identifiers and
an invocation JSON containing `agent`, `response_id`, `text` and a successful
`knowledge_base_retrieve` tool call. Missing evidence must remain explicit.
Preflight alone does not prove retrieval or inference. No live success is implied
by these instructions. If `tool_profile` is `expanded-readonly`, also complete
the [private MCP setup and verification](../44-azure-mcp/readme.md) before deployment.

## Choose an authoring approach

| Folder | Use when |
| --- | --- |
| [prompt-agent](prompt-agent/readme.md) | Instructions and managed tools are sufficient; no custom runtime is required. |
| [hosted-agent](hosted-agent/readme.md) | You need framework code or custom execution while retaining Foundry hosting. |

The optional expanded profile adds read-only Azure inventory. That inventory is
live operational metadata, not another training dataset. Public Microsoft Learn
calls require approval. Neither a streamed HTTP response nor batch ingestion
makes these examples streaming-data or batch-inference pipelines.
