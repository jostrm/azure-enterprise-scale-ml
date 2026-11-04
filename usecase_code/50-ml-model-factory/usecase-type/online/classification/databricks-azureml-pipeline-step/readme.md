# databricks azureml pipeline step

**Purpose:** Serve low-latency request/response inference through an endpoint. This branch covers `classification/databricks-azureml-pipeline-step`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates over shared engines; cloud steps are explicit, charged operations behind switches that default to false and need the listed prerequisites.

[Scenario configuration](../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../accelerator/readme.md) | [Start here](../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [churn-databricks-aml-step.ipynb](churn-databricks-aml-step.ipynb), [diabetes-databricks-aml-step.ipynb](diabetes-databricks-aml-step.ipynb), [titanic-databricks-aml-step.ipynb](titanic-databricks-aml-step.ipynb)

**Training:** Azure ML pipeline whose command steps run the existing Databricks job tasks with managed identity and pass the evaluated MLflow model URI between steps.

**Serving:** The second pipeline step runs the Databricks `register-serve` task (Model Serving).

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- An existing Databricks workspace and cluster with the shared notebooks and factory wheel imported; Unity Catalog objects and permissions per `user-config/databricks`.
- An Azure ML compute identity allowed to run the existing Databricks job (no PAT tokens).
- Endpoint quota; deployed endpoints bill while running, so delete or scale them to zero when done.

**Limitations**

- Databricks models live in Databricks MLflow/Unity Catalog, not in the Azure ML registry.
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->
