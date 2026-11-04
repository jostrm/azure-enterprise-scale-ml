# notebook

**Purpose:** Process arriving events continuously or in micro-batches. This branch covers `classification/notebook`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates: local steps run offline after data approval; cloud steps are explicit, charged operations behind switches that default to false.

[Scenario configuration](../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../accelerator/readme.md) | [Start here](../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [churn-custom.ipynb](churn-custom.ipynb), [diabetes-custom.ipynb](diabetes-custom.ipynb), [titanic-custom.ipynb](titanic-custom.ipynb)

**Training:** Local custom training and held-out evaluation with the shared engine; the same scenario renders as a quality-gated Azure ML v2 pipeline before registration.

**Serving:** Local JSONL `stream-score` simulation and optional Event Hubs consumer; Azure ML scheduled micro-batch job (`stream-job`) reading Event Hubs with lake checkpoints.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- Install the factory extras `train` (plus `vision` for images, `azure` for Azure ML steps and `streaming` for Event Hubs consumers).
- For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, identity and storage selection.
- An Event Hubs namespace, hub and consumer group, Data Receiver RBAC for the consumer identity, and durable checkpoint storage.

**Limitations**

- Azure ML streaming is scheduled micro-batching: latency follows the schedule interval, not continuous event-at-a-time scoring.
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->
