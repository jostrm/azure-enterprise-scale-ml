# MLOps: Machine learning model factory

Use the [Machine learning model factory](../../../usecase_code/50-ml-model-factory/readme.md)
for configurable Kaggle-backed training, evaluation, registration and inference.
Azure Machine Learning is the primary engine, with **AutoML and custom training**.
Azure Databricks provides additional custom tabular/forecasting and Spark examples.
All Azure ML control-plane examples use **Python SDK v2 and CLI v2**.

Start with [data onboarding and lake design](34-datalake-onboard-data.md) and
[DataOps orchestration](36-dataops.md). Reusable CI templates are in
[`mlops/03_mlops_2026-09`](../../../copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md).

## ESML v2: the pip-installable pipeline factory

The rebuilt SDK lives in [`esml-v2`](../../../esml-v2), with distribution name
**`azure-esml-sdk`** and Python import **`azure_esml`**. It uses only
`azure.ai.ml` (Azure ML SDK v2) and `az ml` CLI v2. The Python SDK distribution
itself uses `1.x` version numbers; that does not mean it is the retired SDK v1
package `azureml-core`.

The legacy `esml`, `esmlrt`, `esmlfac`, and quickstart notebooks remain untouched.
This is a new API, not an import-compatible v1 shim. Start with the new
[pipeline notebook](../../../esml-v2/examples/app_layer/01_pipeline_factory.ipynb)
and [data/inference notebook](../../../esml-v2/examples/app_layer/02_data_assets_and_inference.ipynb).

### Installation and package boundary

From the repository root:

```powershell
pip install ".\esml-v2[train,storage]"
```

Or install the built wheel from `esml-v2\dist`. The intended public-index command
is `pip install azure-esml-sdk`, but **PyPI publication is a separate release
action**: building a wheel or pushing GitHub does not make that command available.
Do not claim an index release until it has actually been published.

The package build includes the existing v2 `ml_model_factory` engines from their
canonical source in `usecase_code\50-ml-model-factory`. A temporary build staging
directory creates a self-contained wheel and source archive. Installed consumers
do not need that repository path, an editable checkout, or an unpublished second
package. There is no second maintained copy of training/evaluation/selection code.
Use a clean consumer environment rather than installing both this distribution
and the older `aifactory-ml-model-factory` distribution over the same import package.

| Layer | Responsibility |
|---|---|
| `azure_esml.base_layer` | Generic `MLBackend` and `IFolderCatalog` abstract contracts; injected SDK/CLI transports, explicit credentials, credentialless datastore bindings, data/model/job operations |
| `azure_esml.domain_layer` | ESML lake settings, naming, request validation, pipeline factory, step-map abstraction, DataOps contract and adapters to the shared v2 engines |
| `examples/app_layer` | Customer configuration, Python composition, notebooks, optional HTTP/Databricks examples |

Dependencies point from AppLayer to DomainLayer to BaseLayer. BaseLayer has no
ESML project naming or customer configuration dependencies. Configuration reads
do not log in, provision compute, alter default datastores, or change global
working directories. Authentication is injected or explicitly selected; there
is no credential fallback through unrelated tenants.

### One line creates the mapped pipeline

```python
from pathlib import Path
from azure_esml import ESMLProject, PipelineRequest, PipelineType

project = ESMLProject.from_json(Path("lake_settings.json"))
request = PipelineRequest(data_date_utc="2026-09-13", run_id="training-001")
plan = project.create_pipeline(PipelineType.IN_2_GOLD_TRAINING_AUTOML, request, output=Path("generated"))
```

The final line creates the complete graph, code bundle, v2 YAML and lineage/asset
manifest. It does **not** submit. `plan.to_sdk()` loads the same document with
SDK v2; `az ml job create --file generated\pipeline.yml` uses CLI v2.
Use `project.execute_pipeline(plan)` with an explicitly injected backend for the
scoped facade, including model-scope validation.

```powershell
esml render --settings lake_settings.json --type IN_2_GOLD_INFERENCE `
  --date 2026-09-13 --model-version 7 --run-id inference-001 --output generated
