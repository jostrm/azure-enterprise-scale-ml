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
- Data sources: `<selected-storage>/<selected-container>/kaggle-rag-v1/knowledge/items.json`, through Azure AI Search and Foundry IQ. See [source paths](../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Microsoft Entra ID | Python framework for hosted variants

The pipe-separated entries are applicable values, not a claim that every
available technology or data type is used. The dataset count is a count of
distinct source corpora, not files, agents, chunks or evaluation rows.

## Choose an authoring approach

| Folder | Use when |
| --- | --- |
| [prompt-agent](prompt-agent/readme.md) | Instructions and managed tools are sufficient; no custom runtime is required. |
| [hosted-agent](hosted-agent/readme.md) | You need framework code or custom execution while retaining Foundry hosting. |

The optional expanded profile adds read-only Azure inventory. That inventory is
live operational metadata, not another training dataset. Public Microsoft Learn
calls require approval. Neither a streamed HTTP response nor batch ingestion
makes these examples streaming-data or batch-inference pipelines.
