# azureml pipeline with automl step

**Purpose:** Serve low-latency request/response inference through an endpoint. This branch covers `computer-vision/multi-label/azure-automl/azureml-pipeline-with-automl-step`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates over shared engines; cloud steps are explicit, charged operations behind switches that default to false and need the listed prerequisites.

[Scenario configuration](../../../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../../../accelerator/readme.md) | [Start here](../../../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [image-multilabel-automl-pipeline.ipynb](image-multilabel-automl-pipeline.ipynb)

**Training:** Factory Azure ML v2 pipeline with a AutoML image training step and the vision quality gate.

**Serving:** Azure ML managed online endpoint via `serving-render`, `serving-deploy` and `serving-invoke`.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- Install the factory extras `train` (plus `vision` for images, `azure` for Azure ML steps and `streaming` for Event Hubs consumers).
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- Image training in Azure needs `gpu_compute`, or `vision.device: cpu` for the small custom example.
- AutoML images need lake-bound prepared images (`runtime.lake` with a datastore) and a pinned `automl_vision_environment` for evaluation and scoring.
- AutoML models are scored in Azure with an AutoML-compatible environment, not in the local venv.
- Endpoint quota; deployed endpoints bill while running, so delete or scale them to zero when done.

**Limitations**

- The AutoML image adapter follows Microsoft's documented scoring schema; it has not been executed against a real AutoML artifact in this repository.
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->
