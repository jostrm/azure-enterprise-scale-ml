# RAG from the AI Factory shared lake or project storage

This is an explicit, runnable text-RAG example with two source choices: an
existing versioned corpus in the **AI Factory shared lake**, or the existing
Kaggle helpdesk publication in project data storage. Each binding gets its own
Foundry prompt agent, Search index, Foundry IQ knowledge base and project-managed-
identity connection. Selecting one source never silently selects or mixes another.

The physical `mlops/v1/master` and `mlops/v1/projects` paths are retained.
They already support multimodal data contracts; the name is not a restriction
to model training. This example adds the retrieval integration, not a lake rename.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-derived UTF-8 text in JSON/JSONL; no image/audio/PDF extraction)
- Number of source data sets: 1 per selected binding; 2 alternative example bindings, not 2 mixed datasets
- Data sources: Common master lineage `lake3/mlops/v1/master/environments/<env>/datasets/<dataset>/versions/<version>/`; its published project RAG `documents.jsonl`, or project `agent-factory-adf/kaggle-rag-v1/knowledge/items.json`. Exact reference paths appear below.
- Inference type: Batch (preparation/indexing) | Online (agent questions); no streaming-event pipeline
- Technology used in full chain: Azure Data Factory | Azure Storage / ADLS Gen2 / Blob Storage | Azure AI Search | Microsoft Foundry / Foundry IQ | Microsoft Entra ID

## Data flow and identities

```text
Explicit source binding + SHA-256 pin
  -> operator validates source bytes, schema, manifest and approved project audience
  -> existing ADF copies exactly that file using the project UAMI
  -> separate, source-versioned retrieval folder in project 2001 storage
  -> operator verifies copied bytes against the original SHA-256
  -> Search system identity privately indexes only that retrieval folder
  -> verify every indexed document's count, text hash and mapped provenance
  -> source-specific Foundry IQ knowledge base
  -> Foundry project identity retrieves evidence for the RAG agent
```

The operator's OAuth reads are integrity checks, not managed-identity
impersonation. ADF performs the actual data copy; Search performs actual indexing.
No storage keys, SAS tokens, VM identity attachment or public-storage fallback is
used. Existing Search Basic semantic-text retrieval is reused: no vectorizer,
embedding job, paid SKU upgrade, Azure ML or Databricks job is required.

Search's blob indexer selects a virtual directory, not a single exact filename.
Pointing it at a whole source snapshot could include `chunks/` or other
non-source records. The isolated retrieval copy avoids that ambiguity:

```text
Project storage 2001 / container agent-factory-rag
  sources/<full-binding-fingerprint>/knowledge/items.jsonl  # shared-lake source
  sources/<full-binding-fingerprint>/knowledge/items.json   # project source
```

Only one of these files exists for a particular binding. This is an operational
retrieval copy, not a new master dataset or a replacement `genaiops/v1` hierarchy.
Original master documents, manifests, images, annotations and existing agents
are not overwritten. A changed source hash creates a new binding/index namespace.

## Reference source paths

The consumer configuration is outside the replaceable templates:

```text
<consumer>\aifactory\agent-factory\config.json
<consumer>\aifactory\agent-factory\rag-sources.json
```

| Binding | Foundry agent | Documents | Origin |
| --- | --- | --- | --- |
| `common-air-passengers` | `aif-rag-common` | 12 | Deterministic annual text derived from the Kaggle AirPassengers table. |
| `project-helpdesk` | `aif-rag-project` | 10 | Synthetic IT helpdesk articles from the Kaggle knowledge-item dataset. |

Common storage: `spiderbltscesml001dev`, container `lake3`:

```text
Master lineage:
mlops/v1/master/environments/dev/datasets/air-passengers/versions/bootstrap-v2-20260913-r2/

Actual selected source:
mlops/v1/projects/project001/environments/dev/usecases/air-passengers/rag/corpora/air-passengers/versions/bootstrap-v2-20260913-r2/documents.jsonl

Pinned source manifest:
mlops/v1/projects/project001/environments/dev/usecases/air-passengers/rag/corpora/air-passengers/versions/bootstrap-v2-20260913-r2/_SUCCESS.json
```

Project storage: `saprj001sdcbltsc2001dev`, container `agent-factory-adf`:

```text
kaggle-rag-v1/knowledge/items.json
```

The shared snapshot's original manifest describes its offline preparation:
`index.status=not_built`, `embeddings_computed=false`, `acl_enforced=false`.
This example does not rewrite that immutable manifest to claim broader
activation. Its separate deployment journal records the new index and agent.
Project helpdesk raw CSV and evaluation answers remain excluded.

## Configure a binding

Use [sources.example.json](sources.example.json) as a schema example; replace its
placeholder IDs, storage names and hashes with the actual approved source.
The Spider consumer has populated bindings for the paths above.

Every source explicitly specifies its account resource ID, container, blob path,
format, dataset/version, source SHA-256 and approved audience. Shared sources
also pin their sibling `_SUCCESS.json` and validate its project/environment,
publication state, document count and file hash.

