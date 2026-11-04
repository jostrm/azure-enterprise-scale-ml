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
- Data sources: No master-lake input in the current implementation; [Kaggle source](https://www.kaggle.com/datasets/dkhundley/sample-rag-knowledge-item-dataset) -> `<selected-data-storage>/<selected-container>/<ADF-prefix>/`. Historical project-storage and master-lake context is explained below.
- Inference type: Batch (data preparation only) | Online (downstream agent inference)
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry / Foundry IQ | Microsoft Entra ID

## Two implemented ingestion routes

| Route | Processing and identity | Output |
| --- | --- | --- |
| Azure Data Factory | Managed-VNet copy/projection with the project UAMI; Search indexer uses Search's identity. | `<selected-container>/<ADF-prefix>/knowledge/items.json` and separate evaluation JSON. |
| `worker.py` | Python on already-approved Azure compute with the project UAMI; no local-user fallback. | `<selected-container>/kaggle-rag-v1/documents/<hash>.md`, manifest and separate evaluation JSONL. |

ADF is the configured reference route. Both use a private semantic text index
and existing-index Foundry IQ source. The initial implementation does not compute
embeddings and does not need Azure Machine Learning or Azure Databricks.
See [ADF operations and integrity limits](datafactory-guide.txt) and
[the optional worker guide](guide.txt). Current project connections are
project-scoped (`isSharedToAll=false`); the worker guide's older `true` example
does not describe the implemented connection policy.

## Prerequisites

- Complete the root [prerequisites](../readme.md#prerequisites) with a reviewed
  consumer `aifactory\agent-factory\config.json`, its referenced variables file,
  and one explicit target (the examples use `project001-dev`). Keep
  `ingestion.mode` set to `datafactory` for the normal operator route. Do not
  overwrite existing consumer configuration with `config.example.json`.
- Use cached Azure CLI OAuth in the configured tenant and subscription first;
  use browser-based login only if that tenant's cached OAuth is unavailable.
  Keep the VPN connected and private DNS/routing working for Storage, Search and
  Foundry. Public network access and anonymous Blob access must remain disabled.
- The existing project deployment must already provide ADF with the selected
  project UAMI, `ls_cred_project_uami`, and `AutoResolveIntegrationRuntime` in
  managed VNet `default`. Legacy selection also requires `ls_storage_lake`.
  The ADF managed IR needs approved public HTTPS egress to Kaggle and its download
  redirect; this does not make Azure data endpoints public.
- The project UAMI needs Storage Blob Data Contributor on the selected
  container. Search needs its existing system-assigned identity and Storage
  Blob Data Reader on the selected storage. Foundry's project identity needs
  Search Index Data Reader and its own private runtime path to Search.
  These are different identities; operator OAuth does not impersonate them.
- The operator needs ARM discovery, ADF/artifact configuration and private-link
  approval permissions, Search Service Contributor plus Search Index Data Reader,
  and permission to create the Foundry project connection. Required role grants
  must be reviewed separately; these commands do not grant them.
- Search must already support semantic ranking with available quota. This path
  uses a private, skillset-free indexer on Basic or higher, not managed `azureBlob`
  knowledge-source ingestion. Do not upgrade the SKU or enable public access to
  bypass a failure.

With an explicit storage profile, its private account and container must already
exist. ADF uses `kaggle-rag-v1/adf/<project-id-hash>` as its prefix; use the returned
`container` and `prefix`, not the historical path below. The worker still uses
`kaggle-rag-v1` by default. The linked text guides' `2001` and fixed-container
examples describe legacy selection; the current explicit profile takes precedence.

## How to set up the Python environment

Run these PowerShell commands from **`40-agent-factory`**, not from `43-data`.
Choose the central checkout below, or the consumer's
`C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` directory
([folder layout](../readme.md#folder-layout)).

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
$Consumer = "C:\path\to\consumer" # Replace with your consumer checkout.
$Config = Join-Path $Consumer "aifactory\agent-factory\config.json"
$Target = "project001-dev" # Must be an existing key in config.json.
if (-not (Test-Path $Config)) { throw "Complete the reviewed consumer configuration first." }
if (-not (Test-Path ".\.venv\Scripts\python.exe")) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

Reuse this operator environment if already prepared; activation is unnecessary.
The root [Python setup](../readme.md#how-to-set-up-the-python-environment)
explains the shared dependencies. ADF does **not** require the worker dependencies
or a project UAMI on the operator machine.

## How to run the code

### Normal route: Azure Data Factory

Run each numbered step only after checking the preceding result. These are live
Azure operations, not evidence that ingestion has already succeeded.

1. **Read-only selection and access checks.** `plan` reads local configuration;
   `discover` and `preflight` read Azure. Use cached OAuth first; sign in through
   the browser only if needed.

   ```powershell
   $Plan = .\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target | ConvertFrom-Json
   if ($LASTEXITCODE -ne 0) { throw "Resolve the configuration error before continuing." }
   $Plan.target
   # Only if cached OAuth for this tenant is unavailable:
   # az login --tenant $Plan.target.tenant_id
   # Read-only identity inspection; this alone does not prove token validity.
   az account show --subscription $Plan.target.subscription_id --query "{subscription:id,tenant:tenantId}" --output json
   .\.venv\Scripts\python.exe -m agent_factory discover --config $Config --target $Target
   .\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
   ```

   Confirm the intended account/container, project UAMI, Search and Foundry target.
   Preflight should report private/reachable endpoints and `foundry_access: true`.
   It does not prove ADF, Search or Foundry runtime identity access.

2. **Azure mutation: configure owned artifacts, without starting ingestion.**
   If multiple factories exist, add `--data-factory "<actual-factory-name>"` to
   every configure/start/poll command.

   ```powershell
   .\.venv\Scripts\python.exe -m agent_factory configure-datafactory --config $Config --target $Target --apply
   ```

   Expected status is `configured` or `awaiting-private-endpoint-approval`.
   Review `private_endpoints`, `prerequisites`, `search_identity_principal_id`,
   `container` and `prefix`. This can create ADF definitions, task-owned Blob
   links and Search metadata; legacy mode can also create the private owned
   container. It does not create a factory, grant roles or attach identities.

3. **Conditional Azure mutation: approve only an inspected pending link.**
   For each reported ADF/Search link, obtain its storage
   `privateEndpointConnections` resource ID and exact
   `properties.privateEndpoint.id` requester. Do not substitute an unrelated
   managed-link ID or approve all pending requests.

   ```powershell
   .\.venv\Scripts\python.exe -m agent_factory approve-datafactory-link --config $Config --target $Target `
     --connection-id "<inspected-storage-privateEndpointConnections-resource-id>" `
     --private-endpoint-id "<that-connection-requester-private-endpoint-resource-id>" --apply
   .\.venv\Scripts\python.exe -m agent_factory configure-datafactory --config $Config --target $Target --apply
   ```

   Both ADF Blob and Search Blob links must be Approved/Succeeded and
   configuration must report `configured`. Resolve the separately approved RBAC
   prerequisites before continuing. Skip approval when the links are already ready.

4. **Azure mutation: start once, then poll that saved run.**
   Skip `start-datafactory` if a run is already recorded; resume it with
   `poll-datafactory`. If ingestion already completed successfully, skip both
   and use step 5.

   ```powershell
   .\.venv\Scripts\python.exe -m agent_factory start-datafactory --config $Config --target $Target --apply
   .\.venv\Scripts\python.exe -m agent_factory poll-datafactory --config $Config --target $Target --timeout-seconds 3600 --apply
   ```

   Start returns `status: running` and `run_id`. State is saved in
   `<config-directory>\.agent-factory\<account>\<project>\ingestion.json`.
   After timeout, rerun only polling (optionally `--run-id "<recorded-run-id>"`).
   Unlike the RAG bridge's polling, this poll command **requires `--apply`**:
   after ADF succeeds it creates/runs the private Search indexer. It never starts
   another ADF copy, but polling an already completed ingestion can rerun indexing.
   Success requires `status: ingested`, `document_count: 10` and
   `corpus_sha256_verified: true`. Inspect secured ADF monitoring after a terminal
   failure before authorizing a new start.

5. **Verify, then configure retrieval only if not already configured.**

   ```powershell
   # Read-only corpus/semantic verification; safe for an already ingested corpus.
   .\.venv\Scripts\python.exe -m agent_factory verify-datafactory --config $Config --target $Target
   # Azure mutation: create/validate the existing-index Foundry IQ resources.
   .\.venv\Scripts\python.exe -m agent_factory configure-knowledge --config $Config --target $Target --apply
   ```

   Verification must report ten documents and verified corpus hashes.
   `configure-knowledge` requires the verified ADF ingestion journal and should
   return `retrieval_verified: true`, with a project-scoped connection
   (`isSharedToAll=false`). It is an operator retrieval check, not proof of a
   successful agent-side managed-identity call. Continue with the root
   [run sequence](../readme.md#how-to-run-the-code) for agent deployment/invocation.

Only `knowledge/` enters retrieval. Raw CSV and evaluation answers remain in
separate paths. ADF checks pinned byte count and Content-MD5, **not raw SHA-256**;
the operator independently hashes indexed content against the bundled reference.

### Optional alternative: approved Azure worker host

This is **instead of ADF ingestion**, not another prerequisite. Never attach the
project's broad UAMI to a shared admin machine to run this example. The Azure host
must already be approved and assigned that exact UAMI, have private Blob/Search
DNS and routing, approved Kaggle egress, and UAMI permissions for Blob writes,
Search Service Contributor and Search Index Data Contributor. Local `az login`
cannot supply or impersonate this identity; missing managed identity is a hard error.

1. On the operator machine, export a fresh target using the reviewed selection:

   ```powershell
   $WorkerTarget = Join-Path (Split-Path $Config) "worker-target.json"
   .\.venv\Scripts\python.exe -m agent_factory discover --config $Config --target $Target --output $WorkerTarget
   ```

   This is a local JSON write plus Azure discovery, not ingestion. Transfer this
   IDs-only file through the approved host workflow, together with `43-data`
   and `agent_factory`; do not transfer login caches, tokens or secrets.

2. **On that approved Windows Azure host**, from its `40-agent-factory` checkout,
   use a separate worker environment, not the operator environment:

   ```powershell
   if (-not (Test-Path ".\.venv-worker\Scripts\python.exe")) { py -3.13 -m venv .venv-worker }
   .\.venv-worker\Scripts\python.exe -m pip install -r .\43-data\requirements.txt
   ```

3. **Azure mutation: explicitly authorize this worker execution.** Unlike the
   operator CLI, `worker.py` has no `--apply` or dry-run option; invoking it writes
   Blob artifacts and Search documents immediately. Run only after approval:

   ```powershell
   .\.venv-worker\Scripts\python.exe .\43-data\worker.py `
     --target "C:\path\to\approved\worker-target.json" --index aif-kaggle-rag-v1
   ```

   Omit `--container` to inherit the exported profile; an override must match it.
   Expected output includes `status: ingested`, ten documents, ten evaluations,
   `manifest_url` and `embeddings_required: false`. Only article text is pushed
   into Search; the manifest and evaluation JSONL are not knowledge documents.
   After a partial failure, inspect the error before retrying the same pinned
   inputs; never rerun a successful ingestion merely to check it. Worker index
   `aif-kaggle-rag-v1` is distinct from ADF's `aif-kaggle-rag-adf-v1`. Do not use
   an ADF ingestion journal to configure worker retrieval; follow the
   [worker guide](guide.txt) with that explicit index and current project-scoped
   connection policy.

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
