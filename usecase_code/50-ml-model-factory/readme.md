# ML MODEL FACTORY

# How is the folder structure of these AI Factory ML templates ordered
Evertyihng are generic templates. Not hardcoded examples. You can simply change to your data, and it will work - or prefferlby use the usecase_code\40-agent-factory to build ML-models from these templates.

- SPEED: There are 3 categories of use cases: Batch, Online, Streaming
- TYPE: Under each category, such as "Batch", we haeve different use case cateogories
    - classification (tabular data)
    - regression (tabular data)
    - timeseries-forecasting (tabular data)
    - computer-vision (image data)
    - purposely not there: TEXT, VIDEO, SPEECH, since todays LLMs takes care of that.
- TECHNOLOGY (IDE): Each usecase of speed and type you can pick differnt technology of your choice
    - azure-automl: Azure Machine Learning AutoML
    - azureml-pipeline: Azure Machine Learning Pipeline
        - both via Python SDK v2, and CLI v2
    - databricks-azureml-pipeline-step: Azure Machine Learning Pipeline step for Databricks Spark notebook called in Azure ML
    - databricks-notebook: Databricks spar notebook
    - notebook: Jupyter notebook in Python

## Batch, Online or Streaming use cases
- Batch use cases, meaning ml/dl-models deployed and served on Azure Machine Learning batch pipelines, or Databricks batch processing. Using Azure datafactory to load multiple rows from storage to a pipeline that does inferehces on all rows, and saves the result back to the stoage account.The compute is not up at start, but spins up a cluster that processes the data, then goes down again.
- Online, meaning ml- or dl-models served on AKS or ContainerApps, or Azure ML Managed Online Endpoints, or Databricks equivalent that also have scale to zero cluster. Where a user or consuming applicaiton can call pass some data to a REST endpoint, and get a REST response back, in near real time. The compute is always up-and running, hot. 
- Streaming, meaning models served via Azure Databricks strucured streadming or Azure Stream analtyics, both via Azure Eventhubs. The results are near real time, and can also be save to storage. 


## You are an Enteprise Scale AI Factory Machine learning model developer

Focus on using Azure machine learning AutoML, but also Databricks examples. 

Machine learning models you should create will be scenarios (see Kaggle data) of simple examples of
- classification, such as the "Youwld you surviced Titanic or not" with titanic.parquet data
- regression, such as "risk of diabetes" or "risk of customer churn"
- forecasting, such as "sales forecasting"  of orange juice, https://github.com/Azure/azureml-examples/tree/main/sdk/python/jobs/automl-standalone-jobs/automl-forecasting-orange-juice-sales
- time-series foreacting: 
- computer vision, such as: Multi-class image classification, Multi-label image classificaiton, object detectio, instance segmentaiton (all are supported in AutoML)

Have both examples using AutoML, and without. AutoML v2, docs: https://learn.microsoft.com/en-us/azure/machine-learning/concept-automated-ml?view=azureml-api-2

Create both Jyptuer notebook examples, Azure ML pipelines with Python, and with the CLI. 
Here are some AutoML notebooks: https://github.com/Azure/azureml-examples/tree/main/sdk/python/jobs/automl-standalone-jobs

Use only Azure machine learning V2 examples. 
https://learn.microsoft.com/en-us/azure/machine-learning/?view=azureml-api-2
Create each example with Python SDK, and with CLI v2. 
Docs: https://learn.microsoft.com/en-us/azure/machine-learning/how-to-train-model?view=azureml-api-2&tabs=python

Use Responsible AI tooling, on each model scenario: https://learn.microsoft.com/en-us/azure/machine-learning/concept-responsible-ai?view=azureml-api-2

## Model identity and lake-aligned tags

The shared `ml_model_factory.tags` module produces string tags for local MLflow
artifacts, Azure ML SDK/CLI v2 model registration, and Databricks model versions.
It uses the new `mlops/v1` storage design; it does not run the legacy lake ZIP
initializer or rename existing directories.

For the orange target, set `aifactory: spider-001` in project configuration.
Discovery writes `aifactory`, `project: "001"` and `environment_name: dev` into
runtime JSON. The model tags use `environment: dev`; runtime `environment` remains
reserved for an Azure ML environment asset such as `azureml:training-runtime:3`.

