# ML Model Factory and MLOps

Use reusable examples and shared engines to prepare data, train and compare
models, then deliberately deploy the selected result.

## Watch the model lifecycle

Follow versioned data through training, held-out evaluation and comparison,
reviewed registration, separate deployment approval, and monitoring. This
configuration-wizard lesson is illustrative: playback never submits a job,
registers a model or approves a production release.

<picture>
  <source media="(prefers-reduced-motion: reduce)" srcset="../../../assets/animations/mlops.png">
  <img src="../../../assets/animations/mlops.gif" alt="MLOps lifecycle from versioned data through training, evaluation, reviewed registration, separate deployment approval and monitoring." width="1400" height="995" loading="lazy">
</picture>

[Animated SVG](../../assets/animations/mlops.svg) |
[GIF](../../assets/animations/mlops.gif) |
[Still image](../../assets/animations/mlops.png)

For the upstream data path, see [DataOps + MLOps](dataops.md#watch-the-data-flow).

## Choose your use case

| Pattern | Typical use |
| --- | --- |
| Batch | Score a dataset on demand or on a schedule. |
| Online | Answer individual inference requests. |
| Streaming | Process continuous or micro-batch events with checkpoints. |

The current Model Factory organizes examples by pattern, task and technology:
classification, regression, forecasting and supported vision routes using
custom Python, AutoML, Azure ML pipelines and Databricks.

Start at the [current use-case tree](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/usecase_code/50-ml-model-factory/usecase-type)
and read that leaf's prerequisites. A notebook's presence is not proof that all
engine/task combinations are supported or deployed.

## Where to make your changes

| Folder in `50-ml-model-factory` | Ownership |
| --- | --- |
| `user-config` | Your scenario, model policy, storage and Databricks choices. |
| Project copies of `usecase-type` examples | Thin examples you can adapt for the workload. |
| `accelerator` | Shared maintainer-owned engines; avoid copying their internals. |
| `data/out` and `ml-environment` | Generated datasets, models, reports and run artifacts. |

## Train, compare and deploy separately

1. Validate the chosen scenario, input data, budget and compute references.
2. Render or inspect the job before submitting cloud work.
3. Evaluate candidates against compatible held-out data and the configured policy.
4. Review registration and deployment as separate actions.
5. Monitor inputs, performance and freshness after deployment.

A winning model is not production approval. Missing labels or insufficient
observations are unknown, not a successful health result.

## Version and engine limits

`azure-esml-sdk` / `azure_esml` is a newer API, **not a drop-in ESML v1 replacement**.
Older pipelines remain separate compatibility paths.
AutoML forecasting is not offered for streaming where the prediction method
requires observed history with each request; use the supported alternative
described in the model-factory guide.

Compute SKU/version defaults change and have regional constraints. Read the
[current Parameters reference](../../parameters/advanced.md) instead of copying
an old hard-coded compute table.

<details markdown="1">
<summary>More info</summary>

[Model Factory quickstart and limitations](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/50-ml-model-factory/readme.md) |
[Shared pipeline templates](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/copy_my_subfolders_to_my_grandparent/mlops) |
[DataOps](dataops.md)

Storage selection does not provision or migrate data. Dataset licences, vision
dependencies, existing compute/cluster references and authenticated cloud access
remain explicit requirements. Framework examples are not a universal model CRUD
API across every runtime.

</details>
