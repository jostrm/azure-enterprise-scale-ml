# Shared Agent Factory operator and runtime support

This Python package implements the reusable control plane behind the examples:
target discovery, private-network checks, ingestion, Foundry IQ configuration,
prompt/hosted deployment and invocation. Keep customer resource selections in
the consumer's configuration, not in this package.

## Use case summary

- Use case type: RAG with LLM (shared implementation support, not a separate agent)
- Data type: Tabular | Document (helpdesk ingestion); structured JSON configuration and operational metadata
- Number of source data sets: 1 for the helpdesk ingestion path; 0 for deployment, Azure inventory and offline monitoring
- Data sources: `<selected-storage>/<selected-container>/kaggle-rag-v1/knowledge/items.json`, or a pinned `45-rag-agent` corpus. See [storage selection](../readme.md#one-storage-selection-for-every-example).
- Inference type: Online (invocation) | Batch (ingestion preparation only); configuration/monitoring commands do not infer
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Microsoft Entra ID | Azure Container Apps / Azure MCP in the expanded profile

## Responsibilities

| Modules | Responsibility |
| --- | --- |
| `config`, `azure`, `discovery`, `network` | Explicit target selection, OAuth, actual resource discovery and private-network checks. |
| `data`, `datafactory`, `knowledge` | Pinned corpus preparation, evaluation separation and Foundry IQ setup. |
| `catalog`, `prompt`, `hosted`, `cli` | Agent roles, allowed tools, persistent versions, package construction and invocation. |
| `mcp_control`, `mcp_connection` | Private Azure MCP identity, infrastructure preflight, DNS/connection checks and tool-output verification. |
| `rag_sources`, `rag_materialization`, `rag_indexing` | Explicit common/project source bindings, exact-file managed-identity copies and verified private retrieval for `45-rag-agent`. |
| `monitoring` | Offline projection of recorded aggregates; no live polling, model inference or fabricated quality scores. |

Run `python -m agent_factory --help` from the parent directory.
See the [operator guide](../readme.md). None of these utilities turns arbitrary
PDFs, images or audio into supported training/retrieval inputs without an
explicit adapter. `load_selection` merges root storage defaults with per-target
selection profiles. `FactoryConfig` and exported `Target` carry
`use_common_datalake_storage`, `storage_resource_group` and `storage_container`;
`Target.storage_id` uses the selected storage RG, never the Foundry project RG
by assumption. `Target.resolve_container` rejects contradictory overrides.

The flag is strictly boolean: true selects configured common storage, false
configured project data storage. Only omission retains legacy `2001` discovery
and route-specific containers. All examples, including
[45-rag-agent](../45-rag-agent/readme.md), inherit explicit selection without
moving Foundry/Search/project identities or renaming physical lake paths.
