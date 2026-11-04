# notebook

**Purpose:** Run scheduled or on-demand bulk inference and save predictions to storage. This branch covers `timeseries-forecasting/azure-automl/notebook`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates over shared engines; cloud steps are explicit, charged operations behind switches that default to false and need the listed prerequisites.

[Scenario configuration](../../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../../accelerator/readme.md) | [Start here](../../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [air-passengers-automl.ipynb](air-passengers-automl.ipynb), [delhi-weather-automl.ipynb](delhi-weather-automl.ipynb), [orangejuice-automl.ipynb](orangejuice-automl.ipynb)

**Training:** AutoML through the factory renderer's quality-gated Azure ML v2 pipeline (prepare, AutoML, evaluate).

**Serving:** Azure ML batch endpoint (no-code MLflow) or factory scoring pipeline job via `serving-render`.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- Install the factory extras `train` (plus `vision` for images, `azure` for Azure ML steps and `streaming` for Event Hubs consumers).
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- AutoML models are scored in Azure with an AutoML-compatible environment, not in the local venv.

**Limitations**

- AutoML forecasting needs observed history with each scoring request (history.parquet or the request's history block).
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->

## References and examples

## Consolidated forecasting references

# AutomL notebook examples

docs: https://github.com/Azure/azureml-examples/tree/main/sdk/python/jobs/automl-standalone-jobs
