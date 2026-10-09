# ML model factory

**Purpose:** configure and run reusable machine-learning examples without editing shared accelerator code.
**Ownership:** `user-config` and project copies of examples are user-editable; `accelerator` is maintainer-owned; `data/out` and `ml-environment` contain generated artifacts.
**Status:** 8/105 implementations are **Tested and works** and 97/105 are **Impl TBA** in the Azure matrix recorded on 2026-10-08 to 2026-10-09. Templates exist for 124 of 126 catalog leaves, but a template is not proof of a working deployment. **Impl TBA** includes failed implementations and routes not run because of dataset, quota or private-connectivity prerequisites; see [Azure test status](#azure-test-status).

## Folder layout

```text
50-ml-model-factory\
├── .venv\                              Generated Python environment; stays at root
├── user-config\                        User-editable project configuration
│   ├── model\                          Model behavior and quality policy
│   │   ├── scenarios\                  Shared dataset/features/target/split definitions
│   │   ├── model-selection.json         Candidate/champion comparison rules
│   │   ├── monitoring.example.json      Monitoring configuration template
│   │   └── environments\                Optional custom dependency overrides
│   ├── databricks\                      Customer Databricks configuration
│   │   ├── job-template.json            Existing cluster/notebook/data references
│   │   ├── inference-settings.example.json  Batch/online/streaming task settings
│   │   └── azureml-step.example.json    Azure ML pipeline Databricks-step settings
│   ├── esml-rollout.example.json        ESML pipeline-factory scenario bindings
│   ├── storage-selection.example.json   Common or project storage selection
│   └── lake.example.json                Lake layout configuration template
├── usecase-type\                        User-facing examples by inference pattern
│   ├── batch\                           Scheduled/on-demand bulk scoring to storage
│   ├── online\                          Low-latency request/response inference
│   └── streaming\                       Continuous or micro-batch event processing
├── data\                                Local data, not Azure storage
│   ├── in\                              Raw source datasets
│   │   └── lake-data\                   Raw lake landing imports only
│   └── out\                             Processed datasets
│       └── lake-data\                   Complete local lake releases and provenance
├── ml-environment\                      Generated execution/development artifacts
│   ├── outputs\                         Models, reports, rendered jobs and receipts
│   ├── mlruns\                          Local MLflow tracking
│   ├── .pytest_cache\                    Pytest cache; created on demand
│   └── *.egg-info\                       Generated package metadata
└── accelerator\                         Maintainer-owned shared implementation
    ├── src\                             Importable Python source
    │   └── ml_model_factory\            Shared data/training/evaluation/serving engine
    ├── scripts\                         SDK/CLI and pipeline execution entry points
    ├── environments\                    Maintained dependency specifications
    ├── databricks\                      Shared parameter-driven backend notebooks
    ├── schemas\                         Configuration/report schema contracts
    └── tests\                           Automated accelerator and integration tests
        └── fixtures\                    Small, non-production test inputs
```

`pyproject.toml`, `setup.cfg`, this guide and ignore rules stay at the project root. Install from that root; the Python import remains `ml_model_factory`. `setup.cfg` directs generated package metadata into `ml-environment`; packaging tooling owns those files.

An implementation is `usecase-type\<usecase_type>\<problem_type>\<tech_stack>`. The three dimensions are:

- Use-case type: `batch`, `online`, `streaming`.
- Problem type: `classification`, `computer-vision`, `regression`, `timeseries-forecasting`. Computer vision expands into `multi-class`, `multi-label`, `object-detection`, and `instance-segmentation`.
- Tech stack: `azure-automl`, `azureml-pipeline`, `databricks-azureml-pipeline-step`, `databricks-notebook`, `notebook`. Azure ML pipeline leaves use the ESML pipeline factory for tabular tasks.

The `azure-automl` stack has two variants: `notebook` and `azureml-pipeline-with-automl-step`. They are separate catalog leaves, not additional tech stacks. An AutoML implementation is **Tested and works** only when **both variants** pass.

The catalog contains **12 use cases** (3 x 4), **60 combinations** (3 x 4 x 5), **105 implementations** (3 x 7 expanded problem rows x 5), **126 catalog leaves** (AutoML variants split), and **192 notebooks**. Both streaming forecasting AutoML leaves are unsupported and have no runnable notebooks. From this root, list the source-of-truth catalog with `.\.venv\Scripts\python.exe -m ml_model_factory usecases`.

Example implementation paths:

```text
usecase-type\batch\classification\azure-automl
usecase-type\batch\classification\databricks-azureml-pipeline-step
usecase-type\online\classification\azureml-pipeline
usecase-type\streaming\regression\databricks-notebook
```

Every leaf README states its route, prerequisites and limitations; see [use-case examples](#use-case-examples-and-shared-inference-engines).

## Azure test status

Test dates: **2026-10-08 to 2026-10-09**. Tested factory source: **`81ec23d6588923fe43e0d28935c92602e5397fe1`**; infrastructure prerequisite correction: **`940b1b48`**. This table is generated from the consumer's `matrix-results.json`: **8 Tested and works**, **97 Impl TBA**, no pending classifications. Customer resource identifiers, requests and result receipts remain in the consumer repository.

**Tested and works** means a registered, quality-gated model produced the required lake predictions; any endpoint route must also have a completed invocation. Online additionally requires a successful private endpoint invocation with matching contract-test predictions (or ready, invoked Unity Catalog Model Serving for Databricks). Streaming additionally requires in-network Event Hubs production, the stack's consumer, verified outputs/checkpoints and an idempotent rerun.

Runs used reviewed runtime settings and pinned environments. These results do not certify production quality or every default dependency image. Diagnostic successes do not turn a failed example into a passing implementation. **Impl TBA** is a disposition, not a claim that every affected route has a code defect; footnotes distinguish failures from prerequisites that prevented a run.

| Use-case type | Problem type | azure-automl | azureml-pipeline | databricks-azureml-pipeline-step | databricks-notebook | notebook |
|---|---|---|---|---|---|---|
| batch | classification | Impl TBA[^automl-evaluation] | Tested and works | Impl TBA[^private-connectivity] | Impl TBA[^databricks-package] | Impl TBA[^batch-compute] |
| batch | computer-vision/multi-class | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] |
| batch | computer-vision/multi-label | Impl TBA[^gpu-quota] | Tested and works | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Tested and works |
| batch | computer-vision/object-detection | Impl TBA[^gpu-quota] | Tested and works | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Tested and works |
| batch | computer-vision/instance-segmentation | Impl TBA[^gpu-quota] | Impl TBA[^instance-segmentation-evaluation] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^instance-segmentation-evaluation] |
| batch | regression | Impl TBA[^automl-evaluation] | Tested and works | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^batch-compute] |
| batch | timeseries-forecasting | Impl TBA[^automl-forecast-timezone][^automl-evaluation] | Tested and works | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Tested and works |
| online | classification | Impl TBA[^private-connectivity][^automl-evaluation] | Impl TBA[^private-online] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-online] |
| online | computer-vision/multi-class | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] |
| online | computer-vision/multi-label | Impl TBA[^gpu-quota] | Impl TBA[^private-online] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-online] |
| online | computer-vision/object-detection | Impl TBA[^gpu-quota] | Impl TBA[^private-online] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-online] |
| online | computer-vision/instance-segmentation | Impl TBA[^gpu-quota] | Impl TBA[^instance-segmentation-evaluation] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^instance-segmentation-evaluation] |
| online | regression | Impl TBA[^private-connectivity][^automl-evaluation] | Impl TBA[^private-online] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-online] |
| online | timeseries-forecasting | Impl TBA[^automl-forecast-timezone][^automl-evaluation] | Impl TBA[^private-online-storage] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-online-storage] |
| streaming | classification | Impl TBA[^private-connectivity][^automl-evaluation] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] |
| streaming | computer-vision/multi-class | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] | Impl TBA[^dataset-license] |
| streaming | computer-vision/multi-label | Impl TBA[^gpu-quota] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] |
| streaming | computer-vision/object-detection | Impl TBA[^gpu-quota] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] |
| streaming | computer-vision/instance-segmentation | Impl TBA[^gpu-quota] | Impl TBA[^instance-segmentation-evaluation] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^instance-segmentation-evaluation] |
| streaming | regression | Impl TBA[^private-connectivity][^automl-evaluation] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] |
| streaming | timeseries-forecasting | Impl TBA[^unsupported-stream-automl] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] | Impl TBA[^private-connectivity] |

