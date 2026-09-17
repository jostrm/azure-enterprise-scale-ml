# LangGraph helpdesk agent

`aif-langgraph` runs a small compiled `StateGraph`: a model node receives the
conversation and the evidence already retrieved by the shared host, calls the
Foundry Responses API, and returns the answer. It demonstrates graph-based
execution without pretending that a single model node is a multi-agent team.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: No master-lake binding yet; `<project-data-storage>/agent-factory-adf/kaggle-rag-v1/knowledge/items.json` through `aif-knowledge` and Foundry IQ. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | LangGraph | Microsoft Entra ID

Foundry conversation history is authoritative; this sample does not use a
process-global LangGraph checkpointer. The expanded profile adds read-only Azure
inventory through the same knowledge participant, not unrestricted tool access.
It does not train a model or process streaming events.

Deploy with `--agent aif-langgraph` using the
[shared hosted lifecycle](../readme.md#persistent-deployment-integration).
Source: [LangGraph](https://github.com/langchain-ai/langgraph).
