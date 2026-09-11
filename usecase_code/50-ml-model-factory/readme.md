# Machine learning model factory

## How the AI Factory ML templates are organized
Everything in this folder is intended to be a reusable, generic template rather than a hardcoded, project-specific example. Adapt the configuration, data schema, features, labels, and preprocessing to your own dataset. Use `usecase_code\50-ml-model-factory` to build machine learning models from these templates.

- SERVING PATTERN: There are three categories of use cases: batch, online, and streaming.
- TYPE: Each serving pattern contains the following model categories:
    - classification (tabular data)
    - regression (tabular data)
    - timeseries-forecasting (tabular data)
    - computer-vision (image data)
    - Text, video, and speech scenarios are outside the scope of this factory.
- TECHNOLOGY: For each serving pattern and model type, choose an implementation technology:
    - azure-automl: Azure Machine Learning AutoML
    - azureml-pipeline: Azure Machine Learning pipeline jobs
        - Use Python SDK v2 and CLI v2 for both AutoML and custom training.
    - databricks-azureml-pipeline-step: Orchestrate an Azure Databricks job or Spark notebook from an Azure Machine Learning v2 command component using a supported Databricks Jobs API/SDK integration. Include authentication, completion polling, error propagation, and explicit data handoff. Do not use the SDK v1 DatabricksStep or assume that a native v2 equivalent exists.
    - databricks-notebook: Azure Databricks Spark notebooks
    - notebook: Jupyter notebook in Python

## Batch, online, and streaming use cases
- Batch: Run machine learning or deep learning inference through Azure Machine Learning batch endpoints, pipeline jobs, or Azure Databricks batch processing. Azure Data Factory orchestrates loading rows from storage, submitting an inference job, and persisting results to storage. Configure eligible compute to start on demand and scale down after processing.
- Online: Serve models through Azure Machine Learning managed online endpoints, AKS, Azure Container Apps, or Azure Databricks model serving. Applications send data to a REST endpoint and receive a near-real-time response. Keep capacity warm for predictable latency. Scale-to-zero support and cold-start behavior depend on the hosting platform and configuration; do not assume that every online hosting option supports scale to zero.
- Streaming: Process events from Azure Event Hubs using Azure Databricks Structured Streaming or Azure Stream Analytics with a supported inference integration. Produce near-real-time results and optionally persist them to storage. Streaming inference does not necessarily imply continuous model training.




## Enterprise Scale AI Factory machine learning model development

Prioritize Azure Machine Learning AutoML, then add non-AutoML training and Azure Databricks examples. Use Azure Machine Learning and Azure Databricks rather than Foundry for model training and serving.

Use Kaggle training data to create simple examples of these scenarios:
- Classification: Titanic survival prediction, "Would you have survived the Titanic?", using `titanic.parquet`. Convert the Kaggle source data to Parquet if necessary. Diabetes risk and customer churn with categorical labels are also classification tasks, even when the model returns probabilities.
- Regression: Predict a genuinely continuous target, such as a diabetes progression score or customer lifetime value, where an appropriate Kaggle dataset contains that target. Do not relabel a binary outcome as regression.
- Time-series forecasting: Orange juice sales forecasting and an additional demand, sales, or energy forecasting example. Configure the time column, series identifiers, frequency, forecast horizon, and chronological validation. Reference: https://github.com/Azure/azureml-examples/tree/main/sdk/python/jobs/automl-standalone-jobs/automl-forecasting-orange-juice-sales
- Computer vision: Multi-class image classification, multi-label image classification, object detection, and instance segmentation. All four task types are supported by AutoML. Select Kaggle datasets with suitable labels and annotations.

Record each Kaggle dataset's identifier, version, license, schema, and download instructions. Do not commit credentials or downloaded datasets. The orange juice example is an implementation reference, not an exception to the Kaggle training-data requirement. If a suitable Kaggle orange juice dataset cannot be found, report the gap and request approval before substituting data.

Diabetes examples are educational demonstrations, not clinically validated diagnostic or treatment tools.

Provide both AutoML and non-AutoML implementations for every scenario. AutoML v2 documentation: https://learn.microsoft.com/en-us/azure/machine-learning/concept-automated-ml?view=azureml-api-2

