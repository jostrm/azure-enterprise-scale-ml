# DataOps: ingest, validate and orchestrate model data

DataOps supplies reproducible data and explicit job inputs to
[MLOps](37-mlops.md). The Machine learning model factory uses Kaggle sample sources,
the [versioned project/use-case lake](34-datalake-onboard-data.md), Azure Data Factory
(ADF), Azure ML v2 jobs and Azure Databricks notebooks.

Use the implemented
[Azure Data Factory templates](../../../copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/readme.md).
They are opt-in code-first artifacts, not evidence that pipelines, permissions or
triggers have already been deployed.

## Delta interoperability and shareback

**New ESML v2 silver/gold default to Delta; bronze defaults to unchanged source
format.** A single dataset still flows through silver and a distinct gold
representation. Gold stays beneath project/use-case paths; model inputs are
gold-derived splits. The optional fast path without a bronze node must be chosen
explicitly; it does not skip gold. Reusing already validated silver can bypass
raw refinement and feed the gold merge directly.

Use `table_format: "delta"` (default) or explicitly `"parquet"`. Select
`aml_table_format` independently when an AutoML environment needs the Parquet
compatibility export. New example settings include both. Built-in Delta writes
target a conservative reader-1/writer-2 profile: no deletion vectors, column
mapping, V2 checkpoints, timestamp-NTZ, or automatic advanced table features.
This is an interoperability policy, not a universal certification.
The portable writer supports scalar schemas and normalizes timestamps to UTC
microseconds (naive timestamps are interpreted as UTC); convert source-local
time explicitly before publication. Precision loss, unsupported types and
column names requiring mapping are rejected rather than silently upgrading the
table protocol.
This policy applies to analytical tables. Original image/document bytes remain
files; image AutoML descriptors and fine-tuning APIs can still require JSONL or
other task-specific exchange formats. Naming a binary folder silver/gold does
not make it a Delta table.

| Service | Supported route and qualification |
|---|---|
| Databricks | Native Delta read/write; use shared external storage for direct cross-engine access. Managed Unity Catalog tables have different access constraints. |
| Fabric | Delta via supported engines and OneLake shortcuts. A shortcut avoids copying but does not translate unsupported table features; Fabric experiences have different support. |
| ADF | Mapping Data Flow supports inline Delta source/sink. The Databricks Delta Copy connector runs through Databricks. Ordinary ADLS binary/Parquet Copy is not a Delta snapshot reader. |
| Azure ML | A mounted `uri_folder` exposes files, not Delta semantics. Use a Delta-aware reader or an `MLTable` definition containing `read_delta_lake` with `version_as_of`. |
| AutoML v2 | Accepts MLTable inputs, including the documented Delta-backed construction. Actual runtime/table-feature compatibility still needs a service run; explicit snapshot Parquet remains supported. |

