---
id: engines-and-pipelines
status: observed
sources:
  - esml-v2/azure_esml/base_layer/contracts.py
  - esml-v2/azure_esml/domain_layer/pipeline.py
  - esml-v2/azure_esml/domain_layer/runtime.py
  - esml-v2/azure_esml/domain_layer/rollout.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/training.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/serving.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/streaming.py
  - esmlfac/adapter.py
tests:
  - esml-v2/tests/test_esml_pipeline.py
  - esml-v2/tests/test_esml_runtime.py
  - esml-v2/tests/test_azureml_rollout.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_lifecycle_e2e.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_orchestration_matrix.py
graph_symbols:
  - esml-v2/azure_esml/domain_layer/pipeline.py::class:ESMLPipelineFactory
  - esml-v2/azure_esml/domain_layer/runtime.py::class:FactoryModelSteps
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Engines and pipelines

## Observed architecture

`azure_esml` separates app composition, ESML domain contracts and generic base-layer backends. `ESMLPipelineFactory` builds an offline `PipelinePlan`; SDK v2 and CLI v2 consume the same rendered pipeline. The new API is not an import-compatible shim for retained `esml`, `esmlfac` and `esmlrt` implementations.

Current pipeline types cover input-to-gold refinement, refinement plus inference, explicitly mapped Databricks inference, prepared-gold inference, native AutoML training and manual training. Runtime steps preserve raw bronze, validate silver, produce distinct gold, split and train/evaluate. Learned preprocessing belongs in training-only pipelines, avoiding fitting transforms on the holdout.

Canonical `ml_model_factory` engines supply training, evaluation, selection, batch/online/streaming inference and lake orchestration. Thin user-facing notebooks/configuration select these engines; the example matrix is not evidence that every task, dataset, environment or backend is deployed and certified.

The ESML wheel build includes the same canonical model-factory code. It does not introduce another implementation or require a sibling editable checkout in installed consumers.

## Execution gates

Rendering, source/data registration, training submission, successful job completion, model registration, endpoint publication and invocation are distinct operations. `AzureMLRollout` retains actual job/registration/inference receipts and applies scope, lineage and quality checks. Explicit cloud execution flags in model-factory examples do not replace human authorization or required cloud permissions.

Databricks jobs and Azure ML steps require existing reviewed cluster/notebook/compute/environment bindings. AutoML forecasting streaming is not offered as an equivalent to history-aware batch/online forecasting.

See [[Repository-Boundaries]], [[Selection-and-Promotion]], [[Lake-and-Data-Lineage]], [[Orchestration-and-Updates]], [[Packaging-and-Release]] and [[Index]].

Authority: [MLOps and ESML v2](../../v2/30-39/37-mlops.md), [model-factory usage and matrix](../../../usecase_code/50-ml-model-factory/readme.md).