[^dataset-license]: Not run: the multi-class dataset is still in license review and no other approved multi-class scenario was available. Other gated datasets were not substituted or automatically approved.
[^gpu-quota]: Not run: image AutoML requires GPU compute, but all applicable GPU families had zero quota in the test region.
[^unsupported-stream-automl]: Not implemented: both streaming AutoML forecasting variants are unsupported because forecasting requires observed history with each request.
[^automl-evaluation]: Training failed: AutoML notebook evaluation could not load the model (`azureml._common` missing in the shipped environment; `pkg_resources` missing in the curated environment). The tabular AutoML pipeline-step variant passed batch scoring where available, but an AutoML cell requires both variants to pass.
[^automl-forecast-timezone]: Training failed: the ESML AutoML forecasting evaluation raised a tz-naive versus tz-aware timestamp error.
[^instance-segmentation-evaluation]: Training failed: instance-segmentation evaluation raised `KeyError: 'map_per_class'`, reproduced in Azure and locally, before quality-gated registration.
[^batch-compute]: Batch deployment failed: the no-code MLflow route embedded `azureml:<compute>` in the compute ARM ID, so no endpoint invocation was possible.
[^private-online]: Online deployment failed: automatic scoring selected no-code MLflow, which the private-network endpoint rejected. A separately recorded custom-scoring diagnostic with a workspace-storage model copy returned HTTP 200 and matching contract-test predictions; the example remains Impl TBA.
[^private-online-storage]: Online deployment failed with an internal-server error for the lake-stored model. A separate custom-scoring diagnostic with a workspace-storage model copy returned HTTP 200 and matching predictions; the example remains Impl TBA.
[^databricks-package]: Training failed: installation of the factory wheel tried to resolve a dependency from a public package repository that the private workspace could not reach. The selected runtime's PyYAML version was below the declared minimum. Later retries were blocked by private client connectivity; no successful training or serving result is claimed.
[^private-connectivity]: Not run to completion: the test client's private-network connection was disconnected. Private DNS resolved correctly inside Azure, but private storage uploads and service calls from the client were blocked. This is a platform prerequisite, not an established defect in each affected implementation.

