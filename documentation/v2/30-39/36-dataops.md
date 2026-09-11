# DataOps: ingest, validate and orchestrate model data

DataOps supplies reproducible data and explicit job inputs to
[MLOps](37-mlops.md). The Machine learning model factory uses Kaggle sample sources,
the [versioned project/use-case lake](34-datalake-onboard-data.md), Azure Data Factory
(ADF), Azure ML v2 jobs and Azure Databricks notebooks.

Use the implemented
[Azure Data Factory templates](../../../copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/readme.md).
They are opt-in code-first artifacts, not evidence that pipelines, permissions or
triggers have already been deployed.

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
