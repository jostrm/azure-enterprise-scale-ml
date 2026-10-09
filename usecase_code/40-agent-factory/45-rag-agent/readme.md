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
  -> separate, source-versioned retrieval folder in the selected storage profile
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
Selected account / selected private container
  sources/<full-binding-fingerprint>/knowledge/items.jsonl  # shared-lake-jsonl format
  sources/<full-binding-fingerprint>/knowledge/items.json   # knowledge-json-array format
```

Only one of these files exists for a particular binding. This is an operational
retrieval copy, not a new master dataset or a replacement `genaiops/v1` hierarchy.
Original master documents, manifests, images, annotations and existing agents
are not overwritten. A changed source hash creates a new binding/index namespace.

### Current storage-profile behavior

With root `use_common_datalake_storage` explicitly set, **both the source and
retrieval copy use that profile's account and container**:

- `true`: configured common resource-group storage (default container `lake3`);
- `false`: configured project data storage (default container `agent-factory`).

`location`, `storage_account_resource_id` and `container` are inherited by each
binding. If supplied explicitly, they must match the selected profile; there is
no fallback to a different account. Either implemented text format can be used
in either explicit profile, subject to its path, schema, audience and hash checks.
The selected private container must already exist. ADF, Search and Foundry
identities remain project-scoped; profile selection grants no roles.

Only **legacy configuration with the flag omitted** couples `common` to
`shared-lake-jsonl` and `project` to `knowledge-json-array`, and stages into
project `2001` storage/container `agent-factory-rag`. That legacy path can create
its owned private destination container. Older project-materialization notes
and the reference paths below do not override the current explicit profile.
In all modes the source blob is read-only; materialization writes a separate
`sources/<binding-fingerprint>/knowledge/` prefix, never the original source.
See the root [storage selection](../readme.md#one-storage-selection-for-every-example).

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

These are historical populated Spider bindings, not resources created by copying
the example file. The template's shared binding key is `common-documents`, not
`common-air-passengers`; always inspect and select the actual key in your file.

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

For current `43-data` ADF ingestion with an explicit storage profile, use its
reported account/container and
`kaggle-rag-v1/adf/<project-id-hash>/knowledge/items.json`, not the legacy path
above or the template's placeholder path. Preserve the publication's actual
provenance fields. The optional worker's Markdown output is **not** this JSON-array
publication and is not accepted by these adapters.

## Prerequisites

- Complete the root [prerequisites](../readme.md#prerequisites) for the reviewed
  consumer configuration, one explicit target (for example `project001-dev`),
  deployed Foundry model and private Search service. Do not overwrite an
  existing consumer config or source-binding file.
- Select an **already published and approved** text source, not a raw dataset.
  For helpdesk, reuse successful [43-data ADF ingestion](../43-data/readme.md);
  do not rerun it merely to use this bridge. For shared JSONL, obtain its exact
  `documents.jsonl` and sibling `_SUCCESS.json` pins and project-wide approval.
- Use cached Azure CLI OAuth matching the configured tenant/subscription first;
  use browser-based login only if that tenant's cached OAuth is unavailable.
  The operator needs ARM discovery, read access to source/manifest/staged blobs,
  ADF artifact configuration/run permissions, Search configuration/query access,
  and Foundry connection/agent permissions. Common-lake conditional-role grants
  and private-link approvals need separately approved administrative authority.
- Keep VPN/private DNS and routing to source/destination Blob, Search and Foundry
  available. Storage and Search public access must remain disabled. Common source
  storage must already be private HNS storage without anonymous access.
- ADF must already use the project UAMI through `ls_cred_project_uami` and managed
  VNet `AutoResolveIntegrationRuntime`. The UAMI needs source read access and
  Storage Blob Data Contributor on the selected destination container; the
  workflow grants no write roles. Search's existing system identity needs
  Storage Blob Data Reader there. Foundry's project identity separately needs
  Search Index Data Reader and a private runtime path to Search.
- The existing Search Blob shared private link to the **selected destination
  account** must be Approved/Succeeded. Existing ADF Blob links must reach both
  source and destination. This bridge can create its task-owned common-source
  ADF Blob endpoint, but does not repair missing project ADF or Search links.
  Have the approved infrastructure workflow resolve those blockers; do not
  rerun helpdesk ingestion to obtain networking.
- Existing semantic ranking and quota are required. No paid SKU/semantic-plan
  upgrade, embeddings, vectorizer or per-user security trimming is implied.

## Configure a binding

Use [sources.example.json](sources.example.json) as a schema example; replace its
placeholder publication paths, metadata and hashes with the actual approved
source, inheriting the account/container from the reviewed storage profile.
The populated Spider bindings above are historical references, not verified
current consumer state.

Every source explicitly specifies its blob path, format, dataset/version, source
SHA-256 and approved audience. The current example inherits account/location/
container from the reviewed root storage profile; legacy configurations must
supply those three fields explicitly. Each agent name must be unique across the
source file. JSONL sources also pin their sibling `_SUCCESS.json` and validate its
project/environment, publication state, document count and file hash.

Only these two adapters are implemented:

| Legacy location (explicit profiles may use either) | Format | Required input |
| --- | --- | --- |
| `common` | `shared-lake-jsonl` | Project-scoped `mlops/v1/.../rag/corpora/.../documents.jsonl` with the pinned publication manifest. |
| `project` | `knowledge-json-array` | `.../knowledge/items.json` in the selected account/container; legacy project mode requires `2001`. |

This is not an arbitrary folder crawler. To use master PDFs, images or another
document format, first implement and validate the extraction/publication adapter;
do not relabel binary files as one of these formats or bypass source validation.

## How to set up the Python environment

Run PowerShell from **`40-agent-factory`**, not from `45-rag-agent`. The consumer
alternative is `C:\path\to\consumer\aifactory-usecase-code\40-agent-factory`
([folder layout](../readme.md#folder-layout)).

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
$Consumer = "C:\path\to\consumer" # Replace with your consumer checkout.
$Config = Join-Path $Consumer "aifactory\agent-factory\config.json"
$Sources = Join-Path $Consumer "aifactory\agent-factory\rag-sources.json"
$Target = "project001-dev" # An existing target key in config.json.
if (-not (Test-Path $Config)) { throw "Complete the reviewed consumer configuration first." }
if (-not (Test-Path ".\.venv\Scripts\python.exe")) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
# Initialize only a missing source file; never overwrite reviewed bindings.
if (-not (Test-Path $Sources)) { Copy-Item .\45-rag-agent\sources.example.json $Sources }
```