esml submit --settings lake_settings.json --pipeline generated\pipeline.yml --backend sdk
# Alternative transport for the same job, not a second submission:
# esml submit --settings lake_settings.json --pipeline generated\pipeline.yml --backend cli
```

| Pipeline type | Graph |
|---|---|
| `IN_2_GOLD` | One refinement branch per dataset, then a gold merge |
| `IN_2_GOLD_INFERENCE` | Refinement branches, gold merge, inference |
| `IN_2_GOLD_INFERENCE_DBX` | The same graph with explicitly mapped Databricks components for every required step |
| `GOLD_INFERENCE` | Prepared gold input directly to inference |
| `IN_2_GOLD_TRAINING_AUTOML` | Refinement, merge, leakage-aware split, native AutoML node, held-out evaluation |
| `IN_2_GOLD_TRAINING_MANUAL` | Refinement, merge, split, custom estimator, held-out evaluation |

Public steps use `IN_2_BRONZE`, `BRONZE_2_SILVER`, `IN_2_SILVER`,
`SILVER_MERGED_2_GOLD`, `INFERENCE_GOLD`, `TRAINING_AUTOML`, `TRAINING_MANUAL`,
`TRAINING_SPLIT_AND_REGISTER`, and `EVALUATE`. The historical split-step name
is retained with the requested `TRAINING` spelling, but registry writes are an
explicit post-success operation rather than hidden inside data splitting.

### Lake mapping, dynamic inputs, and names

`use_common_datalake_storage` selects common (`true`) or project (`false`)
data storage for every generated pipeline. Supply explicit `storage_targets`
profiles; the project workspace/compute do not move. The same setting is supported
by the ML use-case runtime and the agent factory. See
[storage selection](36-dataops.md#selecting-the-common-lake-or-project-data-account).
Changing it requires re-rendering and existing data/permissions at the selected
location; it is not a migration operation.

The [AppLayer lake_settings.json](../../../esml-v2/examples/app_layer/lake_settings.json)
retains the recognizable `project_number`, `project_folder_name`, `active_model`,
`models`, `model_number`, `model_folder_name`, `model_short_alias`,
`dataset_folder_names`, `label`, `ml_type`, and `ml_metric` fields.
It adds explicit factory, storage, runtime, feature, merge and split settings.
The old mapping file alone is not enough to establish v2 connectivity.

One source folder produces one input/refinement branch. Two or twelve folders
produce two or twelve branches, without copying pipeline Python. Explicit
`discover_datasets` plus an injected folder catalog reads direct child folders
under a selected prefix; an empty or invalid discovery does not create a fake
successful pipeline. There is no unbounded scan of the whole storage account.
Adding/removing datasets changes the component's graph and requires regeneration.

Names follow the mapping: for example,
`project001_11_diabetes_classification_pipe_IN_2_GOLD_INFERENCE` and
`M11_ds01_diabetes_inference_SILVER_dev`. Long Azure names receive a stable hash
suffix rather than ambiguous truncation. Factory/project/environment/use-case
tags accompany jobs and versioned assets; Stage uses wire value `test`.

New output locations follow `mlops/v1/projects/project001/environments/dev`.
Shared dataset source versions remain separate from model-specific training
runs and inference model/run outputs. Pipeline working silver/gold/splits are
run-specific: generating a pipeline does not overwrite a published gold snapshot
or guarantee storage-enforced immutability. Explicit source path templates can
read legacy locations, but new outputs never rewrite the legacy hierarchy.

### Customization, lifecycle, and limits

New configurations default to `bronze: true`, preserving source bytes before
silver validation. `bronze: false` explicitly selects the combined IN-to-SILVER
fast path. Neither skips the separate gold representation, including when there
is only one dataset. Silver validation does not claim to infer customer
cleaning rules. Concatenation requires compatible schemas; relational joins
require explicit keys and cardinality constraints. Implement `IPipelineStepMap`
or use `DictionaryStepMap`/`StepOverride` to replace individual components or
select different existing CPU/GPU compute. No cluster is automatically created.

New silver and canonical gold use `table_format: "delta"` by default.
`aml_table_format` follows that setting for the training/validation/test MLTable
ports, using a pinned Delta snapshot. Set either explicitly to `"parquet"` for a
documented compatibility path. The custom Python estimator/evaluation engine
uses a verified Parquet projection of gold-derived splits internally. It never
trains directly from raw or reusable silver data. Dataset-specific gold is under
the project/use case, with the merged table and split tables in non-overlapping
`gold/table` and `gold/splits/<split>` paths.

An explicitly selected shared silver reference can bypass repeated raw refinement
while still feeding the gold merge. Dataset settings carry `source_stage: "silver"`,
an exact `input_path`, `format`, and `delta_version` for Delta. Resolve and validate
the producer/variation/release through `SilverShareback` before creating that
binding. The same URI/file-folder contract works against the configured common
Gen2 or project storage; permissions and source retention remain prerequisites.
See [Delta and shareback details](36-dataops.md#delta-interoperability-and-shareback).

The built-in tabular worker supports classification, regression and forecasting;
it reuses the existing leakage-aware preparation and MLflow evaluation engines.
The four vision scenarios remain available in `50-ml-model-factory`; they are
not automatically treated as tabular rows by this pipeline builder.
Databricks uses an explicit Jobs bridge/custom component, not the v1
`DatabricksStep`, which has no direct v2 replacement.

`DatabricksStepMap` maps dataset/stage keys to existing job IDs and notebook task
keys. Its bridge uploads the actual named input files to a project-scoped
transfer prefix, invokes the job with managed identity, waits within a bound,
verifies the notebook's exact output receipt and downloads real output files into
AML output mounts. Downstream nodes receive data, not a JSON file masquerading
as a dataset. The [Databricks AppLayer example](../../../esml-v2/examples/app_layer/databricks_notebook.py)
implements driver-sized conversion, merge and MLflow inference; distributed Spark
processing and Databricks training replacements remain explicit customer notebooks.
The Azure ML and Databricks environments must install the SDK and their required
`train`/`databricks` extras beforehand. Transfer retention is customer-managed;
the library does not erase transfer data automatically.

`allow_reuse` maps to pipeline rerun/component determinism controls. Reuse is
conditional on Azure's inputs/code/settings comparison; new request metadata
or external mutable data can prevent reuse. No percentage cost saving or runtime
is promised. Databricks side-effect components are nondeterministic.

Use `project.wait_for_completion()` for bounded polling, `register_outputs()` for
explicit successful-job data asset registration, `get_dataset(name, version)` for
scoped access, and `register_model()` for the existing quality/lineage and optional
winning-model policy gates. Successful training is not automatic deployment or
cross-environment promotion. Missing labels, unsupported metrics and failed jobs
never become a successful quality result.

`publish_pipeline()` explicitly registers a pipeline component and batch
deployment without changing endpoint default traffic. The published record binds
the reviewed plan; `invoke_pipeline()` refuses a different plan. For daily or
historical dates, the [DataOps adapter](36-dataops.md#esml-v2-dataops-request-contract)
rebuilds concrete input/output/model bindings from the same small request contract.
It does not send legacy v1 published-pipeline IDs to ADF.

Compute provisioning, networking/RBAC changes, online/AKS canary deployment,
cross-workspace promotion, schedules, public package publication and live cloud
execution are separate explicit operations, not side effects of creating a
pipeline.

## 1. Workspace and model hierarchy

The following is a **project example, not a hardcoded template configuration**.
Resource names must be resolved from each project's configuration and Azure inventory.

**Orange project 001 / Dev, observed September 11, 2026:** the Azure ML workspace,
CPU compute and Databricks workspace exist. The Azure ML model registry was empty
at the latest inventory read. Names below are configured model names and notebook
coverage, **not a list of registered or deployed models**. Databricks registry
contents were not inventoried.

```text
Orange project 001 / Dev
|
+-- Azure Machine Learning
|   +-- Workspace: aml-001-sdc-dev-bltsc-001
|       +-- CPU compute: p001-m01sdc-dev
|       +-- Classification
|       |   +-- titanic-survival
|       |   +-- diabetes-classification
|       |   +-- telco-churn
|       +-- Regression
|       |   +-- insurance-charges
|       +-- Forecasting
|       |   +-- monthly-air-passengers
|       |   +-- delhi-temperature
|       |   +-- orangejuice-sales
|       +-- Computer vision
|           +-- Multi-class: scene-classification
|           +-- Multi-label: fruit-multilabel
|           +-- Object detection: car-plate-detection
|           +-- Instance segmentation: sar-ship-instance-segmentation
|
+-- Azure Databricks
    +-- Workspace: dbx-001-sdc-dev-bltsc-001
        +-- Custom classification notebook coverage
        |   +-- titanic-survival
        |   +-- diabetes-classification
        |   +-- telco-churn
        +-- Custom regression notebook coverage
        |   +-- insurance-charges
        +-- Custom forecasting notebook coverage
            +-- monthly-air-passengers
            +-- delhi-temperature
            +-- orangejuice-sales
