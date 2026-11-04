# timeseries forecasting

**Purpose:** Run scheduled or on-demand bulk inference and save predictions to storage. This branch covers `timeseries-forecasting`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates exist for 6 of 6 leaf combinations below; each leaf README lists its route, prerequisites and limitations.

[Scenario configuration](../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../accelerator/readme.md) | [Start here](../../../readme.md)

## References and examples

## Consolidated forecasting references

# Here you have same model implemented, but in different ways
- Azure Machine Learning - via AutoML: Jyputer notebook, and Azure ML pipeline step
- Azure Machine Learning - via pipeline, without AutoMLAzure
- Azure Databricks - via Spark notebook

## Data formats

Raw source formats are preserved; use Delta for refined lake data and an explicit Parquet model-boundary projection when required. Data is centralized under `data/in` and `data/out`, not copied into each example.