Create Jupyter notebooks and reusable Azure Machine Learning pipelines using Python SDK v2 and equivalent CLI v2 YAML and commands. Include data preparation, training, evaluation, Responsible AI assessment, model registration, and inference.
AutoML notebook examples: https://github.com/Azure/azureml-examples/tree/main/sdk/python/jobs/automl-standalone-jobs

Use only Azure Machine Learning v2 examples.
https://learn.microsoft.com/en-us/azure/machine-learning/?view=azureml-api-2
Create each Azure Machine Learning example with Python SDK v2 (`azure-ai-ml` and `azure.identity`) and CLI v2 (the Azure CLI `ml` extension). Do not use SDK v1, CLI v1, `azureml.core`, `PythonScriptStep`, or `DatabricksStep`. Databricks-native examples use supported Databricks tooling; their Azure Machine Learning integration must remain v2-only.
Documentation: https://learn.microsoft.com/en-us/azure/machine-learning/how-to-train-model?view=azureml-api-2&tabs=python

Use Responsible AI tooling for every model scenario. Use Azure Machine Learning Responsible AI dashboards, pipeline components, and scorecards where the task, model format, and environment are supported. Check current compatibility; do not assume that every component supports every AutoML, forecasting, or computer vision model. Where a component is unsupported, document the limitation and provide task-appropriate tooling for error analysis, relevant cohort metrics, explainability, robustness, and data-quality assessment. Record results with the model artifacts.
Documentation: https://learn.microsoft.com/en-us/azure/machine-learning/concept-responsible-ai?view=azureml-api-2
Component requirements and limitations: https://learn.microsoft.com/en-us/azure/machine-learning/how-to-responsible-ai-insights-sdk-cli?view=azureml-api-2

## Running the factory