```

The same logical model names can describe experiments on different engines.
That does not imply a shared registry or automatic cross-platform model copying.
Record the source engine, immutable model version, run and artifact location.

### Scenario-to-model mapping

The [scenario JSON files](../../../usecase_code/50-ml-model-factory/scenarios)
are the source of truth for these names and task settings.

| Scenario | Model name | Type | Source/access notes |
| --- | --- | --- | --- |
| `titanic` | `titanic-survival` | Classification | Kaggle competition authentication and accepted rules required |
| `diabetes` | `diabetes-classification` | Classification | Educational diabetes classification, not clinical decision support |
| `churn` | `telco-churn` | Classification | Dataset license review required |
| `insurance-regression` | `insurance-charges` | Regression | Continuous charges target; review attribution and intended use |
| `air-passengers` | `monthly-air-passengers` | Forecasting | Monthly series; preserve dataset attribution |
| `delhi-weather` | `delhi-temperature` | Forecasting | Daily series; unknown future weather covariates are excluded |
| `orangejuice` | `orangejuice-sales` | Forecasting | Suitable Kaggle chronological sales dataset still required |
| `image-multiclass` | `scene-classification` | Multi-class images | Dataset license review required |
| `image-multilabel` | `fruit-multilabel` | Multi-label images | Annotation conversion required |
| `image-object-detection` | `car-plate-detection` | Object detection | Pascal VOC annotation adapter |
| `image-instance-segmentation` | `sar-ship-instance-segmentation` | Instance segmentation | Supported COCO polygon annotations; crowd/RLE needs another adapter |

Diabetes presence and customer churn with categorical labels are classification
tasks even when a model produces probabilities. They are not regression simply
because a risk score is numeric.

## 2. Technology and serving coverage

| Type | Azure ML AutoML | Azure ML custom | Databricks examples |
| --- | --- | --- | --- |
| Classification/regression | v2 training/pipeline definitions and gated evaluation/registration | scikit-learn training and MLflow models | Shared custom training, Spark batch/streaming examples |
| Forecasting | v2 forecasting; evaluator supports compatible sklearn-flavor models exposing `forecast()` | Seasonal-naive baseline with an explicit supported horizon | Shared custom forecasting and applicable Spark integration |
| All four computer vision tasks | Standalone v2 training definitions; full evaluation/promotion adapter is not implemented | Bounded torchvision training, task-specific evaluation and MLflow export | No packaged end-to-end vision training notebook |

The factory includes **11 scenarios and 22 Jupyter notebooks**, one custom and one
AutoML notebook per scenario. A template's presence does not establish dataset
access, successful training or deployment.

Serving is a separate dimension from model type:

```text
One evaluated model version
    +-- Batch       File/table input -> predictions persisted to storage
    +-- Online      REST request -> near-real-time response
    +-- Streaming   Event Hubs -> Structured Streaming -> results/checkpoints
