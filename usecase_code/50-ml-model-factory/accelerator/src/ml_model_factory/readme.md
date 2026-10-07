# ml model factory

**Purpose:** Implement ingestion, training, evaluation, inference, serving, streaming, lake contracts, monitoring and template generation.

**Owner:** Maintainer-owned Python package.

**Edit/run guidance:** Configure behavior through user-config and supported extension points rather than editing shared internals.

**Status:** Maintained engine; local/cloud execution is explicit, never automatic.

[Model-factory guide](../../../readme.md)

## Module map

| Module | Responsibility |
|---|---|
| `config`, `data`, `training`, `forecasting`, `vision`, `evaluation` | Scenario validation, Kaggle ingestion, leakage-aware preparation, custom training and held-out quality gates. |
| `inference` | One scoring contract (`ModelScorer` strategies, `score`, `sample-requests`) shared by batch, online and streaming callers. |
| `vision_automl` | Documented AutoML image scoring-schema adapter and evaluator for gated AutoML vision pipelines. |
| `online` | Online request parsing, `OnlineService`, the Azure ML scoring entry point and the local `online-test` contract. |
| `endpoints`, `serving` | Azure ML online/batch serving renderers, guarded deployment, invocation and deletion (preview unless `--execute`). |
| `streaming`, `stream_jobs` | Micro-batch `StreamProcessor` with injectable sources/checkpoints/sinks, and scheduled Azure ML micro-batch jobs. |
| `azureml`, `selection`, `tags`, `storage_selection` | Azure ML v2 pipeline rendering, quality-gated registration, champion selection, identity tags and storage selection. |
| `databricks_job`, `databricks_jobs` | Existing-job Databricks steps for Azure ML and multi-task Databricks job rendering/creation/runs. |
| `lake`, `lake_flow`, `lake_storage`, `monitoring`, `monitoring_export` | Versioned lake layout, local lake flows, publication and drift monitoring. |
| `usecases`, `examples`, `notebooks` | Use-case catalog (pattern x task x technology) and the generator of every leaf notebook and README status block. |
| `cli` | Command line; feature modules register subcommands through `add_commands` plugins. |

Keep top-level imports of plugin modules light: the CLI parser imports them on startup.
