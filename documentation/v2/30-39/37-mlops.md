# MLOps: Machine learning model factory

Use the [Machine learning model factory](../../../usecase_code/50-ml-model-factory/readme.md)
for configurable Kaggle-backed training, evaluation, registration and inference.
Azure Machine Learning is the primary engine, with **AutoML and custom training**.
Azure Databricks provides additional custom tabular/forecasting and Spark examples.
All Azure ML control-plane examples use **Python SDK v2 and CLI v2**.

Start with [data onboarding and lake design](34-datalake-onboard-data.md) and
[DataOps orchestration](36-dataops.md). Reusable CI templates are in
[`mlops/03_mlops_2026-09`](../../../copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md).

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
| `train` | Fresh bundle, CLI v2 submission, bounded status polling, evaluated-model registration |
| `deploy` | Separate action with immutable model ID, target, serving kind and an approved environment |

Azure ML job success is normally `Completed`; failed, canceled, unknown or missing
statuses must not produce a success receipt. A timeout does not cancel the cloud
job automatically. Inspect its recorded job ID before retrying.

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

## 7. Legacy ESML workflows

Older ESML notebook flows and
[`02_cicd-ado-gha_mlops`](../../../copy_my_subfolders_to_my_grandparent/mlops/02_cicd-ado-gha_mlops/azure_devops)
remain legacy references. Their `AutoMLStep`, `DatabricksStep` and published-pipeline
patterns are not the implementation contract for this SDK/CLI v2 model factory.
Do not mix the old execution APIs or lake paths into new templates without an
explicit migration plan.

Related guidance: [supported use cases](32-use_cases-where_to_start.md),
[legacy SDK/ESML setup](33-install-azureml-sdk-v1+v2.md),
[data onboarding](34-datalake-onboard-data.md), and [DataOps](36-dataops.md).