Reuse the root Python 3.13 operator environment when it already exists
([Python setup](../readme.md#how-to-set-up-the-python-environment)); this folder has
no separate requirements. The example source file is a schema template with
placeholder hashes, **not** runnable sample data.

## How to run the code

Execute the following numbered sequence one step at a time. Stop on failures;
the expected outputs below are acceptance checks, not claims of a live deployment.

1. **Complete and select the approved binding locally.** Review `$Sources` using
   the contract above: replace placeholder paths, dataset/version, provenance,
   audience and hashes with the actual approved publication. SHA-256 values must
   be exact lowercase 64-character digests of the **published bytes**, not the
   original CSV, a reformatted export or a filename. For an approved local
   byte-for-byte copy, compute a pin with:

   ```powershell
   (Get-FileHash -Algorithm SHA256 -LiteralPath "C:\path\to\approved\items.json").Hash.ToLowerInvariant()
   # For shared-lake-jsonl, use documents.jsonl instead and also pin its manifest:
   # (Get-FileHash -Algorithm SHA256 -LiteralPath "C:\path\to\approved\_SUCCESS.json").Hash.ToLowerInvariant()
   ```

   Record the reviewed pins in the binding; do not replace an approved hash just
   to silence an integrity failure. `plan` later downloads the selected blobs
   using private operator OAuth and checks those pins independently.

   ```powershell
   $SourceConfig = Get-Content -Raw $Sources | ConvertFrom-Json
   $SourceConfig.sources.PSObject.Properties.Name
   $Binding = "project-helpdesk" # Choose one listed key; never an implicit default.
   $Selection = @("--config", $Config, "--target", $Target, "--sources", $Sources, "--source", $Binding)
   # If discovery would find multiple ADFs, explicitly select the reviewed one:
   # $Selection += @("--data-factory", "<actual-factory-name>")
   ```

   For the shared template select `common-documents` after supplying an actual
   publication. Use `common-air-passengers` only when that populated binding
   actually exists. A binding must agree with the selected root profile; do not
   change the storage profile simply to make a historical example pass.

2. **Read-only target/source/network plan, with cached tenant-bound OAuth.**
   Use browser-based login only if the selected tenant's cached OAuth is unavailable.

   ```powershell
   $Plan = .\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target | ConvertFrom-Json
   if ($LASTEXITCODE -ne 0) { throw "Resolve the configuration error before continuing." }
   $Plan.target
   # Only if cached OAuth for this tenant is unavailable:
   # az login --tenant $Plan.target.tenant_id
   # Read-only identity inspection; this alone does not prove token validity.
   az account show --subscription $Plan.target.subscription_id --query "{subscription:id,tenant:tenantId}" --output json
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py plan @Selection
   ```

   Root `plan` is local; the RAG plan is **live read-only**, not offline. It
   validates source bytes/schema/manifest and reads Azure prerequisites without
   creating resources. Expect `mutations: false`, `source_writes: false`, the
   exact `source_url`, source document count, agent name, binding fingerprint,
   materialization destination and prerequisite lists. Inspect every account,
   container and prefix. Ten helpdesk or twelve reference AirPassengers documents
   are expected only for those particular publications.

3. **Azure mutation: configure the owned ADF materialization definitions.**

   ```powershell
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py configure @Selection --apply
   ```

   This does not start a copy or indexer. Expect `configured`, or `needs-setup`
   with explicit prerequisites. For common-lake sources, the implementation
   requires its exact conditional reader assignment even if broader access
   already exists. If separately authorized and missing, use this command
   **instead of** the configure command above:

   ```powershell
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py configure @Selection --apply --grant-read
   ```

   `--grant-read` explicitly grants the existing ADF project UAMI conditional
   **Storage Blob Data Reader**: content reads are limited to the selected
   document blob; listing is limited to its exact filename or version-directory
   prefix. It does not grant whole-lake reads, destination writes or manifest
   reads to ADF. The operator reads the manifest. Existing broader grants are
   not narrowed by adding this role; review effective access separately.
   No source ACLs are edited.

4. **Conditional Azure mutation: approve only a reported pending ADF link.**

   ```powershell
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py approve-link @Selection `
     --connection-id "<reported-storage-connection-resource-id>" `
     --private-endpoint-id "<reported-ADF-requester-resource-id>" --apply
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py configure @Selection --apply
   ```

   Skip this step when no approval is pending. Review the exact connection/
   requester pair in `pending_storage_connections`; never blanket-approve.
   Resolve missing project ADF/Search links or role grants through their approved
   owner workflow. Proceed only with `configured` and no unmet prerequisites;
   the read-only `plan` must also report ready Search networking.

5. **Azure mutation: materialize once, then poll and verify that saved run.**
   Skip `materialize` if its run is already recorded; resume polling it.
   Skip both commands if that binding already has a verified successful copy.

   ```powershell
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py materialize @Selection --apply
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py poll-materialization @Selection --timeout-seconds 3600
   ```

   Start returns `status: running` and a journaled `run_id`. Polling starts no
   new ADF run; after timeout, repeat only polling. Success requires
   `status: succeeded`, `content_verified: true` and a destination SHA-256 equal
   to the approved source pin, not merely ADF reporting `Succeeded`.

6. **Azure mutation: start private indexing once; then verify every document.**
   For active indexing, run only `poll`; for already successful indexing, use
   `verify` instead of starting again.

   ```powershell
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py start @Selection --apply
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py poll @Selection --timeout-seconds 3600
   # Read-only check for later use without restarting completed work:
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py verify @Selection
   ```

   `start` creates/reuses the source-specific Search artifacts only after staged
   hash verification. `poll` requires successful execution without warnings or
   failed items, then verifies count, text hashes and mapped provenance.
   Expect `status: success`, `content_verified: true` and the planned
   `document_count`; `verify` independently rechecks content without an execution
   status field.

7. **Azure mutation: deploy the bound prompt agent; then ask a grounded question.**
   Skip deployment if the exact recorded agent version and binding are current.

   ```powershell
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py deploy @Selection --apply
   .\.venv\Scripts\python.exe .\45-rag-agent\main.py ask @Selection `
     --input "What is the documented PIN reset limit within 24 hours?"
   ```

   Deploy creates/verifies the source-specific Foundry IQ source, knowledge base,
   project-MI connection and agent version; expect `retrieval_verified: true`.
   `ask` performs billable inference (not infrastructure provisioning), requires
   the existing deployment journal, and returns `text` plus a successful
   source-specific `knowledge_base_retrieve` call in `tool_calls`. For the actual
   AirPassengers publication, use
   `What was the airline passenger count in January 1949, in thousands?`
   instead; for another corpus, ask a question it can support.

### Safe resume and state

Mutation commands require `--apply`; RAG `poll-materialization`, `poll` and `verify`
do not. Polling never starts another copy/indexer. Valid completed
materializations and successful indexer runs are reused by the start commands,
but use the read-only checks for routine verification, not repeated starts.
After repairing a terminal failure, explicitly authorize
`materialize --apply --retry-failed` or `start --apply --retry-failed`;
active runs are never restarted. Invalid staged bytes require explicit retry,
not acceptance or a changed hash pin.

If ADF reports `Succeeded` but copied bytes fail integrity verification, after
investigating and repairing the cause use:

```powershell
.\.venv\Scripts\python.exe .\45-rag-agent\main.py materialize @Selection --apply --retry-failed
.\.venv\Scripts\python.exe .\45-rag-agent\main.py poll-materialization @Selection
```

The source must still match its approved hash. The retry rechecks prerequisites,
starts one replacement copy and saves the new run ID with
`retry_reason=destination-verification-failed`. A valid completed copy is reused
even with this flag. Authentication/connectivity errors do not trigger a
replacement, and a failed attempt to start one does not replace the previous
journal.

State is stored under:

```text
<config-directory>\.agent-factory\<account>\<project>\rag\<source-key>\<binding-fingerprint>\
  source-binding.json
  configuration.json
  materialization.json
  indexing.json
  deployment.json
```

Preserve these journals beside the consumer config across sessions. Do not delete
them to bypass failed verification or reuse another binding's run ID. A new hash,
source path or profile is a new reviewed binding, not a resume of the old one.

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
.\.venv\Scripts\python.exe -m unittest tests.test_rag_sources tests.test_rag_materialization `
  tests.test_rag_indexing tests.test_rag_cli
```

These tests use synthetic data and mocks. They do not download Kaggle data,
change lake ACLs, create Azure resources or substitute for live retrieval checks.