## Start here

1. Copy the generic templates into your orange project without overwriting customer edits.
2. Configure a scenario in `user-config\model\scenarios`; it is the single definition referenced by batch, online and streaming examples.
3. Configure project/storage settings under `user-config`, place local raw data in `data\in`, then choose an example under `usecase-type`.
4. Install declared dependencies in the root `.venv`; run existing local validation or render jobs before explicitly enabling a cloud operation.

```powershell
# From the 50-ml-model-factory root, using the intended Python environment:
python -m pip install -e ".[train,azure,dev]"
python -m ml_model_factory --help
python -m ml_model_factory validate --scenario user-config\model\scenarios\diabetes.json
python -m ml_model_factory storage-target --config user-config\runtime.local.json
python -m pytest
```

The runtime example path above is customer-owned: create it from the storage example plus your existing project settings. There is no default subscription, workspace, compute or cluster chosen for you. Review required fields and commands in [user-config/readme.md](user-config/readme.md). Keep credentials in the platform's identity/secret facilities, never in JSON, notebooks or Git.

## Ownership and customization

| Location | User action |
|---|---|
| `user-config\model\scenarios` | Configure data source, target, features, split, algorithms, budgets and quality thresholds. |
| `user-config\databricks` | Configure existing cluster, notebook, experiment and data references, pattern task settings and Azure ML Databricks-step settings; review all placeholders. |
| `user-config\esml-rollout.example.json` | Copy to `esml-rollout.local.json` and add a reviewed source binding per scenario for ESML pipeline-factory leaves. |
| `user-config\model\environments` | Add a reviewed dependency override only when required; normally select a pinned tested environment reference. |
| `usecase-type` | Run or adapt thin project examples; reuse shared engines rather than copying their internals. |
| `accelerator` | Maintainer changes only: implementation, wrappers, schemas, default dependencies and tests. |
| `data\in` / `data\out` | Supply raw inputs / inspect generated processed datasets. |
| `ml-environment` | Inspect generated models, reports and tracking; do not use artifacts as configuration. |

