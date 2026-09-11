# Onboard data: project and use-case lake design

The Machine learning model factory uses a versioned lake namespace that separates
**shared source data**, **training snapshots**, **model runs**, and **inference**.
It retains ESML's useful project boundaries and medallion concepts without relying
on mutable latest-data folders or copying the same source beneath every model.

This page describes the implemented `mlops/v1` layout in
[`50-ml-model-factory`](../../../usecase_code/50-ml-model-factory/readme.md).
Existing ESML consumers retain their legacy `projects/` layout. These are separate
storage contracts; adopting the new one does not automatically migrate old data.

## 1. The design at a glance

```text
Existing storage account / container
|
+-- projects/...                         Legacy ESML: leave unchanged
|
+-- mlops/v1/
    +-- projects/project001/
        +-- environments/
            +-- dev/                     Shown in detail below
            +-- test/                    Separate deployment environment
            +-- prod/                    Separate deployment environment
```

Within one project and environment:

```text
mlops/v1/projects/project001/environments/dev/
|
+-- datasets/                            Shared within this project/environment
|   +-- kaggle-titanic/
|       +-- versions/v1/                 Immutable source version
|       |   +-- landing/                 Original files, unchanged
|       |   +-- bronze/                  Parsed records or image inventory
|       |   +-- silver/                  Reusable source + validation metadata
|       |   +-- download-provenance.json When download provenance is available
|       |   +-- _SUCCESS.json            Files, hashes, publication metadata
|       +-- quarantine/versions/v1/      Rejected-source references and reasons
|
+-- usecases/
    +-- titanic/
        |
        +-- training/
        |   +-- snapshots/s001/          Data/preparation version, not model version
        |   |   +-- gold/
        |   |   |   +-- train/
        |   |   |   +-- validation/
        |   |   |   +-- test/
        |   |   +-- lineage.json
        |   |   +-- _SUCCESS.json
        |   +-- runs/r001/               One training execution
        |       +-- model/              MLflow model and dependencies
        |       +-- evaluation/         Metrics, Responsible AI, quality gate
        |       +-- lineage.json
        |       +-- _SUCCESS.json
        |
        +-- models/m001/binding/         Model version -> exact training artifact
        |
        +-- inference/
        |   +-- batch/models/m001/runs/score001/
        |   |   +-- in/                 Unlabeled requests with request IDs
        |   |   +-- gold/               Features matching the model input schema
        |   |   +-- out/                Predictions + request/model/run IDs
        |   |   +-- lineage.json
        |   |   +-- _SUCCESS.json
        |   +-- online/models/...       Same naming contract, different serving
        |   +-- streaming/models/...
        |
        +-- quarantine/batch/models/m001/runs/score001/
        +-- feedback/models/m001/inference-runs/score001/versions/f001/
        |                                Observed labels, not predictions
        +-- operations/streaming/titanic-scoring/versions/v1/checkpoints/
                                         Stable query state, outside run folders
```

This is a **logical object-key hierarchy**, not a command to create empty folders.
Objects appear when real data and metadata are written. Azure Blob keys use `/`;
local Windows paths use `\`. The shared `LakeLayout` builder handles the distinction.

### Why the hierarchy is ordered this way

| Dimension | Meaning |
| --- | --- |
| `mlops/v1` | Storage-contract version, separate from the legacy lake |
| Project and environment | Ownership and deployment scope before data reuse |
| Dataset and `data_version` | A source's content/provenance, reusable by several use cases |
| Use case | Business scenario and its model lifecycle |
| `snapshot_id` | Fixed source references, preparation settings, and gold splits |
| `run_id` | One training or inference execution |
| `model_version` | An exact model artifact, never a mutable `latest` or `active` alias |
| `pipeline_id` and `pipeline_version` | Streaming query identity and checkpoint compatibility |

Changing the algorithm does not require another copy of the raw dataset. A new
training run can reuse a matching snapshot. Changed data or preparation settings
require a new snapshot. Reusing an identifier for different content is rejected
by the local publication workflow.

The current local snapshot signature includes the full scenario configuration.
Consequently, changing an algorithm or quality-gate setting also requires a new
snapshot ID, even when the underlying source and split rules are unchanged.
This conservative restriction does not require duplicating the shared source.

`environments/test` is the test deployment environment. `gold/test` is a held-out
evaluation split. Neither is an alias for the other.

## 2. Medallion stages and the data flow

```text
Kaggle / approved source
          |
          v
       LANDING ----> BRONZE ----> SILVER
       original      parsed      source schema/validation
          |                         |
          +---- rejected ----------+----> quarantine references
                                    |
                                    v
                           Use-case GOLD snapshot
                          /          |           \
                       train     validation      test
                         |                       |
                fit preprocessing/model         |
                         +----> evaluate <--------+
                                    |
                             quality gate passes
                                    |
                            model + run lineage

