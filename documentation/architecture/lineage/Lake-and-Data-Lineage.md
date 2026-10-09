---
id: lake-and-data-lineage
status: observed
sources:
  - esml-v2/azure_esml/domain_layer/shared_lake.py
  - esml-v2/azure_esml/domain_layer/shareback.py
  - esml-v2/azure_esml/domain_layer/lake_publication.py
  - esml-v2/azure_esml/domain_layer/runtime.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/lake_flow.py
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/storage_selection.py
  - documentation/v2/30-39/34-datalake-onboard-data.md
tests:
  - esml-v2/tests/test_silver_shareback.py
  - esml-v2/tests/test_delta_shareback_flow.py
  - esml-v2/tests/test_lake_publication.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_lifecycle_e2e.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_snapshot_contract.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_storage_selection.py
graph_symbols:
  - esml-v2/azure_esml/domain_layer/shareback.py::class:SilverShareback
  - usecase_code/50-ml-model-factory/accelerator/src/ml_model_factory/lake_flow.py::function:prepare_snapshot
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Lake and data lineage

## Observed contracts

Current `mlops/v1` separates master source/product releases, project/environment datasets, use-case training snapshots, training runs, immutable model bindings and inference/feedback. Legacy `projects/` consumers are not silently migrated.

Bronze preserves original bytes; silver is a validated reusable analytical table; gold is separately use-case-specific. Training splits derive from gold, not an implicit shortcut to silver. New silver/gold default to real Delta with transaction history; explicit Parquet is a compatibility choice, not a silent fallback when Delta dependencies are missing.

Pinned Delta versions, manifest hashes and completion markers establish data identity. Custom training may consume a hash-bound Parquet projection of the same gold splits; that does not replace authoritative gold. `_SUCCESS.json` and lineage manifests are published only after the corresponding output contract completes.

`SilverShareback` uses producer + variation + release identity. Reference mode publishes immutable metadata pointing to a verified producer silver table; copy materialization is explicit. A reference is not a symbolic link or `latest` alias. Retention of pinned table files/history matters before source deletion or Delta vacuum.

## Scope and authorization

Storage selection chooses configured common lake or project **data** storage, not the workspace artifact account and not local disk. Account/container/datastore and resource-group checks are shared across renderers/publication/monitoring paths. Unknown cloud URIs must not be quietly retargeted.

Approved-consumer metadata is **not an ACL**. Azure RBAC/Gen2 ACLs must independently permit the chosen project/environment identity. Common lake reuse does not authorize access to all projects.

RAG, fine-tuning, vision annotations, streaming checkpoints/dead letters and online capture have distinct modality contracts; tabular gold is not a universal representation or an evidenced managed online feature store.

See [[Engines-and-Pipelines]], [[Selection-and-Promotion]], [[Monitoring-and-Retraining]], [[Identity-and-Personas]], [[Retrieval-Provenance]], [[Factory-Scope-Model]] and [[Index]].

Authority: [lake hierarchy](../../v2/30-39/34-datalake-onboard-data.md), [DataOps/Delta/shareback](../../v2/30-39/36-dataops.md).
