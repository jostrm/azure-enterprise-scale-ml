# Foundry prompt agents

This folder describes the agents created by the shared catalog and prompt
deployment code. Foundry runs their model and managed tool calls; there is no
application server to implement here.

## Use case summary

- Use case type: RAG with LLM (knowledge and documentation); LLM evidence review is a supporting role
- Data type: Tabular | Document (CSV-packaged articles and retrieved text)
- Number of source data sets: 1 for `aif-knowledge`; 0 for the default reviewer and public-documentation agent; the expanded reviewer reuses the same 1 corpus
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json` via Foundry IQ; see [source paths](../../43-data/readme.md#data-sources-and-lake-layout). Microsoft Learn uses `https://learn.microsoft.com/api/mcp`, not a lake dataset.
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Microsoft Learn MCP | Microsoft Entra ID

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Python 3.13, PowerShell, Azure CLI OAuth, private Foundry/Search connectivity,
  and operator/project identity permissions from the [root prerequisites](../../readme.md#prerequisites).
- A consumer `aifactory\agent-factory\config.json`, its variables file, an existing
  project and compatible model deployment. `aif` below is the default
  `agent_prefix`; replace all agent-name prefixes if customized.
- Before deploying `aif-knowledge`, complete [ingestion](../../43-data/readme.md)
  and [Foundry IQ configuration/verification](../../readme.md#how-to-run-the-code).
  The config directory's `.agent-factory\<account>\<project>\knowledge.json`
  must record verified retrieval for this target, project connection and storage
  selection; ADF mode also needs verified `ingestion.json`.
- The expanded profile additionally requires [verified private MCP](../../44-azure-mcp/readme.md).
  The default reviewer needs supplied evidence, not its own corpus.
  Microsoft Learn tools always require approval and must never receive private data.

## How to set up the Python environment

Run from the factory root, **not** `prompt-agent`. A copied consumer uses
`C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` instead of the
source-tree path below. Replace `$Config` and `$Target` with your actual values.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

These are the operator requirements; prompt agents have no local `main.py` or
framework runtime to install. Activation is unnecessary; see
[shared Python setup](../../readme.md#how-to-set-up-the-python-environment).

## How to run the code

Continue in the same factory-root PowerShell session:

```powershell
# Offline help and explicit catalog selection; no Azure calls.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-reviewer --agent aif-docs

# Online, read-only Azure/network checks; this does not verify grounding.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target

# MUTATING: after the grounding prerequisites; creates/reuses and routes prompt versions.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --agent aif-reviewer --agent aif-docs --apply

# Online inference (potentially billable), one exact agent per call.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-knowledge --input "How do I reset my password?"
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-reviewer --input "Review this draft: Everyone must reset passwords daily. No supporting evidence was supplied. Identify unsupported claims."
```

The plan reports `mutations: false`; deploy reports version/ID records with
`created` or `unchanged`. A successful invocation returns `agent`, `response_id`
and `text`; knowledge must also show a successful `knowledge_base_retrieve`
tool call. The default reviewer should identify the missing evidence.
For `aif-docs`, use an approval-capable Foundry client/playground: this CLI does
not implement the approval-response round trip, so a tool-approval request is
not a successful answer. Do not disable approvals to make an invocation pass.
These commands are instructions, not evidence of a live deployment.

## Roles and actual tools

| Agent | Default behavior | Expanded read-only profile |
| --- | --- | --- |
| `aif-knowledge` | Retrieves synthetic helpdesk evidence with `knowledge_base_retrieve`. | Also calls `group_resource_list` on the private Azure MCP server. |
| `aif-reviewer` | Reviews supplied drafts/evidence; no default tools. | Adds Foundry IQ and private Azure inventory. |
| `aif-docs` | Uses approval-gated `microsoft_docs_search` and `microsoft_docs_fetch`. | Adds approval-gated `microsoft_code_sample_search` and private Azure inventory. |

The ingestion chain applies to helpdesk grounding; documentation-only questions
do not execute ADF or read the lake. Public documentation queries must not include
private tenant data. An unsupported product-specific question should expose the
evidence gap rather than relabel a generic helpdesk procedure as product guidance.

Definitions live in [catalog.py](../../agent_factory/catalog.py); lifecycle and
tool configuration live in [prompt.py](../../agent_factory/prompt.py).
Use the [operator commands](../../readme.md#how-to-run-the-code) from the
Agent Factory root with the consumer's explicit configuration.

The [data guide](../../43-data/readme.md) explains the selected common/project
storage corpus and the separate common-lake RAG snapshot.