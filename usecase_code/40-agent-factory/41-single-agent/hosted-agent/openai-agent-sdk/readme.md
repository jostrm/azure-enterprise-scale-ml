# OpenAI Agents SDK helpdesk agent

`aif-openai-sdk` uses the OpenAI Agents SDK's `Agent`, `OpenAIResponsesModel`
and `Runner`, but model inference goes to the explicitly configured Microsoft
Foundry endpoint. The shared host supplies evidence from `aif-knowledge` before
the SDK synthesizes the answer.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: No master-lake binding yet; `<project-data-storage>/agent-factory-adf/kaggle-rag-v1/knowledge/items.json` through the persisted knowledge agent. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | OpenAI Agents SDK | Microsoft Entra ID

Public OpenAI tracing is disabled, and the model client uses Entra credentials
for Foundry rather than a public OpenAI API key. Runner turns are bounded.
The optional expanded profile accepts private Azure inventory from the
knowledge participant; it does not automatically install arbitrary SDK tools.

Deploy with `--agent aif-openai-sdk` using the
[shared hosted lifecycle](../readme.md#persistent-deployment-integration).
Source: [OpenAI Agents SDK](https://github.com/openai/openai-agents-python).