Run commands from this template root or its instantiated consumer copy. Use an isolated Python environment; Python 3.10 is recommended when matching Azure AutoML runtime dependencies. The local custom-training code also supports newer Python versions listed in `pyproject.toml`. Azure jobs use their own explicitly defined environments.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[train,azure,kaggle,dev]"
.\.venv\Scripts\python.exe -m ml_model_factory --help
```

Install `.[vision]` for custom computer vision and `.[databricks]` for Databricks SDK integration. These optional dependencies are not needed for basic tabular preparation and training.

### Configuration and data

Scenario JSON files describe the task, source, schema, split, training budget, evaluation gates, and intended model name. `validate` checks configuration without contacting Azure or downloading data:

```powershell
python -m ml_model_factory validate --scenario scenarios\titanic.json
python -m ml_model_factory ingest --scenario scenarios\titanic.json --output data\titanic
python -m ml_model_factory prepare --scenario scenarios\titanic.json --input data\titanic\train.csv --output outputs\titanic\prepared
python -m ml_model_factory train --scenario scenarios\titanic.json --prepared outputs\titanic\prepared --model-output outputs\titanic\model
python -m ml_model_factory evaluate --scenario scenarios\titanic.json --prepared outputs\titanic\prepared --model outputs\titanic\model --output outputs\titanic\evaluation
```

Activate the virtual environment or use its Python executable for every command. Preparation requires an empty output directory, preserves a held-out test split, and writes Parquet and MLTable assets. Numerical tabular features are stored as floating-point columns so missing values have a consistent type; inference clients must follow the registered model's input schema.

`ingest` never accepts Kaggle terms on your behalf. Competition downloads require your own authenticated Kaggle account and accepted competition rules. Configure credentials through Kaggle's supported credential mechanism, not through scenario files. Dataset selections that require license review or a suitable source remain explicitly blocked; validation alone does not establish download rights.

The Titanic source is a Kaggle CSV; preparation creates `titanic.parquet`. Download hashes, dataset identifiers, split hashes, and row counts are recorded. Do not commit local `data`, `outputs`, `generated`, credentials, or downloaded model artifacts.

### Existing Azure resources

Keep the consumer project's settings outside the copied template tree. A project JSON file contains a `variables_file` path relative to that file, an `environment`, an explicit `resource_group`, and optional workspace/compute selections. `discover` reads the actual configuration and deployed resources:

```powershell
python -m ml_model_factory discover --project <project-settings.json> --output runtime.local.json
python -m ml_model_factory render --scenario scenarios\titanic.json --runtime runtime.local.json --output generated\titanic-automl --mode automl
python -m ml_model_factory submit --runtime runtime.local.json --job generated\titanic-automl\pipeline.yml
```

Before rendering, set `input_data` in the resolved runtime to the actual Kaggle training file or an authorized Azure data URI. Set GPU compute and task-specific settings before rendering image training. Discovery never enables services, creates compute, switches the global Azure subscription, or guesses which workspace to use. Missing or ambiguous resources are actionable errors.

SDK submissions default to `AzureCliCredential` bound to the configured tenant, not whichever tenant happens to be the CLI default. On an Azure host with an explicitly authorized identity, select `credential: "managed_identity"` and optionally `managed_identity_client_id`. There is no fallback from a failed managed identity to a developer account.

`render` writes Azure ML v2 YAML that can be submitted either with the SDK-backed `submit` command or directly with `az ml job create --file ... --subscription ... --resource-group ... --workspace-name ...`. Submissions incur charges. Do not submit the same rendered job with both methods unless two separate runs are intended.

### Consumer instantiation

```powershell
python -m ml_model_factory instantiate --destination <orange-repository>\aifactory-usecase-code\50-ml-model-factory
```

The copier excludes local datasets, runtime configuration, environments, and output artifacts. It records template hashes and refuses to overwrite consumer edits. It does not stage, commit, push, or deploy anything.

### Evaluation and execution status

Custom tabular models are saved in MLflow format. Evaluation produces metrics, held-out predictions, cohort/error analysis, permutation importance where applicable, and an explicit quality-gate result. A failed gate exits with an error after saving the diagnostic artifacts. These local reports are not presented as Azure Responsible AI dashboards.

Custom forecasting includes a seasonal-naive baseline. It does not claim to be a tuned AutoML forecasting model. Dataset-specific annotations, runtime compatibility, and hosting support must be checked for vision and forecasting paths.

An offline test or a generated notebook is not evidence of an Azure training run. Dataset access, resource deployment, training completion, model registration, and endpoint responses must each be established separately before describing a scenario as deployed.

### Databricks integration

`databricks\train.py` shares the tabular preparation/training/evaluation implementation and
logs the model and reports to MLflow. It supports small CSV/Parquet inputs from authorized
`wasbs://` Blob storage, `abfss://` storage, or a driver-accessible local/Volume path.
Remote reads require preconfigured cluster data access and have an explicit driver row budget.
`databricks\batch_score.py` and `stream_score.py` provide Spark batch and Event Hubs
Structured Streaming examples with their own widget contracts.

The reusable v2 component in
`batch\classification\databricks-azureml-pipeline-step\component.yml` works for any
configured tabular/forecasting scenario. Load it with `azure.ai.ml.load_component`, or
register it with `az ml component create --file ...` and reference it in a CLI v2 pipeline.
It invokes an existing Databricks job using explicit managed-identity authentication,
waits for completion, propagates failures, and writes the returned MLflow model URI and
run identifiers to its `result` output. It does not provision clusters or pretend that an
Azure ML mounted path is visible to Databricks. The managed identity must have Databricks
workspace/job permissions and private connectivity. Supply a stable idempotency token
when retrying the same logical request. The model URI is a cross-platform handoff, not
automatic registration of a Databricks model in Azure ML.

## Lake layout v1: projects, use cases, and the ML lifecycle

The legacy ESML lake is a useful reference, not a migration script for this factory.
The old `11-ESML-upload-lake-structure.sh` uploads an archive containing 3,927 entries,
including 342 Parquet files, Spark output markers, example dates, and active pointers.
It does not create ACLs despite its authentication prompt, and Blob prefixes are not
directory-level authorization boundaries. This factory does not run that script,
upload its sample contents, or rewrite any legacy `projects/` paths.

### What is retained and what changes

