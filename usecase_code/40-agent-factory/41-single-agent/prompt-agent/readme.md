# Foundry prompt agents

This folder describes the agents created by the shared catalog and prompt
deployment code. Foundry runs their model and managed tool calls; there is no
application server to implement here.

## Use case summary

- Use case type: RAG with LLM (knowledge and documentation); LLM evidence review is a supporting role
- Data type: Tabular | Document (CSV-packaged articles and retrieved text)
- Number of source data sets: 1 for `aif-knowledge`; 0 for the default reviewer and public-documentation agent; the expanded reviewer reuses the same 1 corpus
- Data sources: No master-lake binding yet; `<project-data-storage>/agent-factory-adf/kaggle-rag-v1/knowledge/items.json` via Foundry IQ. Microsoft Learn uses `https://learn.microsoft.com/api/mcp`, not a lake dataset.
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Microsoft Learn MCP | Microsoft Entra ID

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
Use the [operator commands](../../readme.md#operator-commands-powershell) from the
Agent Factory root with the consumer's explicit configuration.

The [data guide](../../43-data/readme.md) distinguishes the currently indexed
project-storage corpus from the separate common-lake RAG snapshot.