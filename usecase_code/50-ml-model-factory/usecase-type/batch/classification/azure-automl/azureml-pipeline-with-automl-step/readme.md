# azureml pipeline with automl step

**Purpose:** Run scheduled or on-demand bulk inference and save predictions to storage. This branch covers `classification/azure-automl/azureml-pipeline-with-automl-step`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates over shared engines; cloud steps are explicit, charged operations behind switches that default to false and need the listed prerequisites.

[Scenario configuration](../../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../../accelerator/readme.md) | [Start here](../../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [churn-automl-pipeline.ipynb](churn-automl-pipeline.ipynb), [diabetes-automl-pipeline.ipynb](diabetes-automl-pipeline.ipynb), [titanic-automl-pipeline.ipynb](titanic-automl-pipeline.ipynb)

**Training:** ESML pipeline factory `IN_2_GOLD_TRAINING_AUTOML` (medallion lake, data assets, quality-gated evaluation) driven by AzureMLRollout receipts.

**Serving:** ESML GOLD_INFERENCE plan published as a pipeline-component batch endpoint, or submitted as a pipeline job, writing predictions to the lake.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- Install the factory extras `train` (plus `vision` for images, `azure` for Azure ML steps and `streaming` for Event Hubs consumers).
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- `user-config/esml-rollout.local.json` with a reviewed source binding for this scenario and pinned Azure ML environments; the ESML SDK is imported from `esml-v2` or azure-esml-sdk.
- AutoML models are scored in Azure with an AutoML-compatible environment, not in the local venv.

**Limitations**

- Pipeline-component batch invocation failed with an unresolved service URI error in the paused Dev rollout; submit the same inference plan as a pipeline job if invocation is unavailable.
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->