Generic examples belong in purple; customer-specific copies belong in orange. Scenario validation rejects invalid feature/target combinations; renderers validate budgets and data bindings before submission. Dataset licensing and vision prerequisites are explicit gates, not automatic approvals.

## Use-case examples and shared inference engines

The [use-case tree](usecase-type/readme.md) has one generated notebook per supported leaf and
configured scenario (192 notebooks for 124 of 126 leaves). Notebooks only orchestrate shared
engines and keep every switch `False` until you opt in. AutoML forecasting is not offered for
streaming because `forecast()` needs observed history with each request; use the custom
seasonal-naive streaming example or AutoML batch/online scoring with explicit history.

| Need | Shared command or component |
|---|---|
| Demo requests without labels | `sample-requests` writes `requests.parquet`, `labels.parquet` (held-out truth), `events.jsonl`, `online-request.json` and forecasting `history.parquet` |
| Batch scoring | `score` locally; `serving-render/deploy/invoke --kind batch` (no-code batch endpoint or factory scoring job); ESML `GOLD_INFERENCE`; Databricks `batch-score` |
| Online serving | `online-test` runs the Azure ML scoring entry point in-process; `serving-render/deploy/invoke/delete --kind online`; Databricks `register-serve` (Unity Catalog + Model Serving) |
| Streaming | `stream-score` micro-batches (JSONL or Event Hubs with Azure AD identity, idempotent batches, checkpoints, quarantine); `stream-job` scheduled Azure ML micro-batch jobs; Databricks `stream-score` |
| Azure ML pipelines | `render` (custom/AutoML, gated AutoML images with lake binding) and the ESML pipeline factory via `user-config/esml-rollout.example.json` |
| Databricks | `databricks-job render/create/run` (multi-task jobs) and `databricks-pipeline render` (Azure ML steps running single Databricks tasks) |

```powershell
python -m ml_model_factory usecases --pattern online --task-folder classification
python -m ml_model_factory usecase-examples            # check generated notebooks/READMEs
python -m ml_model_factory sample-requests --scenario user-config\model\scenarios\diabetes.json `
  --prepared data\out\diabetes\online-custom\prepared --output ml-environment\outputs\diabetes\online-custom\online\requests
python -m ml_model_factory online-test --scenario user-config\model\scenarios\diabetes.json `
  --model ml-environment\outputs\diabetes\online-custom\model `
  --request ml-environment\outputs\diabetes\online-custom\online\requests\online-request.json
