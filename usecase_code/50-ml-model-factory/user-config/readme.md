# user config

**Purpose:** Configure one customer/project without modifying the shared accelerator.

**Owner:** User-editable configuration.

**Edit/run guidance:** Copy generic examples into the orange project, then edit paths and settings. Never store credentials here.

**Status:** Maintained scaffold; local/cloud execution is explicit, never automatic.

[Model-factory guide](../readme.md)

## What to configure

| Location | Required decisions |
|---|---|
| `model\scenarios\<scenario>.json` | Dataset source/version/license, model task, label, features, split policy, algorithm or AutoML limits, and quality thresholds. |
| `storage-selection.example.json` | Actual common/project accounts, resource groups, containers and credentialless Azure ML datastores; the selector is a JSON boolean, not a string. |
| `lake.example.json` | Project/environment/use-case scope, immutable source/snapshot/model versions and a unique execution ID. |
| `model\model-selection.json` | Metrics, direction and improvement thresholds; explicitly choose a champion or first-model policy. |
| `model\monitoring.example.json` | Pinned model version, observation windows, reference data and drift/performance rules. |
| `databricks\job-template.json` | Existing cluster, imported notebook/wheel locations, source data and experiment paths. |
| `model\environments` | Optional reviewed dependency overrides; normally reference an existing pinned environment. |
| `esml-rollout.example.json` | ESML pipeline-factory leaves: shared factory/storage/runtime settings plus one reviewed source binding per scenario (`mode`, compute, data version, run ID, input path, optional AutoML limits and `inference_history_path` for AutoML forecasting). |
| `databricks\inference-settings.example.json` | Databricks batch tables, Model Serving names and Event Hubs streaming settings for the pattern task. |
| `databricks\azureml-step.example.json` | Existing Databricks job ID, task keys and parameters for Azure ML pipelines with Databricks steps (job rendered with `--orchestration azureml`). |

Keep the scenario file shared across serving patterns. Changing a notebook must not
silently change which scenario, storage profile or registered model it uses.

### Optional runtime keys for serving and streaming

| Key | Used by |
|---|---|
| `serving.online_instance_type`, `serving.instance_count`, `serving.batch_instance_count`, `serving.environment` | `serving-render`; `serving.environment` pins a custom-scoring environment. |
| `serving.public_network_access`, `serving.egress_public_network_access` (`enabled`/`disabled`) | `serving-render --kind online` for private workspaces without a workspace managed VNet (legacy per-deployment isolation). Use with `--scoring custom`: Azure ML rejects MLflow no-code deployments with egress disabled. Register the model on workspace storage (deployments reach only workspace storage/ACR/Key Vault) and pre-build `serving.environment` (for example by a smoke job). Use `--endpoint-name`; online endpoint names are unique per region. |
| `job_identity` (`{"type": "managed"}`, optional `client_id`, or `{"type": "user_identity"}`) | Every rendered training/evaluation job and the batch scoring job. Use the compute managed identity for credentialless lake datastores whose ACLs only cover the governed prefix. |
| `automl_vision_environment` | Pinned environment able to load AutoML image MLflow models for gated evaluation and batch scoring. |
| `streaming.eventhubs` (`namespace`, `eventhub`, `consumer_group`) | `stream-score --source eventhubs` and `stream-job`; Azure AD identities only, never connection strings. |
| `streaming_environment` | Optional pinned stream-job environment; required for AutoML image streaming. |
| `lake` with a datastore | Stable stream-job checkpoints, lake-bound AutoML image pipelines, run-scoped prepared/split/model/evaluation outputs, and batch scoring-job predictions under `inference/batch/models/<version>/runs/<inference_run_id>/out`. Use a new `run_id` per training attempt; each `serving-invoke --kind batch --bundle` gets its own inference run (`--inference-run-id`, or generated and reported), never the training `run_id`. Batch requests need a unique `request_id` column. |

## Project-specific settings

Create `runtime.local.json` here in the orange project. Set your existing
`tenant_id`, `subscription_id`, `resource_group`, `workspace_name`, CPU `compute`,
and factory/project/environment identity. Set `gpu_compute` only for tasks that
need it. Merge the reviewed storage-selection example and provide the actual input
data binding; examples do not provision infrastructure or choose the first account.

The JSON field `environment_name` is the deployment stage (`dev`, `test`, `prod`).
The runtime field `environment` is an Azure ML environment reference, not the stage.
Use a pinned version compatible with the trained model. Configuration paths should
be explicit, and no `TODO`, unreviewed dataset license, placeholder cluster, or
implicit `latest` model belongs in an executed deployment.

Local `*.local.json` files are excluded from Git and template copies. Keep secrets
out of even these files: authenticate through the approved identity tooling and
secret stores. Generic configuration templates in purple contain no customer IDs.

## Offline preview first

From the model-factory root after installing the package:

```powershell
python -m ml_model_factory validate --scenario user-config\model\scenarios\diabetes.json
python -m ml_model_factory validate --scenario user-config\model\scenarios\diabetes.json `
  --runtime user-config\runtime.local.json
python -m ml_model_factory storage-target --config user-config\runtime.local.json
python -m ml_model_factory lake-plan --scenario user-config\model\scenarios\diabetes.json `
  --config user-config\lake.local.json
python -m ml_model_factory render --scenario user-config\model\scenarios\diabetes.json `
  --runtime user-config\runtime.local.json --mode automl `
  --output ml-environment\outputs\diabetes\reviewed-render
```

The first command checks the scenario without needing project credentials. The
second also validates your resolved project settings. Create `lake.local.json`
from the lake example with matching use-case identifiers before `lake-plan`.
Render into a new empty output folder. These commands
resolve or validate configuration and create local definitions; they do not submit
training, deploy endpoints, or grant permissions. Dataset ingestion and cloud
execution remain separate explicit actions.
