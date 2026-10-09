---
id: monitoring-and-retraining
status: observed
sources:
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/monitoring.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/monitoring_export.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/lake_flow.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/stream_jobs.py
  - usecase_code/50-ml-model-factory/accelerator/scripts/activate_monitoring.py
  - usecase_code/40-agent-factory/agent_factory/monitoring.py
tests:
  - usecase_code/50-ml-model-factory/accelerator/tests/test_monitoring.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_monitoring_jobs.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_activate_monitoring.py
  - usecase_code/40-agent-factory/tests/test_monitoring.py
graph_symbols:
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/monitoring.py::function:monitor
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/lake_flow.py::function:feedback_in_lake
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Monitoring and retraining

## Observed

ML `monitor` requires an immutable model version, scoped context, ordered disjoint observed UTC windows and bounded rows. It measures feature distribution changes and separately evaluates labeled performance degradation. Predictions and labels must align by request identity; sparse, stale or unavailable evidence must not masquerade as healthy.

The “concept drift” field is a **labeled performance signal**, not proof of a change in the conditional distribution. Data drift alone is not model-quality degradation. Optional image statistics describe fixed color/dimension summaries, not semantic image understanding.

Reports carry scope, model version, window, expiry, metrics and explicit limitations. Monitoring scripts/export adapters and infrastructure dashboards are distinct layers. Agent Factory's monitoring utility projects recorded aggregates; it does not invent quality scores or run inference to create missing observations.

Feedback is stored separately by `feedback_in_lake`; the CLI describes that path as “without retraining.” Streaming recurrence schedules execute bounded scoring jobs; a schedule is not evidence of an autonomous training/remediation loop.

## Gap and proposed operational loop

No automatic drift-to-retraining-to-promotion controller was established in the reviewed engines. A defensible **proposed** loop is: observe signal -> investigate data/labels -> approve new snapshot/training -> evaluate comparable evidence -> separately approve registration/deployment -> observe again. Do not describe this governance loop as an already implemented scheduler.

Historical feature-store terminology establishes lake reuse intent, not an observed managed online feature store or feature-serving SLA. [[Lake-and-Data-Lineage]] records the implemented versioned tables/shareback boundary.

See [[Selection-and-Promotion]], [[Health-Models]], [[State-Machines-and-DAGs]], [[Evidence-and-Gaps]] and [[Index]].

Authority: [model-factory monitoring guidance](../../../usecase_code/50-ml-model-factory/readme.md), [DataOps semantics](../../v2/30-39/36-dataops.md).