```

Support is operation-specific. Current Azure serving helpers generate tabular
MLflow batch/online deployments and custom-vision online deployments where supported.
They do not generate image batch deployments or AutoML forecasting deployments.
AutoML image models cannot pass the factory's gated registration/deployment route
until a suitable evaluation adapter exists. Databricks streaming examples do not
prove that every task/model flavor supports a Spark UDF or live stream.

## 3. DataOps-to-MLOps lifecycle

### Model identity tags: one small contract

`ml_model_factory.tags` produces a string dictionary used by Azure ML SDK v2,
CLI v2 model definitions, local MLflow artifacts and Databricks model versions.
It preserves ESML's useful ownership, training-origin and evaluated-candidate
concepts without its SDK v1 controllers, mutable active-model files or large
metric-specific tag collections.

Example tags for the orange target:

```yaml
tag_schema: ml-model-factory/v1
aifactory: spider-001
project: "001"
environment: dev
training_environment: dev
use_case: diabetes
task_type: classification
training_engine: azureml
training_mode: automl
dataset: kaggle-diabetes
data_version: v1
snapshot_id: gold-20260911-01
run_id: train-20260911-03
```

The last four data/run tags come from the selected lake configuration when present;
they are not guessed from a model name. Without lake configuration, dataset metadata
comes from the scenario and unavailable snapshot/run values are omitted.

Registration additionally records `source_run_id`, `quality_gate: passed` and
`lifecycle_status: candidate`; Azure ML also records the originating workspace ARM
ID as `source_resource_id`. A candidate is not automatically promoted to production.
Metrics, confusion matrices, explanations and detailed lineage remain artifacts,
not sprawling tag values.

Set the explicit factory identity in the project's `project.json`:

```json
{
  "aifactory": "spider-001",
  "variables_file": "..\\variables.json",
  "environment": "dev",
  "resource_group": "spider-esml-project001-sdc-dev-001-rg"
}
```

Discovery obtains the three-digit project number from `variables.json`, resolves
actual resources and writes `aifactory`, `project` and `environment_name` into
runtime JSON. `environment_name` is the deployment scope; runtime `environment`
still means an Azure ML environment asset such as `azureml:training-runtime:3`.

Preview tags without changing any model:

```powershell
python -m ml_model_factory tags --scenario scenarios\diabetes.json --context runtime.local.json --engine azureml --mode automl
```

Model tags must agree with `runtime.lake` and the evaluated lake lineage:
`project001`, `environments/dev`, the use-case folder, dataset version, snapshot
and execution IDs. The factory identity belongs to the selected storage/project
context; adding tags does not rename the lake or introduce a legacy model-first
directory tree. Mismatches are errors, not silently rewritten labels.

Rendering and exploratory local training can use partial metadata. Cloud
submission and registry writes require complete factory/project/environment
identity; SDK and CLI wrappers reject a differently scoped job before submission.
New tagged jobs
must have matching tags in their evaluated report; older factory jobs require
explicit context and valid task/mode lineage. Deployment preserves the registered
model's origin tags and rejects a different factory/project/environment. Cross-
environment promotion is not implemented by relabeling the same model.

Local tags are stored in `factory.json` and MLflow `MLmodel` metadata before the
artifact is committed. The factory refuses to edit tags inside an immutable,
already-published lake run. Local metadata is not evidence of cloud registration.
Existing untagged immutable local runs are not silently backfilled; create a
new identity-bearing run instead. Azure AutoML output files remain service-owned;
their full identity is on the submitted job, evaluated report and registered
model version rather than an in-place rewrite of the AutoML output.

Databricks training accepts an optional `model_context` JSON/path widget and
merges it with `lake_config`, rejecting conflicting identities. It tags the
tracking run and model artifacts. The separately invoked
`databricks/model_tags.py::register_evaluated(...)` verifies the finished run,
quality gate and model metadata before registering a tagged model **version**.
It does not rewrite name-level registry tags or register automatically.

```text
DataOps
  Kaggle ingestion -> landing -> validation/preparation -> gold snapshot
                                                           |