Tags include factory/project/environment, training origin, use case, task type,
training engine/mode, and available dataset/snapshot/run IDs. Lake tags must agree
with the actual `project001/environments/dev` and use-case/data/run keys. Conflicting
identities are rejected; cloud submission and registry writes require complete scope. Exploratory
training can omit unavailable scope, but never invents it.

```powershell
# Preview only; no model or registry writes:
python -m ml_model_factory tags --scenario scenarios\diabetes.json --context runtime.local.json --engine azureml --mode automl

# SDK v2 registration after the completed pipeline's evaluation gate:
python scripts\azureml_sdk.py --runtime runtime.local.json register --job-name <completed-pipeline> --model-name diabetes-classification

# Alternative: same gate/tag builder, followed by CLI v2 model creation:
python scripts\azureml_cli.py --runtime runtime.local.json --register-job <completed-pipeline> --model-name diabetes-classification
```

Do not execute both registration alternatives for the same intended version.
Candidate registration is not automatic production promotion. Keep metrics and
Responsible AI details in evaluation artifacts, not a large tag collection.
Local tags are written into `factory.json` and MLflow `MLmodel` metadata before
publication; completed immutable runs are never edited in place.

Databricks training accepts `model_context` JSON/path alongside `lake_config`.
Import `databricks/model_tags.py` with the notebook. Its separately invoked
`register_evaluated` helper verifies finished-run status, quality gate and model
metadata before creating tagged registry versions. The Azure ML Databricks
component accepts an optional JSON-file `model_context` input and forwards only
factory/project/environment identity.