```

Commands that change Azure or Databricks resources preview by default and require
`--execute`. Endpoint, schedule and streaming costs continue until you delete or stop them.

## Local-data migration notes

The former `data\<scenario>` sources are now under `data\in\<scenario>`. New notebook preparation writes to `data\out`, while models/reports go to `ml-environment\outputs`. Existing generated run bundles are preserved byte-for-byte, including their historical absolute-path metadata.

The former `lake-data` is now `data\out\lake-data`. Its historical releases mix raw landing, refined data and provenance, so they remain intact to preserve manifest references. Only original landing files are also exposed under `data\in\lake-data`; the complete lake is not duplicated. The redundant top-level forecasting documentation has been consolidated into the batch forecasting branch.

The code supports local MLflow storage under `ml-environment\mlruns` when configured. Old MLflow metadata may still reference the original artifact location; use recorded files directly or an explicit reviewed import rather than silently rewriting run history.

## Choose common or project data storage

Set `use_common_datalake_storage` to the JSON boolean `true` for the common
datalake, or `false` for the data account in the project resource group (not
local disk and not the AML workspace's artifact account). Merge
[`storage-selection.example.json`](user-config/storage-selection.example.json) into the
project discovery JSON, runtime JSON, or standalone lake configuration:

```json
{
  "use_common_datalake_storage": false,
  "storage_targets": {
    "common": {
      "account_name": "examplecommonlake",
      "resource_group": "example-common-dev",
      "container": "lake3",
      "datastore": "esml_shared_lake"
    },
    "project": {
      "account_name": "exampleprojectdata",
      "resource_group": "example-project001-dev",
      "container": "ml-model-factory",
      "datastore": "ml_model_factory"
    }
  }
}
```

Use actual, existing accounts and identity-based AML datastores. No selection
is made by taking the first account in a resource group; the older `mrvel`
account must not be substituted for the configured common account.
Resource-group checks reject a project/common scope mismatch. Keep `resource_group`
as the project's AML group and optionally set `common_resource_group` explicitly.

All scenarios and batch/online/streaming templates share this resolver: Azure ML
SDK/CLI rendering, lake publication, Databricks lake bindings, monitoring and ADF
lake-bound run parameters use the selected account/container/datastore. Local
Kaggle source paths remain local. A configured data URI is retargeted only when
it belongs to one of the supplied profiles; unknown cloud paths and opaque data
asset references fail instead of silently reading another account. Prefer an
account-independent `input_path` object key when switching frequently.

```powershell
python -m ml_model_factory storage-target --config user-config\runtime.local.json
python -m ml_model_factory discover --project project.json --output user-config\runtime.local.json
```

Changing the flag requires re-rendering saved jobs/schedules. Submission refuses
a job still bound to the other datastore and checks the selected datastore's
actual account/container. Existing configurations without the flag retain their
previous explicit storage behavior. `"false"` is not accepted as a boolean.
This is configuration, **not data migration or resource provisioning**: copy or
publish the intended input release to the chosen location, and arrange its
private connectivity/RBAC/ACL access separately. Streaming checkpoints still need
a supported HNS/ABFS or UC-Volume backend; selecting a non-HNS project account
does not turn it into Gen2. Registered models, Foundry resources and compute stay
in the project resource group.

## Winning-model comparison

[`user-config\model\model-selection.json`](user-config/model/model-selection.json) defines the winning model with
per-task selected metrics, maximize/minimize direction, signed improvement
thresholds and absolute/relative comparison. All chosen metrics must pass; ties
keep the champion by default. Classification includes AUC, accuracy, F1 and MCC;
regression includes RMSE, R2 and Spearman; forecasting and all four vision tasks
have separate profiles.

```powershell
python -m ml_model_factory compare-models --policy user-config\model\model-selection.json `
  --candidate ml-environment\outputs\candidate\comparison.json --champion ml-environment\outputs\champion\comparison.json `
  --output ml-environment\outputs\selection-decision.json
```

Use `--no-champion` instead of `--champion` only for an explicit initial-model
decision. Reports must describe the same scoped held-out benchmark. Missing
metrics, probabilities, labels or compatible evaluation evidence cannot win.
The command never deploys or registers. Azure ML SDK/CLI v2 registration and
MLOps CI can apply this same opt-in gate before registry writes.

See [policy semantics, metric availability and SDK/CLI examples](../../documentation/v2/30-39/37-mlops.md#define-the-winning-model-in-json).

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
python -m ml_model_factory tags --scenario user-config\model\scenarios\diabetes.json --context user-config\runtime.local.json --engine azureml --mode automl

# SDK v2 registration after the completed pipeline's evaluation gate:
python accelerator\scripts\azureml_sdk.py --runtime user-config\runtime.local.json register --job-name <completed-pipeline> --model-name diabetes-classification

# Alternative: same gate/tag builder, followed by CLI v2 model creation:
python accelerator\scripts\azureml_cli.py --runtime user-config\runtime.local.json --register-job <completed-pipeline> --model-name diabetes-classification
```