MLOps                                                     v
  validate config -> train -> held-out evaluation + Responsible AI
                                    |
                             quality gate passes
                                    |
                       register exact evaluated artifact
                                    |
                         separate deployment approval
                                    |
                    batch / online / streaming inference
                                    |
                    observed feedback -> explicit review
                                    |
                            new training snapshot
```

Source versions are shared within a project/environment. Gold snapshots belong
to a use case; model and evaluation artifacts belong to individual runs.
Snapshot identity includes source hashes and preparation settings, not algorithms,
AutoML budgets or quality thresholds. Different model variants can reuse unchanged
gold while producing separate evaluations. Changed features, split/group rules,
forecast horizons or annotation mappings require a new snapshot.

Use immutable model versions. Keep inference requests unlabeled and retain request,
model and run identifiers in results. Store observed labels separately from
predictions; feedback is not automatically training-eligible.
See the [visual lake hierarchy](34-datalake-onboard-data.md#1-the-design-at-a-glance).

## 4. SDK v2 and CLI v2 execution

### Define the winning model in JSON

Edit [`model-selection.json`](../../../usecase_code/50-ml-model-factory/model-selection.json)
in your orange model-factory copy. It replaces the ESML v1 comparison controller
with a small shared Python/CLI policy, not a weighted sum of unrelated units.
Use a different policy file per use case/environment when requirements differ.

The supplied profiles cover classification, regression, forecasting and all four
vision tasks. For example, classification selects:

```json
{
  "on_tie": "keep_champion",
  "require_any_improvement": true,
  "metrics": [
    {"metric": "auc_weighted", "direction": "maximize", "min_delta": 0.02, "delta_mode": "absolute"},
    {"metric": "accuracy", "direction": "maximize", "min_delta": -0.0001, "delta_mode": "absolute"},
    {"metric": "f1_weighted", "direction": "maximize", "min_delta": -0.0001, "delta_mode": "absolute"},
    {"metric": "matthews_correlation", "direction": "maximize", "min_delta": 0.0, "delta_mode": "absolute"}
  ]
}
```

This is a **profile excerpt**, nested under `profiles.classification` in the full
versioned policy. AUC must improve by at least 0.02; accuracy/F1 may decrease by at
most 0.0001; MCC must not decrease. All selected rules must pass.

| Setting | Meaning |
|---|---|
| `direction` | `maximize` for accuracy/AUC/F1/MCC/R2/Spearman/mAP; `minimize` for errors, log loss and Hamming loss |
| `min_delta > 0` | Required improvement, inclusive at the threshold |
| `min_delta = 0` | No regression on that metric |
| `min_delta < 0` | Explicitly tolerated regression; not a weighting coefficient |
| `delta_mode: absolute` | Score-unit change: accuracy +0.02 is two percentage points |
| `delta_mode: relative` | Directed change divided by the absolute champion score; 0.02 means 2%, not two score units |
| `require_any_improvement` | Defaults true; at least one selected metric must strictly improve |
| `on_tie` | Defaults `keep_champion`; `candidate` is an explicit override when all selected scores tie and all rules pass |
| `on_no_champion` | `block`, or `candidate_if_qualified` after an explicit first-model acknowledgement |

For minimizing RMSE, improvement is `champion - candidate`, not the reverse.
The regression template requires a 2% RMSE reduction while tolerating at most
0.001 absolute loss in R2 and Spearman. A zero champion denominator blocks relative
comparison; use an absolute rule rather than an invented epsilon.

Available tabular metrics include `accuracy`, `auc_weighted`, `precision_weighted`,
`recall_weighted`, `f1_weighted`, `matthews_correlation`, `log_loss`, `rmse`, `mae`,
`mape`, `r2` and `spearman_correlation`, as appropriate to the task. AUC/log loss
require actual class-aligned probabilities; hard predictions are never converted
into pretend probabilities. Undefined metrics are omitted with availability
reasons. MAPE uses fractions, not percentages, and is undefined with zero actuals;
Spearman is undefined for constant ranks. Unsupported selected metrics block
selection rather than being ignored. The old screenshot's
`Matthews_promote_weight2` reference is a typo, not an accepted metric alias.
These metrics are not silently normalized to the legacy SDK v1 metric units.

Evaluation emits `comparison.json` alongside the existing metrics, Responsible AI
and quality-gate reports. Candidate and champion must have the same
factory/project/environment, use case, task, held-out data fingerprint, preparation
contract, row count and evaluator. Forecast fingerprints also include validation
history used during prediction. The model identity is content-bound, not a mutable
`latest` alias. Preserve the champion's evidence as a versioned artifact; when the
benchmark changes, explicitly re-evaluate both models against the new benchmark.
Do not compare historical scores from different test datasets or repeatedly tune
on the final test set. Unscoped old reports need re-evaluation, not fabricated tags.

```powershell
# Offline decision only: does not register, deploy, or change endpoint traffic.
python -m ml_model_factory compare-models --policy model-selection.json `
  --candidate outputs\candidate\comparison.json --champion outputs\champion\comparison.json `
  --output outputs\selection-decision.json

