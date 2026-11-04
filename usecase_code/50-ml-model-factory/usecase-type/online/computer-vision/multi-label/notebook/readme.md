# notebook

**Purpose:** Serve low-latency request/response inference through an endpoint. This branch covers `computer-vision/multi-label/notebook`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates: local steps run offline after data approval; cloud steps are explicit, charged operations behind switches that default to false.

[Scenario configuration](../../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../../accelerator/readme.md) | [Start here](../../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [image-multilabel-custom.ipynb](image-multilabel-custom.ipynb)

**Training:** Local custom training and held-out evaluation with the shared engine; the same scenario renders as a quality-gated Azure ML v2 pipeline before registration.

**Serving:** Local `online-test` contract check; Azure ML managed online endpoint via `serving-render`, `serving-deploy` and `serving-invoke`.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- Install the factory extras `train` (plus `vision` for images, `azure` for Azure ML steps and `streaming` for Event Hubs consumers).
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- Image training in Azure needs `gpu_compute`, or `vision.device: cpu` for the small custom example.
- Endpoint quota; deployed endpoints bill while running, so delete or scale them to zero when done.

**Limitations**

- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->
