# azureml pipeline with automl step

**Purpose:** Serve low-latency request/response inference through an endpoint. This branch covers `timeseries-forecasting/azure-automl/azureml-pipeline-with-automl-step`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates over shared engines; cloud steps are explicit, charged operations behind switches that default to false and need the listed prerequisites.

[Scenario configuration](../../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../../accelerator/readme.md) | [Start here](../../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [air-passengers-automl-pipeline.ipynb](air-passengers-automl-pipeline.ipynb), [delhi-weather-automl-pipeline.ipynb](delhi-weather-automl-pipeline.ipynb), [orangejuice-automl-pipeline.ipynb](orangejuice-automl-pipeline.ipynb)

**Training:** ESML pipeline factory `IN_2_GOLD_TRAINING_AUTOML` (medallion lake, data assets, quality-gated evaluation) driven by AzureMLRollout receipts.

**Serving:** Azure ML managed online endpoint via `serving-render`, `serving-deploy` and `serving-invoke`.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- Install the factory extras `train` (plus `vision` for images, `azure` for Azure ML steps and `streaming` for Event Hubs consumers).
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- `user-config/esml-rollout.local.json` with a reviewed source binding for this scenario and pinned Azure ML environments; the ESML SDK is imported from `esml-v2` or azure-esml-sdk.
- ESML AutoML forecast inference needs `inference_history_path` (observed history in the lake) in the scenario's reviewed rollout binding.
- AutoML models are scored in Azure with an AutoML-compatible environment, not in the local venv.
- Endpoint quota; deployed endpoints bill while running, so delete or scale them to zero when done.

**Limitations**

- AutoML forecasting needs observed history with each scoring request (history.parquet or the request's history block).
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->