| ESML concept | Assessment and replacement |
| --- | --- |
| Project and model folders | Keep project ownership, but scope environment before data/use cases; datasets are shared within that scope rather than recopied under every model. |
| `train` versus `inference` | Keep them separate. A labeled training snapshot is not an inference request, and predictions are never fabricated labels. |
| `in`, `out`, `bad` | Define them precisely: inference requests, predictions, and quarantine references. Quarantine has reason codes, not just an empty `bad/` folder. |
| Bronze, silver, gold | Keep the progression but describe the actual validation/transformation. ADF binary copying into a folder does not make data silver. |
| Date-based partitions and `active` | Dates alone are not unique run IDs. Use explicit immutable source versions, snapshot IDs, run IDs and model versions; do not overwrite a latest data directory. |
| Model version `0` | Do not treat it as a mutable latest-model storage location. Pin a model version and bind it to the exact training artifact. |
| Train/Validate/Test gold splits | Use lowercase `train/validation/test` beneath a training snapshot. `environments/test` is a deployment environment, not the held-out test split. |
| Repeated source inputs | Store a source version once and reference it from use cases. Model/framework/AutoML choice belongs in metadata, not duplicate lake hierarchies. |
| Streaming run folders | Keep requests/results partitioned, but put checkpoints outside run and model-version folders so restarts and model rollouts do not reset offsets. |

The legacy Python consumers also depend on exact path casing and mutable bronze/silver
locations. A versioned namespace avoids breaking them. Any later legacy migration needs
an explicit source-to-destination inventory, permissions review, and checksum comparison;
changing path builders is not a data migration.

### Logical object-key layout

```text
mlops/v1/projects/project001/environments/dev/
  datasets/kaggle-titanic/
    versions/v1/
      landing/                         original source bytes
      bronze/                          parsed source records or image index
      silver/                          validated reusable source representation
      _SUCCESS.json                    immutable publication manifest
    quarantine/versions/v1/            rejected source references and reasons
  usecases/titanic/
    training/
      snapshots/s001/gold/
        train/                         data.parquet + MLTable, or image manifests
        validation/
        test/
      runs/r001/
        model/                         MLflow model and dependencies
        evaluation/                    metrics, predictions, RAI, quality gate
        lineage.json
        _SUCCESS.json
    models/m001/binding/               model version -> exact training artifact
    inference/batch/models/m001/runs/score001/
      in/                              unlabeled requests with request IDs
      gold/                            model-schema-compatible features
      out/                             predictions + request/model/run IDs
      lineage.json
      _SUCCESS.json
    quarantine/batch/models/m001/runs/score001/
    feedback/models/m001/inference-runs/score001/versions/f001/
    operations/streaming/titanic-scoring/versions/v1/checkpoints/
```

`LakeLayout` builds the same paths for classification, regression, forecasting, and all
four vision tasks. `batch`, `online`, and `streaming` describe serving, not three copies
of training data. Object keys use `/`; local Windows paths are constructed separately.
No empty directories, zero-byte marker files, sentinel dates, or example datasets are
uploaded to create the layout.

Use immutable identifiers without slashes or traversal syntax. `latest`, `active`,
`champion`, and `production` are not accepted as model versions. Source versions and
snapshot IDs can be reused only if their content and preparation contract match.
Every separate training or scoring execution needs a new run ID. For multiple models
in one use case, model-version identifiers must distinguish those exact artifacts.

The snapshot signature excludes model algorithms, AutoML search budgets, model names
and evaluation thresholds. Different model variants reuse the same source and gold
snapshot, but produce separate model/evaluation runs. Data-preparation changes
(features, typing, splits/groups, forecast horizon/frequency, image annotations or
image URIs) require a new snapshot. Older full-scenario signatures are compared
compatibly without changing the already-published snapshot.

### What the medallion stages actually do

The local tabular flow preserves the original bytes in landing, parses CSV/Parquet into
bronze, and validates a nonempty, uniquely named, Parquet-serializable source schema for
silver. Basic silver has no learned transformations and does not claim domain-specific
cleansing. Use-case-specific column checks, typing and split rules are applied before
publishing gold. Imputers, scalers and encoders are fitted on the training split only.

Images remain binary assets with indexes and annotations. Source silver metadata
explicitly states when task-specific annotation validation is still required; the vision
preparer validates images/annotations and disjoint hashes before gold publication.
Do not interpret a source folder name as proof that all vision checks have passed.