Detailed guides:
[MLOps and tags](../../documentation/v2/30-39/37-mlops.md#model-identity-tags-one-small-contract),
[DataOps](../../documentation/v2/30-39/36-dataops.md),
[lake design](../../documentation/v2/30-39/34-datalake-onboard-data.md).

## Data and concept-drift monitoring

`ml_model_factory.monitoring` compares explicit observed reference/current windows.
It does not predict future drift, and distribution drift is not proof that a
model has become inaccurate.

| Signal | Method | Required evidence |
| --- | --- | --- |
| Numeric data drift | Reference-quantile Population Stability Index (PSI), fixed additive smoothing | Comparable numeric features and enough rows |
| Categorical data drift | Jensen-Shannon divergence over reference categories, plus unseen values | Comparable categorical features |
| Data quality | Change in missing-value fraction | Reference and current observations |
| Classification concept signal | Increase in labeled error rate, bootstrap interval | Same model version, disjoint reference/current request IDs, observed outcomes |
| Regression/forecasting concept signal | Increase in normalized MAE, with MAE/RMSE/R2 details | Same-model predictions and observed continuous targets |
| Vision data drift | Explicit fixed features/embeddings or `image_statistics: true` | Comparable representations; image statistics use color/dimensions, not semantic embeddings |
| Vision concept signal | Multi-class label/prediction comparison only | Other vision tasks need task-specific matched annotation adapters and report `not_supported` |

The concept signal is **observed performance degradation**, not mathematical proof
of a change in `P(y|x)`. Its bootstrap assumes independent observations; correlated
time series need domain-specific block/bootstrap analysis. Thresholds are configurable
operational heuristics, not universal guarantees. A lower warning threshold can
highlight an observed change before the drift threshold is crossed; it is not a forecast.

Create a private config from `monitoring.example.json`, replacing its model version
and timestamp windows with actual observed windows. Default feature selection uses
scenario features; images require explicit `features` or `image_statistics`.
Reference data must remain fixed for the comparison.

```powershell
python -m ml_model_factory monitor --scenario scenarios\diabetes.json `
  --context runtime.local.json --config monitoring.local.json `
  --reference reference.parquet --current current.parquet `
  --reference-outcomes reference-outcomes.parquet `
  --predictions current-predictions.parquet --labels observed-labels.parquet `
  --output outputs\monitoring\window-001
```

Reference outcomes contain `request_id`, `actual`, `prediction`, `model_version`.
Current predictions contain `request_id`, `prediction`, `model_version`.
Observed labels contain `request_id`, the scenario's target column, and `observed_at`.
Requests must match the exact current set, IDs must be unique, baseline/current IDs
must not overlap, and both sets of predictions must name the monitored model version.
Do not fabricate outcomes from model predictions. Omit outcome inputs when labels
have not arrived: the concept signal will be `unknown`, not healthy.

The command writes bounded `report.json` and compact `tags.json`. Reports expose
every calculated feature/performance metric and limitations, without raw rows.
Use `--evaluation-metrics <metrics.json>` to include all numeric model-evaluation
metrics as `evaluation_reference.*`; these are reference artifact values, not
claims about current-window health.
Statuses are `healthy`, `warning`, `drift`, `insufficient_data`, `not_supported`,
`stale`, or `unknown`. Expiration is based on the observation window end, not
when someone regenerates the report. Reusing old inputs cannot make them fresh.

### Config Wizard contract and model tags

Both this factory and `40-agent-factory` export `aifactory.monitoring/v1`:
scope (`aifactory`, `project`, `environment`), subject kind/name/version/task,
generation/window/expiry timestamps, summary states, metric records, details and
limitations. Wire environments are `dev`, `test`, `prod`; the Config Wizard displays
`test` as **Stage**.

Summary model tags are `mon_schema`, `mon_source`, `mon_kind`, `mon_subject_version`,
`mon_status`, `mon_data_drift`, `mon_concept_drift`, `mon_checked_at`,
`mon_window_end`, `mon_expires_at`, and optional score/report-URI fields.
Full metrics remain in the JSON report; the tags are not a substitute for it.
Data scores from different metric families are not directly comparable.

```powershell
# Preview only:
python -m ml_model_factory monitor-publish --report outputs\monitoring\window-001\report.json

# Explicit Azure write, only after reviewing target, identity, report and permissions:
python -m ml_model_factory monitor-publish --report outputs\monitoring\window-001\report.json `
  --runtime runtime.local.json --execute
```

Publication requires an existing registered model version and an existing project
Blob container from `runtime.lake`. It validates factory/project/environment/use case,
uploads immutable JSON under
`usecases/<use-case>/monitoring/models/<version>/reports/<sha256>.json`, then changes
only `mon_*` summary tags while preserving model identity and quality-gate metadata.
It rejects a report older than the published window. Use one publisher per model
version: the SDK tag update is read-modify-write, not a cross-service transaction
or a distributed lock. No container, identity, permission or schedule is created
by a preview.

Agent reports expose recorded counts and curated numeric aggregates, not fabricated
latency/tokens/cost. Agent data/concept drift is `not_supported`; agent-health checks
are a different signal. See the
[agent monitoring exporter](../40-agent-factory/readme.md#offline-monitoring-ml-reports).

### Scheduling

Use the v2 monitoring job/schedule renderer in `scripts\monitoring_job.py`.
For example, after resolving the three credential-free Azure data URIs:

```powershell
python scripts\monitoring_job.py render --runtime runtime.local.json --scenario scenarios\diabetes.json `
  --config-uri <current-window-config-uri> --reference-uri <fixed-baseline-uri> `
  --current-uri <current-features-uri> --output outputs\monitoring-schedule --interval-hours 24
python scripts\monitoring_job.py create --runtime runtime.local.json --schedule outputs\monitoring-schedule\schedule.yml
```

The second command previews by default; only `create --execute` or an explicit
`az ml schedule create` enables recurring jobs. Add `render --publish` only when
the compute identity may update the selected existing model version and write
the report container. Optional outcomes, predictions, labels and evaluation
metrics have matching `--*-uri` inputs. Each job downloads the supplied
current-window config; it never replaces old observation dates with its wall clock.
Recurring jobs must read a current-window configuration and data supplied by DataOps,
and keep the reference baseline fixed. The renderer does not deploy schedules by
default. Model-tag publication must be explicitly enabled and use an authorized
managed identity. Updating tags, uploading reports and scheduling Azure jobs incur
external side effects; they are not performed by unit tests or local report generation.
