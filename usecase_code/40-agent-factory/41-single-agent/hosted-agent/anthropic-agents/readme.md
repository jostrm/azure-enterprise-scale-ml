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
- Data sources: No master-lake binding yet; `<project-data-storage>/agent-factory-adf/kaggle-rag-v1/knowledge/items.json` through `aif-knowledge`. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
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
