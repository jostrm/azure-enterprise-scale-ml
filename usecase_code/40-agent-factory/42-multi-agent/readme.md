# Multi-agent helpdesk: retrieve, review and synthesize

`aif-helpdesk-team` coordinates two separately persisted prompt agents.
It asks `aif-knowledge` for evidence, passes those findings to `aif-reviewer`,
and synthesizes the reviewed answer. Both participants retain their own Foundry
identity and definition; the coordinator does not create duplicate agents.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus, not one dataset per participant
- Data sources: No master-lake binding yet; `<project-data-storage>/agent-factory-adf/kaggle-rag-v1/knowledge/items.json` through `aif-knowledge`. See [source paths](../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Azure AI Projects SDK | Python | Microsoft Entra ID

## Execution

```text
Question -> knowledge participant -> evidence-aware reviewer -> synthesis -> answer
```

The sequence matters: review receives the actual draft, not just the original
question. Source URLs are retained after synthesis. In the expanded profile,
the knowledge participant can alternatively inspect live Azure inventory using
the private read-only MCP server. Inventory is not synthetic helpdesk policy.

Deploy the active prompt participants first, then select `--agent
aif-helpdesk-team` in the [operator workflow](../readme.md).
Public documentation approval is not propagated by this text-only coordinator;
call the documentation agent separately. There is no training pipeline and no
automatic Agent Map relationship rendering.