# Explicit first-model case; absolute quality and all selected metrics remain required.
python -m ml_model_factory compare-models --policy model-selection.json `
  --candidate outputs\candidate\comparison.json --no-champion `
  --output outputs\initial-selection.json
```

The decision is `candidate_wins`, `champion_kept`, or `blocked`, with each rule's
scores/delta/result and policy/evidence hashes. Keeping the champion is a valid
training outcome, not a failed training job. A blocked offline comparison exits 2.

SDK v2 registration can apply the **same** policy directly:

```python
from pathlib import Path
from ml_model_factory.azureml import register
from ml_model_factory.config import load_json

model_id = register(
    "completed-pipeline-job", load_json(Path("runtime.local.json")), "diabetes-classification",
    selection_policy=load_json(Path("model-selection.json")),
    champion_evaluation=load_json(Path(r"outputs\champion\comparison.json")),
    decision_path=Path(r"outputs\selection-decision.json"),
)
```

The equivalent CLI v2 route is:

```powershell
python scripts\azureml_cli.py --runtime runtime.local.json `
  --register-job completed-pipeline-job --model-name diabetes-classification `
  --selection-policy model-selection.json --champion-evaluation outputs\champion\comparison.json `
  --selection-output outputs\selection-decision.json
```

For an initial model, replace the champion argument with `no_champion=True` (SDK)
or `--no-champion` (CLI). Registration downloads the **actual completed job's**
report, checks its quality/metrics/model lineage, then compares; it never accepts
a disconnected candidate score file as registration authority.
Winners receive `selection_status=winner`, `selection_policy_sha256` and
`selection_evidence_sha256` tags while retaining `lifecycle_status=candidate`:
winning a comparison is **not deployment approval**. A rejected SDK registration
raises `ModelSelectionRejected` with its decision; CLI prints a kept-champion
decision without creating a model. No endpoint, registry champion alias, monitoring
schedule, or Dev/Stage/Prod promotion is changed by the comparison.

