# GitHub Copilot SDK helpdesk agent

`aif-copilot-sdk` uses the GitHub Copilot SDK as its agent runtime, with a
bring-your-own-model Responses provider pointed at Microsoft Foundry. Grounding
is performed by the shared host through `aif-knowledge`, before Copilot receives
the conversation and evidence.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: No master-lake binding yet; `<project-data-storage>/agent-factory-adf/kaggle-rag-v1/knowledge/items.json` through the persisted knowledge agent. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | GitHub Copilot SDK | Microsoft Entra ID

This is not a desktop coding assistant. Built-in tools, shell/file permissions,
host Git operations, MCP discovery and GitHub auto-login are disabled. Optional
Azure inventory comes from the verified private knowledge-participant path,
not a general-purpose command executor.

The native SDK runtime must be available or its supported release download must
be reachable. Scratch state is isolated in a writable temporary directory and
cleaned up after each request; the application directory may be read-only.

Deploy with `--agent aif-copilot-sdk` using the
[shared hosted lifecycle](../readme.md#persistent-deployment-integration).
Source: [GitHub Copilot SDK](https://github.com/github/copilot-sdk).
