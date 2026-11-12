# ML Model Factory and MLOps

The Model Factory is a set of code templates and shared engines to prepare data, train and compare models,
and deploy the one you choose. Find them in the [code templates library](../../code-templates/index.md).

## Watch the model lifecycle

Follow versioned data through training, evaluation on held-out data, comparison, registration, the approval
to deploy, and monitoring.

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

Start at the [use-case tree](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/usecase_code/50-ml-model-factory/usecase-type),
or follow [Train your first model](../../usage/02-first-ml-model.md). Each example lists what it needs.

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

The best model of a comparison still needs your approval before it goes to production. When labels or
observations are missing, the monitoring shows the result as unknown.

## Version and engine limits

`azure-esml-sdk` (`azure_esml`) is a new API. Code written for the ESML v1 SDK needs changes to use it.
AutoML forecasting isn't available for streaming, because that forecast needs the observed history with
every request. The Model Factory guide names the alternative.

The compute sizes and versions of a project are settings, and what you can choose depends on the region. See
the [Parameters reference](../../parameters/advanced.md).

<details markdown="1">
<summary>More info</summary>

[Model Factory quickstart and limitations](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/50-ml-model-factory/readme.md) |
[Shared pipeline templates](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/copy_my_subfolders_to_my_grandparent/mlops) |
[DataOps](dataops.md)

Each example lists what it needs: the licence of its sample data, the vision packages, a compute cluster that
exists, and a sign-in to Azure.

</details>
