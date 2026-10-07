# azureml pipeline

**Purpose:** Run scheduled or on-demand bulk inference and save predictions to storage. This branch covers `timeseries-forecasting/azureml-pipeline`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates over shared engines; cloud steps are explicit, charged operations behind switches that default to false and need the listed prerequisites.

[Scenario configuration](../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../accelerator/readme.md) | [Start here](../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [air-passengers-custom-pipeline.ipynb](air-passengers-custom-pipeline.ipynb), [delhi-weather-custom-pipeline.ipynb](delhi-weather-custom-pipeline.ipynb), [orangejuice-custom-pipeline.ipynb](orangejuice-custom-pipeline.ipynb)

**Training:** ESML pipeline factory `IN_2_GOLD_TRAINING_MANUAL` (medallion lake, data assets, quality-gated evaluation) driven by AzureMLRollout receipts.

**Serving:** ESML GOLD_INFERENCE plan published as a pipeline-component batch endpoint, or submitted as a pipeline job, writing predictions to the lake.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- Install the factory extras `train` (plus `vision` for images, `azure` for Azure ML steps and `streaming` for Event Hubs consumers).
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- `user-config/esml-rollout.local.json` with a reviewed source binding for this scenario and pinned Azure ML environments; the ESML SDK is imported from `esml-v2` or azure-esml-sdk.

**Limitations**

- The custom seasonal-naive baseline only forecasts timestamps inside its fitted horizon window.
- Pipeline-component batch invocation failed with an unresolved service URI error in the paused Dev rollout; submit the same inference plan as a pipeline job if invocation is unavailable.
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->

## References and examples

## Consolidated forecasting references

# docs Azure ML 

# Azure ML pipelines
https://learn.microsoft.com/en-us/azure/machine-learning/concept-ml-pipelines?view=azureml-api-2


## CLI v2
https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-component-pipelines-cli?view=azureml-api-2

## SDK v2

https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-component-pipeline-python?view=azureml-api-2


## Pipeline input and output
https://learn.microsoft.com/en-us/azure/machine-learning/how-to-manage-inputs-outputs-pipeline?view=azureml-api-2&tabs=cli

## Debug pipelines

https://learn.microsoft.com/en-us/azure/machine-learning/how-to-debug-pipeline-failure?view=azureml-api-2


https://learn.microsoft.com/en-us/azure/machine-learning/how-to-debug-pipeline-performance?view=azureml-api-2

https://learn.microsoft.com/en-us/azure/machine-learning/how-to-debug-pipeline-reuse-issues?view=azureml-api-2
