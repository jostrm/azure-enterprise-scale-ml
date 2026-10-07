# notebook

**Purpose:** Process arriving events continuously or in micro-batches. This branch covers `timeseries-forecasting/azure-automl/notebook`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Not supported for this combination; see the reason and the supported alternative.

[Scenario configuration](../../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../../accelerator/readme.md) | [Start here](../../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Not supported:** AutoML forecast() needs observed history aligned with every request, which event streams do not carry. Use streaming/timeseries-forecasting/notebook (custom seasonal-naive model), or AutoML batch/online scoring with explicit history.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->
