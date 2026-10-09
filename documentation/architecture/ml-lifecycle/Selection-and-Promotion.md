---
id: selection-and-promotion
status: observed
sources:
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/selection.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/tags.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/evaluation.py
  - esml-v2/azure_esml/domain_layer/rollout.py
  - copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md
tests:
  - usecase_code/50-ml-model-factory/accelerator/tests/test_selection.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_tags.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_evaluation_metrics.py
  - esml-v2/tests/test_azureml_rollout.py
graph_symbols:
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/selection.py::function:build_evidence
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/selection.py::function:compare
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Selection and promotion

## Observed

`build_evidence` binds model content, manifest, scoped use case, held-out dataset/contract hashes, evaluator, row count, metrics and independent quality-gate result. `compare` begins blocked and requires explicit policy, immutable identity, finite valid metrics and comparable evidence.

Candidate and champion must agree on scope, use case, task and evaluation identity. Metric-specific directions and absolute/relative deltas preserve units rather than combining arbitrary scores into one weighted number. A zero champion metric blocks undefined relative improvement. Initial selection without a champion requires an explicit policy choice.

Registration tags distinguish factory/project/environment identity from the Azure ML execution-environment asset. Tags and lake dataset/snapshot/run references must agree. Training origin is not silently rewritten to the deployment target.

## Important non-equivalences

```text
quality gate passed
  != candidate beats champion
  != model registered
  != promotion authorized
  != endpoint deployed
  != traffic switched
```

Without opt-in comparison, documented CI behavior registers a qualified completed pipeline model as a **candidate**. Comparison can block registration of a losing model; it does not switch endpoint traffic. A returned `promotion_allowed` is a policy outcome, not a human approval token.

Infrastructure Stage/Prod predecessor checks are a separate lifecycle contract from model-evidence promotion. Repeatedly selecting on a holdout also risks overfitting; the evidence contract does not establish scientific independence by itself.

See [[Engines-and-Pipelines]], [[Monitoring-and-Retraining]], [[Lake-and-Data-Lineage]], [[Reviewed-Operations]] and [[Index]].

Authority: [candidate/champion CI contract](../../../copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md), [model identity and lifecycle](../../v2/30-39/37-mlops.md).
