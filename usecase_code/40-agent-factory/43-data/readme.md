# Prepare the synthetic helpdesk corpus for RAG

This folder prepares one public Kaggle dataset for private Foundry IQ retrieval.
Its CSV contains Markdown knowledge articles together with evaluation questions
and expected answers. Preparation separates those concerns so evaluation answers
cannot leak into the searchable knowledge corpus.

Both routes inherit the root
[`use_common_datalake_storage` selection](../readme.md#one-storage-selection-for-every-example):
`true` uses the configured common RG account/container (default `lake3`);
`false` uses configured project data storage (default `agent-factory`).
Account and RG must be explicit, not AML/Foundry artifact storage. ADF, Search
and the worker's UAMI stay project-scoped. Export a fresh `target.json` for the
worker; its optional `--container` must match the configured container. Selected
containers must already exist and be private; no account, container, role or
public-access change is implicit in selection.

## Use case summary

- Use case type: RAG with LLM (data preparation and retrieval setup, not model training)
- Data type: Tabular | Document (CSV input containing Markdown articles; JSON or Markdown knowledge output)
- Number of source data sets: 1; pinned Kaggle version 1 contains 10 unique knowledge items
- Data sources: No master-lake input in the current implementation; [Kaggle source](https://www.kaggle.com/datasets/dkhundley/sample-rag-knowledge-item-dataset) -> `<project-data-storage>/agent-factory-adf/kaggle-rag-v1/`. Master-lake context is explained below.
- Inference type: Batch (data preparation only) | Online (downstream agent inference)
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry / Foundry IQ | Microsoft Entra ID

## Two implemented ingestion routes

| Route | Processing and identity | Output |
| --- | --- | --- |
| Azure Data Factory | Managed-VNet copy/projection with the project UAMI; Search indexer uses Search's identity. | `<selected-container>/kaggle-rag-v1/knowledge/items.json` and separate evaluation JSON. |
| `worker.py` | Python on already-approved Azure compute with the project UAMI; no local-user fallback. | `<selected-container>/kaggle-rag-v1/documents/<hash>.md`, manifest and separate evaluation JSONL. |

ADF is the configured reference route. Both use a private semantic text index
and existing-index Foundry IQ source. The initial implementation does not compute
embeddings and does not need Azure Machine Learning or Azure Databricks.
See [ADF operations and integrity limits](datafactory-guide.txt) and
[the optional worker guide](guide.txt). Current project connections are
project-scoped (`isSharedToAll=false`); the worker guide's older `true` example
does not describe the implemented connection policy.

## Data sources and lake layout

When the flag is omitted, `<project-data-storage>` retains legacy project `2001`
discovery, not Foundry's reserved `1001` metadata storage. Legacy containers remain
`agent-factory-adf` for ADF and `agent-factory` for the worker. The following are
historical Spider project-001 reference paths, not defaults for other factories:

```text
Storage account: saprj001sdcbltsc2001dev
Container: agent-factory-adf

kaggle-rag-v1/raw/rag_sample_qas_from_kis.csv
kaggle-rag-v1/knowledge/items.json
kaggle-rag-v1/evaluation/samples.json
```

Only `knowledge/` is selected by the indexer. Do not point it at the container
root or at `raw/`: the raw CSV also contains evaluation answers.

The common lake already has a different RAG preparation example, observed on
2026-09-16:

```text
Storage account: spiderbltscesml001dev
Container: lake3

Master source:
mlops/v1/master/environments/dev/datasets/air-passengers/versions/bootstrap-v2-20260913-r2/

Derived RAG snapshot:
mlops/v1/projects/project001/environments/dev/usecases/air-passengers/rag/corpora/air-passengers/versions/bootstrap-v2-20260913-r2/
```

That snapshot has 12 derived text documents and 24 chunks. Its manifest says
`status=not_built`, `embeddings_computed=false`, and `acl_enforced=false`.
It is not the ten-item helpdesk corpus and is not wired to these agents.

An appropriate **proposed, not currently bound** helpdesk master path is:

```text
lake3/mlops/v1/master/environments/<env>/datasets/kaggle-helpdesk/versions/<version>/landing/
```

The existing `SharedLake` contract already provides project document and
`usecases/<usecase>/rag/corpora/...` areas. The separate
[45-rag-agent bridge](../45-rag-agent/readme.md) now explicitly chooses the
existing common-lake JSONL publication or this project JSON corpus, copies only
the pinned file with ADF managed identity, and builds a separately verified
Search/Foundry IQ retrieval path. Both `43-data` and `45-rag-agent` now inherit
the root storage profile when the flag is set.
The proposed helpdesk master path above is still not created or bound by either
example. No `mlops/v1` rename is required.

## Boundaries

This is text RAG, not PDF/OCR, image, audio or general 100-dataset ingestion.
Original article text and provenance are retained. Content hashes and the
evaluation split are checked; folder names and ACL fields are not substitutes
for actual storage and retrieval authorization.