Selection is opt-in for compatibility: calls without a policy retain the existing
absolute-quality registration gate. AutoML vision remains blocked by the missing
evaluation adapter; adding selection does not make unsupported evaluation work.
The policy API is engine-neutral, but automatic registry gating here is wired to
Azure ML SDK/CLI v2, not the separate Databricks model-version registration helper.

### Submit and register

Run from the model-factory root after configuring its declared dependencies,
scenario JSON and a resolved runtime JSON. Runtime names existing resources;
rendering does not provision a workspace, compute or datastore.

```powershell
python -m ml_model_factory validate --scenario scenarios\titanic.json --runtime runtime.local.json
python -m ml_model_factory render --scenario scenarios\titanic.json --runtime runtime.local.json --mode automl --output generated\titanic-automl
```

Choose **one** submission route for a rendered job:

```powershell
# Python SDK v2 through the shared factory entry point:
python -m ml_model_factory submit --runtime runtime.local.json --job generated\titanic-automl\pipeline.yml

# Alternative CLI v2 entry point; do not also submit the same job above:
python scripts\azureml_cli.py --runtime runtime.local.json --job generated\titanic-automl\pipeline.yml
```

Use `--mode custom` for custom training. Render into a new empty directory.
Resolve standalone preparation/model placeholders before submitting; image
AutoML uses `job.yml`, not an evaluated end-to-end `pipeline.yml`.
Submission incurs compute charges.

Registration is explicit and requires a completed factory pipeline plus its
downloaded passing quality gate and matching lineage:

```powershell
python scripts\azureml_sdk.py --runtime runtime.local.json register --job-name <completed-pipeline-name> --model-name titanic-survival
```

The CLI v2 alternative uses the same gate and tag builder, then submits its model
definition with `az ml model create`:

```powershell
python scripts\azureml_cli.py --runtime runtime.local.json --register-job <completed-pipeline-name> --model-name titanic-survival
```

Do not substitute a raw model registration command that bypasses these checks.
Use the [factory guide](../../../usecase_code/50-ml-model-factory/readme.md)
for local lake execution, deployment helpers and Databricks job parameters.

## 5. Azure DevOps and GitHub Actions

Both providers call the same `scripts\ci.py` in the
[current MLOps template folder](../../../copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md).
Reuse the existing AI Factory self-hosted runner/agent, private connectivity and
authentication configuration. Preprovision dependencies; workflows do not install
tools or silently switch to a hosted runner.

| Action | Behavior |
| --- | --- |
| `validate` | Offline configuration and contract validation; no Azure login or submission |
| `ingest` | Explicit Kaggle download; credentials stay in secret providers, rules are not accepted automatically |
| `train` | Fresh bundle, CLI v2 submission, bounded polling, optional winning-model selection, gated registration |
| `deploy` | Separate action with immutable model ID, target, serving kind and an approved environment |

Azure ML job success is normally `Completed`; failed, canceled, unknown or missing
statuses must not produce a success receipt. A timeout does not cancel the cloud
job automatically. Inspect its recorded job ID before retrying.

Enable the shared selection gate through environment-specific runtime JSON:

```json
{
  "model_selection": {
    "policy": "..\\..\\aifactory-usecase-code\\50-ml-model-factory\\model-selection.json",
    "champion_evaluation": "champions\\diabetes\\v3\\comparison.json"
  }
}
```

Merge this object with existing runtime settings, not as a replacement runtime.
Paths resolve beside the original runtime JSON; this example assumes orange's
`aifactory\ml-model-factory` configuration folder. Both CI providers use the same
settings and existing runner. For the first model, explicitly replace
`champion_evaluation` with `"no_champion": true`; a missing file never implies
bootstrap. Direct SDK/CLI registration uses the explicit policy arguments shown
above and refuses to silently ignore a runtime that requests selection.

CI keeps `training-status.json`, `selection-decision.json` and, when reached,
`registration-selection-decision.json` as audit artifacts. A kept champion
finishes successfully **without** `registered-model.json`; a blocked comparison
fails without registering. Workflow artifact steps handle both cases and clear
stale receipts before authentication so an earlier run cannot masquerade as the
current result.

When `runtime.lake` is enabled, CI generates a fresh execution ID without rewriting
the source runtime or snapshot ID. Azure preparation uses a run-scoped working
area; direct output URI bindings do not provide immutable storage locks.
Shared snapshot publication remains explicit.