For repeated customers/patients/devices, set `split.group_column` to keep each entity in
exactly one tabular split. Without an entity key, the default random split cannot prove
entity independence. Forecasting uses ordered per-series windows, not random splitting.
No missing target is replaced with zero. Quarantine and late feedback live outside
immutable manifests so appending diagnostics/labels cannot silently change a source or run.

### Local execution

Copy `lake.example.json` to a private `lake.local.json`, set the project/environment,
dataset version, snapshot ID and run ID, then run:

```powershell
python -m ml_model_factory lake-plan --scenario scenarios\titanic.json --config lake.local.json
python -m ml_model_factory lake-train --scenario scenarios\titanic.json --config lake.local.json --root lake-data --input data\titanic\train.csv
python -m ml_model_factory lake-infer --scenario scenarios\titanic.json --config scoring.local.json --root lake-data --input requests.parquet --model <committed-training-run>\model
```

`lake-train` publishes source data and gold snapshots once, writes each model/evaluation
under its run, and writes `_SUCCESS.json` only after successful completion. Failed
preparation creates a quarantine reference; a failed quality gate retains diagnostic
reports but does not publish a model. All local publication paths are protected against
overwrite and traversal; source and model file hashes are verified on reuse.

`lake-infer` is a finite local scoring operation, not an online server or streaming
engine. It supports tabular/forecasting requests and all four exported vision models.
Tabular requests contain model features and a unique `request_id`, without the target.
Vision requests contain `request_id` and `image_base64`, without labels. Prediction
records retain IDs, model version and run ID for reliable feedback joins.

To record real observed outcomes, set `feedback_version` and `feedback_source`, then use
`lake-feedback` with the same scoring run's configuration and an input containing
`request_id`, the target label, and `observed_at`. It checks membership in the exact
inference run and marks feedback `training_eligible: false`. Human review and an explicit
new training snapshot are required; this is not automatic retraining on predictions.

### Azure and orchestration behavior

Add optional `lake` configuration to runtime JSON to enable SDK/CLI output bindings.
Azure job preparation writes to its unique training run's `prepared/` area. It does not
overwrite shared gold snapshots or claim that Azure job outputs are immutable merely
because they have versioned names. Shared snapshot publication remains explicit.
Models, evaluations and lineage use the same shared path contract. Existing runtime
files without `lake` retain their original behavior.

`lake-publish` previews a transfer by default. With explicit `--execute --tenant-id ...`,
it publishes an already committed source/snapshot/run to an **existing** Blob container:
data first, completion manifest last, no overwrites, and no directory/ACL creation.
It uses explicit token authentication. A failed upload leaves an uncommitted prefix;
consumers must require the matching completion manifest and hashes. It does not set
retention, legal holds, container permissions, private endpoints, or storage versioning.

The orange project's storage2001 account is non-HNS Blob storage. Do not substitute
`dfs`/ABFS paths or POSIX ACL assumptions. Configure credentialless Azure ML datastores,
Blob RBAC and private DNS for each execution identity. Shared dataset folders are a
logical reuse mechanism, not permission grants.

ADF raw-copy outputs land in landing, never falsely in silver. CI creates fresh run
identifiers. Databricks uses the same lineage/path builder; streaming query checkpoints
remain stable across run IDs and model versions, while incompatible schema/query
changes require a new pipeline version. Catalog table names and physical lake paths are
separate settings, not interchangeable strings.

The yellow repository is reference material only. Its tenant is scheduled for removal
on September 16, 2026. Inventory and migrate any required datasets, access grants,
identities, checkpoints and registrations before removal; no tenant data migration has
been performed by these changes.

### Lifecycle validation

Run the model-factory and orchestration tests together from this folder:

```powershell
python -m pytest tests ..\..\copy_my_subfolders_to_my_grandparent\mlops\03_mlops_2026-09\tests ..\..\copy_my_subfolders_to_my_grandparent\dataops\azure-datafactory\tests --junitxml=outputs\validation\lifecycle-results.xml -q
```

The suite distinguishes real local training/inference from service-boundary simulations
and definition checks. Generated fixtures do not establish live Kaggle access; mocked
Azure/ADF/Databricks calls do not establish cloud execution. Explicitly unsupported
task/serving combinations must fail their promotion path rather than generate success
receipts. Source corruption, failed gates, invalid inference/feedback and reused run IDs
are tested alongside successful lifecycles.
