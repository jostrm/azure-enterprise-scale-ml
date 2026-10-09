---
id: state-machines-and-dags
status: observed
sources:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py
  - bootstrap/lib/factory_lifecycle.py
  - bootstrap/lib/factory_lifecycle_contract.txt
  - esml-v2/azure_esml/domain_layer/pipeline.py
  - healthmodel/src/aifactory_healthmodel/domain/definitions.py
tests:
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_operations.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_lifecycle.py
  - esml-v2/tests/test_esml_pipeline.py
  - healthmodel/tests/test_definitions.py
graph_symbols:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py::function:OperationStore.continue_operation
  - esml-v2/azure_esml/domain_layer/pipeline.py::class:ESMLPipelineFactory
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# State machines and DAGs

## Do not flatten all graphs into one DAG

| Structure | Observed meaning |
|---|---|
| ML pipeline DAG | Dependencies within one rendered job: refinement branches, merge, splits, training/evaluation or inference. |
| IaC/module and phase dependencies | Resource/template prerequisites for one deployment; feature flags and external shared resources affect the actual graph. |
| Health-model definition ordering | Plan nested model definitions before containers that reference them. |
| Agent operation state machine | Human review, execution, observation, continuation, terminal and uncertain states. |
| Factory lifecycle | Repeated configure/deploy/update/observe/reconcile cycles across separate reviewed operations. |
| Architecture wiki graph | Navigational and explanatory cross-links, intentionally cyclic. |

The observed operation path can loop through `running` observations and `awaiting_continuation -> continuing -> running/awaiting_continuation`. This is not a topologically sorted pipeline. Uncertain states cannot be resolved by simply traversing the same write edge again.

Each rendered ML job may be acyclic while the broader ML operating process cycles through data, training, inference, feedback and separately approved retraining. The latter is not evidence of an implemented autonomous retraining controller.

Deletion requires dependency closure and ownership/retention checks, not just reversing a source import graph. Shared network/DNS resources and cascades can cross project boundaries. Static source edges do not capture actual cloud ownership.

## Intended modeling constraint

Give each graph an explicit edge vocabulary and provenance. Preserve cycles where they represent state/knowledge; reject cycles only where the underlying contract requires a DAG. Do not label dynamic calls or inferred associations as proven runtime edges.

See [[Lifecycle-and-Recovery]], [[Reviewed-Operations]], [[Engines-and-Pipelines]], [[Monitoring-and-Retraining]], [[ADR-001-Dual-Graph]] and [[Index]].

Authority: [operation implementation](../../../usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py), [lifecycle contract](../../../bootstrap/lib/factory_lifecycle_contract.txt), [pipeline contracts](../../v2/30-39/37-mlops.md).
