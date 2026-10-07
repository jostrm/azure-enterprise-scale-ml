# databricks azureml pipeline step

**Purpose:** Process arriving events continuously or in micro-batches. This branch covers `computer-vision/object-detection/databricks-azureml-pipeline-step`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates over shared engines; cloud steps are explicit, charged operations behind switches that default to false and need the listed prerequisites.

[Scenario configuration](../../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../../accelerator/readme.md) | [Start here](../../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [image-object-detection-databricks-aml-step.ipynb](image-object-detection-databricks-aml-step.ipynb)

**Training:** Azure ML pipeline whose command steps run the existing Databricks job tasks with managed identity and pass the evaluated MLflow model URI between steps.

**Serving:** The second pipeline step starts the Databricks `stream-score` task.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- An existing Databricks workspace and cluster with the shared notebooks and factory wheel imported; Unity Catalog objects and permissions per `user-config/databricks`.
- An Azure ML compute identity allowed to run the existing Databricks job (no PAT tokens).
- An Event Hubs namespace, hub and consumer group, Data Receiver RBAC for the consumer identity, and durable checkpoint storage.

**Limitations**

- Base64 image events must respect Event Hubs message size limits; large images need storage URI references and a reviewed adapter.
- Databricks models live in Databricks MLflow/Unity Catalog, not in the Azure ML registry.
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->
