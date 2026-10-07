# usecase type

**Purpose:** Choose a serving pattern, model task, and implementation approach.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates exist for 124 of 126 leaf combinations (192 notebooks, one per configured scenario); every leaf README states its route, prerequisites and limitations. Cloud steps stay behind switches that default to false.

[Scenario configuration](../user-config/model/scenarios/readme.md) | [Shared execution code](../accelerator/readme.md) | [Start here](../readme.md)

| Pattern | Choose it when | Example surface |
|---|---|---|
| [Batch](batch/readme.md) | Score many records/files in one bounded job and persist predictions. | 66 notebooks: local `score`, Azure ML batch endpoints or scoring jobs, ESML `GOLD_INFERENCE`, Databricks Spark scoring. |
| [Online](online/readme.md) | An application needs a prediction in a request/response interaction. | 66 notebooks: local `online-test` contract, Azure ML managed online endpoints, Databricks Model Serving. |
| [Streaming](streaming/readme.md) | Events arrive continuously and must be processed in small batches or continuously. | 60 notebooks: local JSONL/Event Hubs micro-batches, scheduled Azure ML micro-batch jobs, Databricks Structured Streaming. AutoML forecasting is not offered (history context). |

Inside each pattern, select classification, regression, forecasting or a computer
vision subtype, then a technology branch:

| Technology | Training route | Shared components reused |
|---|---|---|
| `notebook` | Local custom training, optionally the same scenario as an Azure ML pipeline | Factory engine CLI, `render`, gated registration, serving/streaming engines |
| `azure-automl/notebook` | Azure ML AutoML through the factory renderer | `render --mode automl`, AutoML image adapter, serving/streaming engines |
| `azure-automl/azureml-pipeline-with-automl-step` | ESML pipeline factory `IN_2_GOLD_TRAINING_AUTOML` (tabular); gated AutoML image pipeline (vision) | `azure_esml` ESMLProject/AzureMLRollout, `render` |
| `azureml-pipeline` | ESML pipeline factory `IN_2_GOLD_TRAINING_MANUAL` (tabular); custom vision pipeline | `azure_esml` ESMLProject/AzureMLRollout, `render` |
| `databricks-notebook` | Databricks job `train-evaluate` plus a pattern task | `accelerator/databricks` notebooks, `databricks-job` |
| `databricks-azureml-pipeline-step` | Azure ML pipeline running single tasks of an existing Databricks job | `databricks-pipeline`, `databricks_job` step, `accelerator/databricks` notebooks |

The notebooks and README status blocks are generated from the use-case catalog:
`python -m ml_model_factory usecases` lists routes and limitations;
`python -m ml_model_factory usecase-examples` checks that generated files are current
(add `--write` after changing the catalog or generator). Train a compatible versioned
model first; choosing online/streaming does not imply continuous retraining. Folder names
and templates are not evidence that a model/backend combination has been deployed.