Azure DevOps uses configured service connections; GitHub uses configured workload
identity federation. Required reviewers and protected environments must be set up
separately: an environment name alone is not an approval policy.
There is no automatic production-promotion stage.

## 6. Responsible AI and validation evidence

Every implemented evaluation route records task-appropriate diagnostics and
limitations. Local reports include held-out errors, relevant cohorts and
explanations where applicable; vision and forecasting use their own task metrics.
These reports are not automatically Azure Responsible AI dashboards.

Compatible custom tabular models also have a separate optional `rai-pipeline.yml`
using Azure Responsible AI components. Review model-flavor, environment and
component compatibility before submission; do not claim universal dashboard support.

Validation must distinguish:

| Evidence | Meaning |
| --- | --- |
| Real local lifecycle | Actual preparation, custom fitting, MLflow reload, inference and feedback on local data |
| Contract/service simulation | SDK/CLI schemas, ADF parameters and CI/registration/deployment decisions with service boundaries simulated |
| Live cloud integration | Actual jobs, model registrations and endpoint responses under the intended identities |

The test suites cover seven task types, three serving-path variants, custom/AutoML
definitions, both CI providers, ADF initial/delta bindings and rejected flows.
Selecting a serving path in a local test does not run an online endpoint or
streaming engine. Generated fixtures and simulated Kaggle downloads are explicitly
distinguished from real Kaggle data.

Run the combined suite from the model-factory root:

```powershell
python -m pytest tests ..\..\copy_my_subfolders_to_my_grandparent\mlops\03_mlops_2026-09\tests ..\..\copy_my_subfolders_to_my_grandparent\dataops\azure-datafactory\tests --junitxml=outputs\validation\lifecycle-results.xml -q
```

At the September 11, 2026 project snapshot, real local Kaggle classification,
regression and forecasting runs had completed. Full live cloud validation remained
incomplete: AKS recovery failed on the subscription feature
`Microsoft.Network/AllowBringYourOwnPublicIpAddress`, and the platform retry had
not completed. This does not invalidate local results, but neither do local
results establish cloud deployment success.

## 7. Monitoring ML: data drift and labeled concept-change signals

The Config Wizard's **Monitoring - ML** view consumes the shared
`aifactory.monitoring/v1` contract from both
[`50-ml-model-factory`](../../../usecase_code/50-ml-model-factory/readme.md#data-and-concept-drift-monitoring)
and [`40-agent-factory`](../../../usecase_code/40-agent-factory/readme.md#offline-monitoring-ml-reports).
Reports and model-version summary tags are isolated by factory, project, environment
and model/agent version. Dev/Stage/Prod are displayed independently; the wire value
for Stage is `test`.

Data drift compares feature distributions and missingness. The concept-change
indicator measures degradation against observed labels for the same model version;
it is not proof of conditional concept drift or a prediction of future problems.
Without enough labels it is unknown/insufficient, never implicitly healthy.
Image statistics can monitor input shifts; object detection, multilabel and
segmentation performance need separate annotation-aware monitoring adapters.

Compact `mon_*` tags expose statuses, observation time, expiry, model version and
an optional immutable report link. Full feature/performance/agent metrics remain
in the report. The UI must surface expired, missing, inaccessible or mismatched
reports instead of substituting a healthy status.

The model factory supplies local `monitor`, preview-first `monitor-publish`, and
Azure ML v2 job/schedule definitions. Enable publication/scheduling only after
configuring data-window production, baseline data, label feedback, existing
storage, registered models and managed-identity permissions. No live monitoring
schedule or Azure tag update is implied by the availability of these templates.

Agent monitoring reports describe recorded checks and numeric aggregates; they
do not claim agent data/concept drift. Raw prompts, responses and secrets must
not be placed into monitoring reports.

## 8. Legacy ESML workflows

Older ESML notebook flows and
[`02_cicd-ado-gha_mlops`](../../../copy_my_subfolders_to_my_grandparent/mlops/02_cicd-ado-gha_mlops/azure_devops)
remain legacy references. Their `AutoMLStep`, `DatabricksStep` and published-pipeline
patterns are not the implementation contract for this SDK/CLI v2 model factory.
Do not mix the old execution APIs or lake paths into new templates without an
explicit migration plan.

Related guidance: [supported use cases](32-use_cases-where_to_start.md),
[legacy SDK/ESML setup](33-install-azureml-sdk-v1+v2.md),
[data onboarding](34-datalake-onboard-data.md), and [DataOps](36-dataops.md).
