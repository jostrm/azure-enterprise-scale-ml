# scenarios

**Purpose:** Keep the single authoritative JSON definition for each model scenario.

**Owner:** User-editable configuration.

**Edit/run guidance:** Set dataset, features, target, split, algorithms, AutoML limits and quality thresholds; all serving examples reference these files.

**Status:** Maintained scaffold; local/cloud execution is explicit, never automatic.

[Model-factory guide](../../../readme.md)

## Scenario catalogue

| Task | Configuration files |
|---|---|
| Classification | [Titanic](titanic.json), [diabetes](diabetes.json), [churn](churn.json) |
| Regression | [Insurance costs](insurance-regression.json) |
| Forecasting | [Air passengers](air-passengers.json), [Delhi weather](delhi-weather.json), [orange juice](orangejuice.json) |
| Computer vision | [Multi-class](image-multiclass.json), [multi-label](image-multilabel.json), [object detection](image-object-detection.json), [instance segmentation](image-instance-segmentation.json) |

Each file is the source of truth for its dataset, features, target, split,
algorithm/AutoML settings and quality thresholds. A batch training example and an
online or streaming consumer can reference the same definition; serving mode does
not require another copy of the scenario.

Check the dataset's `status`, `license`, version and notes before ingestion.
Some examples require license review, competition authentication, source selection,
or additional task-specific adapters. Do not clear those gates merely to run an
example. The diabetes example is educational classification, not clinical guidance.

Change configuration in your orange project. If your use case needs a genuinely
different feature or target contract, give it a distinct scenario name and review
its validation/evaluation rules rather than modifying an unrelated shared example.