Authoritative references:
[Fabric interoperability](https://learn.microsoft.com/en-us/fabric/fundamentals/delta-lake-interoperability),
[Databricks table features](https://learn.microsoft.com/en-us/azure/databricks/tables/features/feature-compatibility),
[ADF Delta format](https://learn.microsoft.com/en-us/azure/data-factory/format-delta),
[ADF Databricks connector](https://learn.microsoft.com/en-us/azure/data-factory/connector-azure-databricks-delta-lake),
[Azure ML MLTable Delta schema](https://learn.microsoft.com/en-us/azure/machine-learning/reference-yaml-mltable?view=azureml-api-2#delta-lake).

The Python `deltalake` dependency writes and reads actual Delta transactions
without requiring Spark for local/CPU examples. Delta reads always apply the log
at a pinned version. Never glob all `*.parquet` files under a Delta table: removed
rows/files may still exist physically. Parquet fallback is produced by a proper
snapshot read, with source-version lineage.

### Share back project silver without duplicating it

`SilverShareback` publishes a versioned product indexed by dataset, producer
project, variation and release. The project source must be a committed silver
publication, not gold or an arbitrary CSV. The default mode is `reference`;
`copy` explicitly creates an independently retained table.

The consumer selects the exact producer/variation/release and is checked against
the product's approved project list. Resolution verifies source scope, manifest,
table content and pinned transaction version; missing or changed sources fail,
rather than silently switching to another project's silver. A consumer reference
can drive an AML input binding after resolution. AML itself does not dereference
an arbitrary JSON file automatically.

```python
from pathlib import Path
from azure_esml.domain_layer.shareback import SilverShareback
from azure_esml.domain_layer.shared_lake import SharedLake

catalog = SilverShareback(Path("mounted-lake"), SharedLake("my-factory", "dev"))
catalog.publish(
    dataset="customers", producer_project="003", variation="cleaned-demographics",
    version="v1", source_key="mlops/v1/projects/project003/environments/dev/usecases/customers/dataops/runs/refine-v1/silver",
    table_relative="", owner="project003-data-owner", allowed_projects=["003", "004", "005"],
    mode="reference",
)
# project005 is an ESMLProject with its workspace/datastore already configured.
project005 = project005.with_shared_silver(
    catalog, dataset="customers", producer_project="003",
    variation="cleaned-demographics", version="v1",
)
```

`table_relative=""` shares a completed pipeline silver output directly; use a
relative subfolder when the committed source is an enclosing project release.
`list_variations(dataset, consumer_project=...)` exposes selectable producer
variants. `onboard_reference()` records the consumer's choice without copying
table payloads. The caller's mounted catalog must correspond to the datastore
used in that project; changing a local reference is not a cloud data transfer.

The same operations are exposed through local catalog CLI commands:

```powershell
esml shareback-silver --root mounted-lake --settings shared_lake_settings.json `
  --request silver_shareback.json --output shareback-receipt.json
esml resolve-silver --root mounted-lake --settings shared_lake_settings.json `
  --request consumer-selection.json --output resolved-silver.json
```

Use the [shareback request](../../../esml-v2/examples/app_layer/silver_shareback.json)
and [AppLayer composition](../../../esml-v2/examples/app_layer/silver_shareback.py)
as templates. A consumer selection contains `dataset`, `producer_project`,
`variation`, `version`, and `consumer_project`. Metadata-only references still
require retention of the **committed source release**; do not append or delete
files inside that immutable release. Publish another release for changed silver.
Independently managed mutable Delta tables require their own snapshot/retention
workflow before onboarding them as immutable shareback sources.

These changes apply to **new releases**. The uploaded
`bootstrap-v2-20260913-r2` Parquet data is preserved; the SDK does not rewrite that
committed Azure release or claim a live Fabric/ADF/AutoML compatibility run.

## Shared common lake: master to project IN

The common HNS-enabled account and a project's Blob account are both supported
storage targets. They are not interchangeable names: bind an explicit datastore
to the intended account/container. `SharedLake` and `SharedLakeIngestion` in
[`esml-v2`](../../../esml-v2) add the shared organization layer without moving or
overwriting old `projects/` data.

```text
lake3/
  mlops/v1/
    _system/blueprints/<version>/design.json
    master/environments/dev/
      datasets/<dataset>/versions/<source-version>/
        landing/                    Immutable original bytes
        changes/                    Explicit source changes and provenance
      products/<dataset>/versions/<product-version>/
        silver/                     Validated reusable Parquet/MLTable
        contract.json               Owner, schema, lineage, allowed consumers
      annotations/<dataset>/versions/<label-version>/
                                    Labels evolve independently of image bytes
    projects/project001/environments/dev/
      datasets/<dataset>/versions/<import-version>/
        in/                         Pinned copy of master or shared silver
        source-binding.json
      usecases/<use-case>/
        dataops/runs/<run>/          Bronze, silver and merged gold working data
        training/snapshots/<id>/gold/{train,validation,test}/
        training/runs/<run>/{model,evaluation}/
        inference/{batch,online,streaming}/models/<version>/runs/<run>/{in,gold,out}/
        operations/streaming/<pipeline>/versions/<version>/checkpoints/
        rag/corpora/<corpus>/versions/<version>/
        fine-tuning/{snapshots,runs}/
        labeling/tasks/             Reviewed annotation work
        quarantine/                 Rejections and dead letters, never model labels
        feedback/                   Actual outcomes, separate from predictions
```

Configure `storage.input_area: "in"` in the new SDK's lake settings to read the
project imports shown here. The earlier `landing` setting remains the default
for existing configurations; nothing silently renames those folders.
`master` versions preserve source provenance. Shared silver is an explicit,
validated **data product**, not whatever files happen to occupy a silver-named
folder. Models/use cases can pin a product version instead of repeating someone
else's cleansing. Project onboarding records the exact source manifest and copies
only that release into `in`; approval metadata does not itself grant Azure access.

### Initial, partial and delta loading

`SharedLakeIngestion.ingest()` performs full initial file snapshots or explicit
file changes against a verified previous version. Added/replaced/deleted files
are recorded in a new release; old versions are never edited. A file-copy
modification-time window is not CDC and does not infer deletions.

`ingest_rows()` handles keyed row changes with explicit upsert/delete operations.
Primary keys, schema and change ordering are validated; watermarks are explicit
UTC bounds and only committed data can advance the recorded position. Duplicate
or ambiguous events cannot silently become a new source of truth. Keep source
change semantics separate from pipeline execution IDs and model versions.

`publish_silver()` validates selected tabular columns and optional keys, preserves
the source lineage, and publishes a new shared product version. It does not fit
imputation/scaling on held-out data or invent business cleansing rules.
`onboard()` pins either master bytes or an approved shared silver product to a
project. A different project's read access remains an explicit RBAC/ACL decision.

The optional `DeltaLakeTable` adapter uses actual Spark/Delta initial writes,
keyed `MERGE` and `versionAsOf` reads. It must run in an environment with Spark
and Delta installed. Never create a directory called Delta or copy `_delta_log`
files and claim a transaction occurred. Concurrent-writer latest-version
observations are not proof of this request's exact commit; model snapshots pin
a reviewed transaction version. Local bootstrap publications use Parquet/JSONL,
not a simulated Delta engine.

### Images, streaming, RAG and fine-tuning

Original images remain versioned assets with content hashes. Classification,
multilabel, bounding-box and polygon instance annotations have separate immutable
releases and explicit review status. Gold snapshots bind image bytes, label
versions and splits; changing labels does not rewrite master images. The bootstrap
image example retains real Kaggle Pascal VOC annotations, not generated labels.

Streaming checkpoints are stable across request/model rollouts; event partitions,
dead-letter records and observed event time remain separate. Online captures and
LLM conversations require explicit retention/redaction decisions. Creating a lake
layout does not start Event Hubs, Structured Streaming or capture live traffic.

RAG snapshots retain source IDs/hashes, access metadata, chunker settings and
deletion tombstones. Chunks inherit source access restrictions. An index manifest
records that index creation/deletion synchronization is still required; it is not
a fabricated vector index. Fine-tuning snapshots require reviewed source/license
information and isolated train/validation/test conversations. No fine-tuning job,
embedding model or base-model evaluation is claimed merely from writing JSONL.

### Preview-first Kaggle bootstrap

The old `11-ESML-upload-lake-structure.sh` uploads `esml_lake.zip`, containing
3,927 entries, 1,284 files and 342 Parquet files, including historical samples and
mutable active pointers. It does not implement ACL creation. Do not rerun it to
initialize the new namespace or blindly upload stale data as current examples.

```powershell
esml lake-seed --settings shared_lake_settings.local.json `
  --source-root ..\usecase_code\50-ml-model-factory\data `
  --scenario-root ..\usecase_code\50-ml-model-factory\scenarios `
  --root outputs\shared-lake --version bootstrap-v2-001
esml lake-publish --root outputs\shared-lake --plan outputs\shared-lake\publication-plan.json
# After reviewing the exact account, paths, file count and bytes:
# esml lake-publish --root outputs\shared-lake --plan outputs\shared-lake\publication-plan.json --tenant-id <tenant> --subscription-id <subscription> --execute
```

The seed verifies actual Kaggle provenance, stages master data, shared silver,
project IN, real bronze/silver transformations and held-out gold, plus a bounded
image subset. The publisher creates absent blobs, compares existing bytes,
verifies uploads and writes `_SUCCESS.json` last. It does not change container
access, network controls, roles, ACLs, vector indexes or any other storage account.
A failed or interrupted publication is not a committed dataset. Read the returned
publication receipt and inspect Azure before claiming the common lake is populated.

**Spider Dev activation, September 13, 2026:** the user-approved
`bootstrap-v2-20260913-r2` seed is now in `spiderbltscesml001dev/lake3/mlops/v1/`:
245 files, 32,884,279 bytes, and 21 committed releases. It contains three real Kaggle
tables, master/shared silver/project IN/refined gold, 24 images with original
annotations and prepared vision splits, and 12 derived RAG sample documents.
The identity-only `esml_shared_lake` datastore is bound to this common HNS account
in `aml-001-sdc-dev-bltsc-001`; it is not the workspace default. Compute/workspace
data permissions were not granted, jobs were not submitted, and streaming,
vector indexes and fine-tuning remain unactivated. The `mrvel` account was untouched.

## ESML v2 DataOps request contract

The new [`esml-v2`](../../../esml-v2) SDK rebuilds the lake-mapped graph from
customer `lake_settings.json`; ADF callers do not need to know how many datasets
feed the gold merge. Its server-side `DataOpsAdapter` accepts:

```json
{
  "esml_data_date_utc": "2026-09-13",
  "esml_model_version": "7",
  "esml_run_id": "adf-request-001"
}
```

Use the processing date in UTC, including historical dates. `model_version` must
be explicit and immutable; `0` and `latest` are not silently resolved. Run IDs
identify requests and their output paths. A retry must keep the same request
identity; a new attempt uses a new ID. Deterministic names help reconciliation
but are not a distributed exactly-once guarantee.

Optional inputs are `esml_data_version`, `esml_project_name`, `esml_environment`
and `esml_allow_reuse`. If supplied, project/environment must match the
server-configured scope. Workspace, tenant, datastore and arbitrary paths cannot
be changed through the HTTP request. Dataset mapping and any discovery prefix
remain in trusted customer configuration.

The adapter builds and submits a native **v2 PipelineJob** and returns job
metadata immediately. It does not wait inside an HTTP function for training or
inference to finish. ADF must poll within a bounded Until/Wait loop and only
accept `Completed`/`Succeeded`; failed, cancelled or unknown statuses are not
success. A `202 Accepted` response is only submission acceptance.

The [AppLayer HTTP example](../../../esml-v2/examples/app_layer/dataops_adapter.py)
provides routes for one fixed project. Host authentication, private connectivity,
managed identity permissions and deployment are customer configuration, not
created by importing the SDK. Entra-protected Function ingress uses the Function
application's audience for ADF authentication; it is not the AML management or
batch-invocation audience.

Generate the matching code-first ADF definition without deploying anything:

```python
from azure_esml.domain_layer.dataops import adf_pipeline
definition = adf_pipeline(
    adapter_url="https://your-function.azurewebsites.net/api/esml/inference",
    adapter_resource="api://your-adapter-application-id",
)
```

Its single `esml_request` object contains the three parameters above. Generated
activities submit, poll, wait up to two hours and require explicit job success.
Install the `dataops` extra in a Function host. The HTTP example defaults to
Function-key authentication; use its `entra_protected=True` option for the
generated MSI workflow **only with mandatory EasyAuth authentication, matching
audience validation and an authorized-ADF-caller restriction configured on the
host**. That option does not create or enforce host settings on its own.

The old `AzureMLExecutePipeline` activity targets published **SDK v1** pipelines.
Do not pass the new v2 YAML or component IDs into that activity. The new adapter
resolves complete paths and model references before submission; AML does not
automatically interpolate a date parameter into every dataset URI.

### Source and output layout

Default training sources map each configured dataset to:

```text
mlops/v1/projects/project001/environments/dev/
  datasets/<dataset-folder>/versions/<data-version>/landing/
```

Inference source branches map under the selected use case, immutable model
version and request:

```text
.../usecases/<use-case>/inference/batch/models/<model-version>/runs/<run-id>/
  in/<dataset-folder>/
  gold/
  out/
```

Explicit read-only input path templates can map existing onboarding/legacy
partitions. Dataset discovery lists direct child folders under a configured
prefix, never all projects. Missing folders, incompatible schemas, ambiguous
join cardinality and absent labels fail explicitly. The default parser does
not infer customer cleansing rules or convert inference predictions into labels.

Intermediate pipeline outputs are run-specific. Shared source versions,
published gold snapshots, quarantined records and late feedback retain the
separate [lake design](34-datalake-onboard-data.md); a successful Azure output
upload is not an immutable snapshot publication.

The user-specified common account `spiderbltscesml001dev` is HNS-enabled, private,
and has container `lake3`. Read-only inspection on September 13, 2026 returned no
blobs there and no AML datastore bound to that common account. The existing
`ml_model_factory` datastore instead points at project storage2001. These are
distinct locations; the SDK does not silently repoint a datastore or claim the
common lake is already populated. `connect_datastore()` is an explicit,
credentialless AML binding operation; storage creation, RBAC and networking
remain separate.

## 1. DataOps in the complete lifecycle

```text
Kaggle download / explicit source
    |
    v
Source Blob location
    |
    +-- ADF initial Copy
    +-- ADF delta Copy: modification-time window
    |
    v
Dataset-version LANDING                  Raw bytes; not cleaned silver
    |
    +-- Azure ML v2 processing job
    +-- Databricks training/processing notebook
    |
    v
BRONZE -> validated SILVER -> use-case GOLD
    |                           |
    +-- rejection references    +-- train / validation / test
            |                              |
         quarantine                        v
                                   MLOps evaluation/gates
                                           |
                                   registered model version
                                           |
                             inference IN -> GOLD -> OUT
                                           |
                             observed FEEDBACK -> review
```

Copy, validation, training and promotion are separate operations. A successful
file transfer is not proof of valid labels, leakage-free splits, model quality
or deployment readiness.

## 2. Project, use-case and workspace mapping

An example orange project 001 / Dev inventory, observed September 11, 2026:

```text
Project 001 / Dev
|
+-- Data Factory: adf-001-sdc-dev-bltsc-001
|   +-- Raw initial/delta Copy
|   +-- Azure ML v2 job orchestration
|   +-- Optional Databricks notebook orchestration
|
+-- Azure ML: aml-001-sdc-dev-bltsc-001
|   +-- Classification / regression / forecasting
|   +-- Computer vision with task-specific data adapters
|
+-- Databricks: dbx-001-sdc-dev-bltsc-001
    +-- Custom tabular/forecasting training
    +-- Spark batch scoring and Event Hubs streaming examples
```

The resource names above are project-specific. Reusable templates receive names,
URIs and identities through configuration. They must not embed this project's
names as defaults for other factories.

See [MLOps model hierarchy](37-mlops.md#1-workspace-and-model-hierarchy) for all
11 configured model names grouped by engine and task. At the inventory read,
the Azure ML registry contained no models; scenario coverage did not imply
registered or deployed models.

## 3. Storage contract

```text
mlops/v1/projects/<project>/environments/<environment>/
    datasets/<dataset>/
        versions/<version>/
            landing/
            bronze/
            silver/
        quarantine/versions/<version>/
    usecases/<use-case>/
        training/snapshots/<snapshot>/gold/{train,validation,test}/
        training/runs/<run>/{model,evaluation}/
        inference/<batch|online|streaming>/models/<model>/runs/<run>/{in,gold,out}/
        quarantine/<serving>/models/<model>/runs/<run>/
        feedback/models/<model>/inference-runs/<run>/versions/<feedback-version>/
        operations/streaming/<pipeline>/versions/<version>/checkpoints/
```

Sources are shared within a project/environment, rather than duplicated under
every model or technology. Snapshot IDs identify preparation and split contracts;
run IDs identify executions. Keep quarantine and late feedback outside immutable
source/snapshot/run publications.

Raw inputs must retain their source identity and available download provenance.
Preserve hashes, schema/annotation versions and transformation history.
Predictions are not observed labels. Invalid data must not be silently relabeled,
accepted as silver or copied into a training snapshot.

No new workflow uploads the legacy `esml_lake.zip` merely to create folder shapes.
Leave existing ESML `projects/` paths unchanged. Use the
[onboarding guide](34-datalake-onboard-data.md) for exact publication and migration rules.

### Storage and identity prerequisites

The orange project's storage2001 uses **non-HNS Blob storage**. Use Blob APIs and
endpoints, not assumed `dfs`/ABFS access or directory ACLs. Logical folder prefixes
are not authorization boundaries.

Provision and validate these independently:

| Identity or component | Required access |
| --- | --- |
| Source/sink Blob identity | Read source and write the intended destination, scoped appropriately |
| ADF managed identity | Permission to submit/read Azure ML jobs |
| Azure ML job/compute identity | Read inputs and write outputs through its configured datastore |
| Databricks execution identity | Workspace/job permissions and independent storage access |
| ADF self-hosted integration runtime | Private DNS, routes and TLS access to the selected endpoints |

An AI Factory build agent is **not** automatically an ADF self-hosted integration
runtime. An ADF managed virtual network does not automatically route arbitrary
Web activities through the project network.
Do not fix missing private connectivity by silently enabling public access.

## 4. Code-first ADF templates

The [template directory](../../../copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory)
contains:

| File | Purpose |
| --- | --- |
| `main.bicep` | Linked services, datasets and pipelines under an existing factory |
| `parameters.example.json` | Existing factory, integration runtime and Blob endpoints |
| `copy.example.json` | Source/sink paths and initial/delta settings |
| `job-payload.example.json` | Example Azure ML Jobs ARM request shape, with unresolved assets |
| `prepare_run.py` | Offline validation and generation of ADF run parameters |

Deployment creates or updates only the named child resources. It does not create
a factory, storage account, workspace, compute, identity, role assignment,
integration runtime or trigger. Choose an isolated `namePrefix` and coordinate
with ADF Git authoring/publishing so later publishes do not overwrite live changes.

Two pipeline definitions are available:

| Pipeline | Behavior |
| --- | --- |
| `<namePrefix>_copy_aml_v2` | Copy input, submit an explicit Azure ML v2 ARM job, poll and require successful completion |
| `<namePrefix>_copy_databricks` | Copy input and call the supplied training notebook; created only with an existing Databricks linked service |

Resolve and review local parameters before following the
[installation instructions](../../../copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/readme.md#manual-install-administrator-action-not-performed-automatically).
Installation and queueing are separate, authenticated operations.

### Initial versus delta loads

Initial loads recursively copy matching files. Delta loads apply an explicit UTC
modification-time window `[watermarkStart, watermarkEnd)`. Source and destination
paths must not overlap.

This is file-level incremental copying, **not change-data capture or an exactly-once
transaction**. Deletions are not propagated. Persist the next watermark only after
the entire workflow succeeds. A retry may overwrite matching landing files; use
a new dataset version when source bytes change, and never target a committed
immutable source publication with mutable Copy operations.

## 5. Connect Copy to Azure ML v2

An Azure ML CLI job YAML and an ARM Jobs request body are **different schemas**.
Do not submit `pipeline.yml` as `jobPayload`. The ARM payload needs its actual
job type, versioned assets, compute and typed input definitions.

With no lake configuration, `prepare_run.py` preserves the supplied Copy settings
and explicit ARM job payload. It does not infer the relationship between them.

With `--lake` or `runtime.lake`, the optional adapter uses the shared `LakeLayout`:

1. Retain the configured external source folder and select the scenario's filename.
2. Bind the sink to dataset-version landing, not silver.
3. Bind the existing named ARM input, normally `raw`, to that exact copied file.
4. Record project, environment, dataset, snapshot, execution and serving metadata.

From the repository root with the model-factory environment available:

```powershell
$templates = 'copy_my_subfolders_to_my_grandparent\dataops\azure-datafactory'
$python = 'usecase_code\50-ml-model-factory\.venv\Scripts\python.exe'
& $python "$templates\prepare_run.py" --runtime runtime.local.json `
  --copy copy.local.json --job-payload job-payload.local.json `
  --lake lake.local.json --scenario usecase_code\50-ml-model-factory\scenarios\titanic.json `
  --input-name raw --output generated\adf-run.json
```

This command generates parameters locally and submits nothing.
The current lake adapter requires a single safe source filename. Image-directory
and complex annotation payloads need a reviewed folder/manifest binding; they are
not silently treated as tabular files.

ADF calls Jobs ARM API `2024-04-01`, using a known job ID derived from the ADF run ID.
It polls the same job resource. Azure ML success is `Completed`; ADF activity
success is `Succeeded`. Failed/canceled states fail the pipeline, and unknown or
missing states cannot be treated as success. The bounded wait does not cancel
the Azure job automatically.

There is **no automatic registration or endpoint deployment** in this ADF pipeline.
MLOps separately checks the evaluated model's quality gate and lineage.
Avoid the legacy `AzureMLExecutePipeline` activity for these v2 job definitions.

## 6. Databricks and streaming

The optional notebook activity calls the packaged `databricks\train.py` using
its actual widgets: `scenario_path`, `input_path`, `artifact_root`,
`experiment_path`, and optional `lake_config` and `model_context`. The optional
ADF `modelContext` parameter supplies model identity; alternatively include
`aifactory` in the lake configuration. Tags use the same project/environment,
dataset and run identity as the storage layout, and conflicting values are rejected.
This does not grant registry permissions or automatically register models.
The existing linked service,
cluster permissions and storage connectivity must be configured independently.
ADF credentials are not transferred to the notebook.

The notebook supports custom tabular/forecasting training and logs model and
evaluation artifacts to MLflow. Driver scratch files alone are not durable
outputs. Batch-scoring and streaming notebooks have different widget contracts;
do not interchange them with the training activity.

Event Hubs streaming examples use explicit request/entity/time fields,
deduplication/watermark policy, immutable model versions and stable checkpoints.
Checkpoints are keyed by pipeline identity/version, not every execution or
model rollout. A query or schema change can require a new checkpoint and an
explicit replay plan. Catalog table names and physical storage paths are
different settings.

These templates do not automatically deploy Event Grid/Data Mesh triggers,
cross-project sharing, or shareback/shareforward pipelines. Add such workflows
only with reviewed data contracts, ownership, identities and retention rules.
The former placeholder list of five pipelines was not implemented functionality.

## 7. Validate from ingestion to inference

Run the combined suite from `usecase_code\50-ml-model-factory`:

```powershell
python -m pytest tests ..\..\copy_my_subfolders_to_my_grandparent\mlops\03_mlops_2026-09\tests ..\..\copy_my_subfolders_to_my_grandparent\dataops\azure-datafactory\tests --junitxml=outputs\validation\lifecycle-results.xml -q
```

Local lifecycle tests execute ingestion/provenance, preparation, custom training,
evaluation, inference and observed feedback across all seven task types.
Deterministic fixtures simulate only the Kaggle download boundary in those tests.
Separate real Kaggle runs provide different evidence.

Orchestration tests exercise initial/delta parameters, SDK/CLI definitions,
CI provider contracts, model-promotion gates and failure behavior with cloud
responses simulated. This does not execute an ADF Copy, a Databricks stream,
AutoML fitting or live CI runners.

Before production, establish actual identity/RBAC, private connectivity, data
arrival, job completion, model registration and endpoint output. Explicitly
report unsupported image adapters, license gates and unavailable resources.
Do not confuse an empty folder, rendered template or successful unit test with
a completed cloud lifecycle.

## 8. Legacy and tenant migration

The legacy ESML lake and older notebook pipelines remain separate contracts.
Preserve their existing data and consumers until an explicit migration maps paths,
verifies checksums and reconciles permissions.

The yellow repository represents a retiring tenant; the user-designated cutover
to the orange tenant is September 16, 2026. Inventory any required source data,
models, identities, role assignments, checkpoints and integrations before removing
the old tenant. No cross-tenant data migration is performed by these templates.

Related pages: [data onboarding](34-datalake-onboard-data.md),
[MLOps and model hierarchy](37-mlops.md), and
[supported use cases](32-use_cases-where_to_start.md).