Unlabeled requests --> IN --> inference GOLD --> saved model --> OUT
                         \---- invalid --------------------> quarantine

Later observed outcomes --> FEEDBACK --> explicit review --> NEW training snapshot
```

The medallion stage names describe **work performed**, not just destination folders:

| Stage | Implemented behavior and boundary |
| --- | --- |
| Landing | Preserve source bytes; retain available Kaggle download provenance and hashes |
| Bronze | Parse tabular data into Parquet; for images, inventory source assets |
| Silver | Basic reusable tabular schema validation and metadata, without fitting learned transformations |
| Training gold | Validate use-case inputs and create fixed training/validation/test splits |
| Inference gold | Match the saved model's feature schema; no labels or training-time fitting |
| Quarantine | Record reason codes and source references; do not silently promote rejected data |

Basic silver validation is not a claim of complete business-rule cleansing. For
images, source metadata explicitly marks task-specific annotation validation as
pending; the vision preparer validates images and annotations before gold.
An ADF binary Copy activity produces landing data, **not** cleaned silver.

Imputation, scaling and encoding are fitted on training data only and saved with
the model. Validation and test data must not influence those fitted statistics.
For repeated customers, patients or devices, configure `split.group_column` to
keep each entity in one tabular split. A random row split alone cannot establish
entity independence. Forecasting uses chronological windows per time series.

## 3. Training versus inference, bad data, and feedback

Training data requires real target labels. Missing labels are not replaced with
zero or model predictions. Inference requests contain features and a unique
`request_id`; they must not contain the training target.

Tabular predictions retain the request ID, prediction, model version and run ID.
Vision requests use `image_base64` plus a request ID; the four vision task types
share the same lifecycle layout while retaining their own annotation and result
schemas.

Quarantine replaces the ambiguous legacy `bad/` convention. Rejection records
identify the source and reason without automatically duplicating raw personal
data. Raw rejected-data retention, access restrictions and deletion policies are
separate decisions; a reference is not a guarantee that raw rejected bytes were
retained.

Feedback contains independently observed outcomes with `request_id`, the target
label and `observed_at`. It is tied to an exact inference run. The local workflow
requires `feedback_version` and `feedback_source` and marks the result
`training_eligible: false`. Review, consent, data-quality and leakage checks must
precede an explicit new training snapshot.

Quarantine and feedback sit **outside immutable source/snapshot/run publications**.
Late outcomes or new diagnostics therefore do not change an earlier run's hashes.

## 4. Batch, online, streaming, and different model types

All seven task types use this hierarchy: tabular classification, regression,
time-series forecasting, multi-class image classification, multi-label image
classification, object detection and instance segmentation.

Model type and execution technology belong in configuration and lineage, not
additional lake levels. The code templates can be organized by technology, but
Azure ML AutoML, custom Python and Databricks should not each duplicate a source
dataset simply because they use different tools.

| Serving pattern | Data and operational state |
| --- | --- |
| Batch | Input requests and predictions scoped to an immutable model version and run |
| Online | The same identity/lineage contract for captured requests/results; an endpoint still requires separate hosting |
| Streaming | Query-owned outputs plus a stable checkpoint keyed by pipeline identity/version |

The checkpoint path does not include `run_id` or `model_version`. Restarting a
query or rolling out a model must not automatically reset offsets. An incompatible
query/schema change requires a new pipeline version and a deliberate replay plan.
Checkpoint compatibility, Delta table names and physical storage locations remain
distinct configuration concerns.

The local `lake-infer` command processes a finite request file. Selecting `online`
or `streaming` changes its path contract; it does not start a server or stream.
Databricks and endpoint examples supply the respective execution engines.

## 5. Onboard data locally

Run from `usecase_code\50-ml-model-factory` or its orange-repository copy. Follow
the [factory setup guide](../../../usecase_code/50-ml-model-factory/readme.md#running-the-factory)
to provision and activate the Python environment. New Azure ML examples use SDK v2
and CLI v2, not the legacy SDK v1.

1. Select a scenario and review its Kaggle license, authentication requirements,
   source schema and labels. A required-selection or license-review gate is not
   bypassed automatically.
2. Copy `lake.example.json` to an ignored `lake.local.json`. Set project,
   environment, use case, dataset version, snapshot ID and a unique run ID.
3. Resolve the layout before writing data:

```powershell
python -m ml_model_factory lake-plan --scenario scenarios\titanic.json --config lake.local.json
```

Download and run a custom-training example:

```powershell
python -m ml_model_factory ingest --scenario scenarios\titanic.json --output data\titanic
python -m ml_model_factory lake-train --scenario scenarios\titanic.json --config lake.local.json --root lake-data --input data\titanic\train.csv
```

Titanic competition access requires your own authenticated Kaggle account and
acceptance of its rules. The commands do not accept terms on your behalf.
For images, pass the source directory containing the required images and annotations.

The local workflow publishes the source version, then the gold snapshot, then the
model/evaluation run. It uses exclusive publication paths and checksum manifests.
Failed quality gates retain diagnostics but do not publish a successful model.
`lake-train` is the custom-training route; AutoML uses the separate Azure job route.

For inference, create a separate `scoring.local.json` with a fresh `run_id`,
the exact `model_version`, and the intended serving pattern. Prepare an unlabeled
request file and pass the model path returned by training:

```powershell
python -m ml_model_factory lake-infer --scenario scenarios\titanic.json --config scoring.local.json --root lake-data --input requests.parquet --model "<committed-training-run>\model"
```

Keep datasets, models, outputs, local configuration and the virtual environment
out of Git. Only templates and reproducible configuration examples belong there.

## 6. Publish and orchestrate in Azure

### Storage prerequisites

Use an existing storage account/container with authorized identity-based access
and working private connectivity. Configure `storage.account_url`,
`storage.container` and, for Azure ML bindings, an existing credentialless
`storage.datastore`. The datastore must actually map to the intended storage.

For non-HNS Blob storage, use the Blob endpoint. Do not assume `dfs`/ABFS support
or directory ACLs. Project/environment prefixes are logical scopes, **not access
controls**. Enforce isolation using appropriate containers/accounts, RBAC and
network policies; apply retention and regulatory controls separately.

### Preview-first publication

```powershell
python -m ml_model_factory lake-publish --scenario scenarios\titanic.json --config lake.local.json --root lake-data --area training_snapshot
```

The default is a transfer plan, with no Azure writes. After approving the destination
and content, `--execute --tenant-id <tenant-guid>` enables explicit token-authenticated
publication. Supported areas are `dataset_root`, `training_snapshot`, `training_run`
and `inference_root`; this is not a general-purpose uploader for arbitrary folders.

The publisher writes data first and `_SUCCESS.json` last, rejects conflicting
objects, and does not create a container or change ACLs/RBAC. Readers must require
the completion manifest and matching content. This is an application-level
publication contract, not Azure Storage WORM or a legal-hold policy.

An interrupted upload may leave an incomplete prefix or publication lock. Inspect
and reconcile it before retrying; do not treat folder existence as success.

### Azure ML, ADF, CI and Databricks

Add optional `lake` configuration to runtime JSON for Azure ML output bindings.
Each Azure job writes preparation data beneath
`training/runs/<run_id>/prepared/`, separately from a shared gold snapshot.
Its model and evaluation use the corresponding run paths. Snapshot paths in that
bundle are references: direct Azure output bindings do not publish a snapshot or
provide storage-enforced immutability. Existing configurations without `lake`
retain their previous behavior.

Use the [ADF templates](../../../copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/readme.md)
for raw Copy into landing and explicit Azure ML v2 or Databricks job orchestration.
The lake-aware ADF adapter currently binds a single source file; image directories
need a reviewed folder/manifest binding. Do not claim that a raw copy performs
schema validation, quarantine or model promotion.

The [MLOps templates](../../../copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md)
generate fresh execution IDs and retain source/snapshot lineage. Databricks uses
the same path builder and stable checkpoint identity; physical checkpoint backend
support and cluster permissions must be configured explicitly.

Azure Storage Explorer is useful for inspection and authorized manual onboarding.
Do not edit files beneath a completed version or fabricate `_SUCCESS.json` by hand.
Use a new source version and the validated publication workflow instead.

## 7. Legacy ESML compatibility and migration

The old layout remains distinct:

```text
projects/<project>/<model>/train/<dataset>/in/<env>/<date>/
projects/<project>/<model>/train/<dataset>/out/<bronze-or-silver>/<env>/
projects/<project>/<model>/inference/<model-version>/...
```

Legacy consumers depend on exact paths, casing and active-pointer behavior.
The old upload script and `esml_lake.zip` are not the initializer for `mlops/v1`.
The archive includes sample Parquet data, Spark markers and sentinel dates, not
just a declarative folder specification.

Before migrating, inventory required sources, checkpoints, registrations,
identities and permissions; map old paths to new identities; copy explicitly; and
compare hashes and consumer behavior. Do not delete the old data merely because
the new templates work. Complete any cross-tenant migration before retiring the
source tenant.

Related legacy guidance:
[SDK/ESML setup](33-install-azureml-sdk-v1+v2.md) and
[supported use cases](32-use_cases-where_to_start.md).

Implementation references:
[`LakeLayout`](../../../usecase_code/50-ml-model-factory/ml_model_factory/lake.py),
[local lifecycle](../../../usecase_code/50-ml-model-factory/ml_model_factory/lake_flow.py),
[example configuration](../../../usecase_code/50-ml-model-factory/lake.example.json).