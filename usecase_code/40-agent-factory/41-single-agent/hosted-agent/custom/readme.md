# Custom Responses helpdesk agent

`aif-custom` is the minimal Python implementation of the grounded hosted-agent
pattern. The shared host asks `aif-knowledge` for evidence, then this worker calls
Foundry's Responses API directly. Use it to understand the boundary between
hosting, retrieval and model inference without another agent framework.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: No master-lake binding yet; `<project-data-storage>/agent-factory-adf/kaggle-rag-v1/knowledge/items.json` through `aif-knowledge` and Foundry IQ. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Python / OpenAI client library | Microsoft Entra ID

There is no model-training job, batch-inference scheduler or streaming-event
consumer in this sample. The common host handles bounded history, cancellation,
managed identity and source-link preservation. The optional expanded profile
also permits evidence from the private Azure inventory tool.

Deploy with `--agent aif-custom` using the
[shared hosted lifecycle](../readme.md#persistent-deployment-integration).