Only these two adapters are implemented:

| Location | Format | Required input |
| --- | --- | --- |
| `common` | `shared-lake-jsonl` | Project-scoped `mlops/v1/.../rag/corpora/.../documents.jsonl` with the pinned publication manifest. |
| `project` | `knowledge-json-array` | `.../knowledge/items.json` in the explicitly selected project `2001` account. |

This is not an arbitrary folder crawler. To use master PDFs, images or another
document format, first implement and validate the extraction/publication adapter;
do not relabel binary files as one of these formats or bypass source validation.

## Run the example

Run from `40-agent-factory`, using the existing operator Python environment.
Keep the VPN connected for private Storage/Search/Foundry access.

```powershell
$config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$sources = "C:\path\to\consumer\aifactory\agent-factory\rag-sources.json"
$binding = "project-helpdesk" # Or common-air-passengers; always choose explicitly.
$selection = @("--config", $config, "--sources", $sources, "--source", $binding)

python .\45-rag-agent\main.py plan @selection
python .\45-rag-agent\main.py configure @selection --apply
```

For common-lake access, `configure --apply --grant-read` explicitly grants the
existing ADF project UAMI a **conditional Storage Blob Data Reader** role:
content reads are limited to the selected document blob, and listing is limited
to its exact filename or version-directory prefix. It does not grant access to
the whole lake. Existing broader assignments, if any, are not narrowed by adding
this role; review effective access separately. No source ACLs are edited.

If setup reports a pending ADF Blob private endpoint, approve only its reported
connection/requester pair:

```powershell
python .\45-rag-agent\main.py approve-link @selection `
  --connection-id "<reported-storage-connection-resource-id>" `
  --private-endpoint-id "<reported-ADF-requester-resource-id>" --apply
python .\45-rag-agent\main.py configure @selection --apply
```

Then materialize once, poll that recorded run, index, verify and deploy:

```powershell
python .\45-rag-agent\main.py materialize @selection --apply
python .\45-rag-agent\main.py poll-materialization @selection
python .\45-rag-agent\main.py start @selection --apply
python .\45-rag-agent\main.py poll @selection
python .\45-rag-agent\main.py deploy @selection --apply
python .\45-rag-agent\main.py ask @selection `
  --input "What is the documented PIN reset limit within 24 hours?"
```

For `common-air-passengers`, ask:
`What was the airline passenger count in January 1949, in thousands?`

If multiple Data Factories exist in the selected group, supply `--data-factory`.
Mutation commands require `--apply`. Polling resumes saved work and never starts
a second ADF run. Valid completed materializations and successful indexer runs
are reused. After correcting a terminal failure, explicitly use
`materialize --apply --retry-failed` or `start --apply --retry-failed`; active runs
are never restarted. Invalid staged bytes require explicit retry, not acceptance.

State is stored under:

```text
<config-directory>\.agent-factory\<account>\<project>\rag\<source-key>\<binding-fingerprint>\
  source-binding.json
  configuration.json
  materialization.json
  indexing.json
  deployment.json
```

The `ask` command revalidates the source, staged bytes, indexed corpus and live
knowledge-base/source/connection binding before invoking the recorded agent
version. An answer counts as grounded only after a successful source-specific
`knowledge_base_retrieve` call, not merely because the model says it used a source.

## Access, freshness and supported scope

This initial example serves **project-wide approved corpora**. Shared documents
must all have the exact `acl: ["project001"]` audience for project 001 (or the
selected project equivalent). Empty, mixed or per-user ACLs and tombstones are
rejected. An ACL string in JSON does not enforce access; no per-user security
trimming is claimed. Only publish sources that may be read by the target
Search/Foundry project's authorized readers.

Sources are bounded to 4 MiB and 1,000 text documents; these are validation
limits, not a claim of 1,000 input datasets. Both source and destination are
hash-pinned. Indexes have no automatic refresh schedule. A new corpus version
requires a new binding and explicit verification/promotion; index deletion,
retention policies and automatic tombstone processing are not implemented.
The CLI checks protect this workflow, not every possible external caller of a
Foundry endpoint or administrator editing Search directly.

ADF checks transfer consistency and source/destination size. The operator
independently computes SHA-256 over the resulting bytes; ADF is not described
as computing SHA-256. Evaluations remain outside retrieval. All private links
and managed identities must work independently of the operator's login.

## Implementation and offline tests

The example reuses [Foundry IQ configuration](../agent_factory/knowledge.py) and
[prompt deployment](../agent_factory/prompt.py). New helpers are
[source validation](../agent_factory/rag_sources.py),
[ADF materialization](../agent_factory/rag_materialization.py), and
[private indexing](../agent_factory/rag_indexing.py).

```powershell
python -m unittest tests.test_rag_sources tests.test_rag_materialization `
  tests.test_rag_indexing tests.test_rag_cli
```

These tests use synthetic data and mocks. They do not download Kaggle data,
change lake ACLs, create Azure resources or substitute for live retrieval checks.