Do not execute both registration alternatives for the same intended version.
Candidate registration is not automatic production promotion. Keep metrics and
Responsible AI details in evaluation artifacts, not a large tag collection.
Local tags are written into `factory.json` and MLflow `MLmodel` metadata before
publication; completed immutable runs are never edited in place.

Databricks training accepts `model_context` JSON/path alongside `lake_config`.
Import `accelerator\databricks\model_tags.py` with the notebook. Its separately invoked
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
python -m ml_model_factory monitor --scenario user-config\model\scenarios\diabetes.json `
  --context user-config\runtime.local.json --config monitoring.local.json `
  --reference reference.parquet --current current.parquet `
  --reference-outcomes reference-outcomes.parquet `
  --predictions current-predictions.parquet --labels observed-labels.parquet `
  --output ml-environment\outputs\monitoring\window-001
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
python -m ml_model_factory monitor-publish --report ml-environment\outputs\monitoring\window-001\report.json

# Explicit Azure write, only after reviewing target, identity, report and permissions:
python -m ml_model_factory monitor-publish --report ml-environment\outputs\monitoring\window-001\report.json `
  --runtime user-config\runtime.local.json --execute
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

Use the v2 monitoring job/schedule renderer in `accelerator\scripts\monitoring_job.py`.
For example, after resolving the three credential-free Azure data URIs:

```powershell
python accelerator\scripts\monitoring_job.py render --runtime user-config\runtime.local.json --scenario user-config\model\scenarios\diabetes.json `
  --config-uri <current-window-config-uri> --reference-uri <fixed-baseline-uri> `
  --current-uri <current-features-uri> --output ml-environment\outputs\monitoring-schedule --interval-hours 24
python accelerator\scripts\monitoring_job.py create --runtime user-config\runtime.local.json --schedule ml-environment\outputs\monitoring-schedule\schedule.yml
```

The second command previews by default; only `create --execute` or an explicit
`az ml schedule create` enables recurring jobs. Add `render --publish` only when
the compute identity may update the selected existing model version and write
the report container. Optional outcomes, predictions, labels and evaluation
metrics have matching `--*-uri` inputs. Each job downloads the supplied
current-window config; it never replaces old observation dates with its wall clock.

### Dev activation prerequisites

`accelerator\scripts\activate_monitoring.py` previews an idempotent, Dev-only control-plane setup:
an existing private project's `ml-model-factory` container, credentialless
`ml_model_factory` datastore, container-scoped compute/workspace data access, and a
workspace-scoped custom role limited to model-version metadata read/write.
It does not create jobs, registered models, inference endpoints or schedules.
It never changes firewalls, public access, networking or subscription features.

```powershell
python accelerator\scripts\activate_monitoring.py --runtime user-config\runtime.local.json `
  --storage-account <existing-project-storage2001> --output user-config\runtime-monitoring.local.json
# Add --execute only after approving the printed target and role assignments.
```

Existing conflicting roles, public containers or credential-bearing datastores
are not silently overwritten. The actual Azure-assigned custom-role ID is used;
container/role setup can be resumed after a partial failure. Control-plane setup
alone does not prove Blob data-plane connectivity. Use the configured private
network/runner for data uploads and training, and sign into the selected tenant.
Do not enable recurring jobs until registered model versions and truthful current
observation inputs exist. Validation traffic must be labelled as validation,
not production monitoring.
Recurring jobs must read a current-window configuration and data supplied by DataOps,
and keep the reference baseline fixed. The renderer does not deploy schedules by
default. Model-tag publication must be explicitly enabled and use an authorized
managed identity. Updating tags, uploading reports and scheduling Azure jobs incur
external side effects; they are not performed by unit tests or local report generation.
