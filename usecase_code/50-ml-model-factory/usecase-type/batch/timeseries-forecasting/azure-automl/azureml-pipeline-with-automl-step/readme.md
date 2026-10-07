# azureml pipeline with automl step

**Purpose:** Run scheduled or on-demand bulk inference and save predictions to storage. This branch covers `timeseries-forecasting/azure-automl/azureml-pipeline-with-automl-step`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates over shared engines; cloud steps are explicit, charged operations behind switches that default to false and need the listed prerequisites.

[Scenario configuration](../../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../../accelerator/readme.md) | [Start here](../../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [air-passengers-automl-pipeline.ipynb](air-passengers-automl-pipeline.ipynb), [delhi-weather-automl-pipeline.ipynb](delhi-weather-automl-pipeline.ipynb), [orangejuice-automl-pipeline.ipynb](orangejuice-automl-pipeline.ipynb)

**Training:** ESML pipeline factory `IN_2_GOLD_TRAINING_AUTOML` (medallion lake, data assets, quality-gated evaluation) driven by AzureMLRollout receipts.

**Serving:** ESML GOLD_INFERENCE plan published as a pipeline-component batch endpoint, or submitted as a pipeline job, writing predictions to the lake.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- Install the factory extras `train` (plus `vision` for images, `azure` for Azure ML steps and `streaming` for Event Hubs consumers).
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- `user-config/esml-rollout.local.json` with a reviewed source binding for this scenario and pinned Azure ML environments; the ESML SDK is imported from `esml-v2` or azure-esml-sdk.
- ESML AutoML forecast inference needs `inference_history_path` (observed history in the lake) in the scenario's reviewed rollout binding.
- AutoML models are scored in Azure with an AutoML-compatible environment, not in the local venv.

**Limitations**

- AutoML forecasting needs observed history with each scoring request (history.parquet or the request's history block).
- Pipeline-component batch invocation failed with an unresolved service URI error in the paused Dev rollout; submit the same inference plan as a pipeline job if invocation is unavailable.
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->

## References and examples

## Consolidated forecasting references

# Docs: AutoML via pipeline

https://learn.microsoft.com/en-us/azure/machine-learning/concept-automated-ml?view=azureml-api-2

## Azure ML SDK v2 AutoML


SDK v1 AutoMLStep/DatabricksStep APIs are not used. Use the maintained v2 components and wrappers in the accelerator.
