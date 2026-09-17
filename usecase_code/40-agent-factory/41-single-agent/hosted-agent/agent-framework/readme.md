# Microsoft Agent Framework helpdesk agent

`aif-agent-framework` demonstrates a Foundry-hosted Python agent implemented
with Microsoft Agent Framework. The shared host first obtains cited evidence
from `aif-knowledge`; `main.py` then uses `Agent`, `Message` and
`OpenAIChatClient` to produce the final response through Foundry.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: No master-lake binding yet; `<project-data-storage>/agent-factory-adf/kaggle-rag-v1/knowledge/items.json`, accessed indirectly through `aif-knowledge`. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Microsoft Agent Framework | Microsoft Entra ID

The expanded read-only profile also lets the knowledge participant retrieve
live Azure resource inventory. It does not give this worker arbitrary Azure
commands or a public-model fallback. No model training, image processing or
event-stream processing is implemented.

Deploy through the [shared hosted lifecycle](../readme.md#persistent-deployment-integration),
using `--agent aif-agent-framework` and a configured Foundry model.
Keep [requirements.txt](requirements.txt) isolated per runtime.

Source: [Microsoft Agent Framework](https://github.com/microsoft/agent-framework).
