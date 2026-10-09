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

<!-- project-team:start -->
## Project-team quickstart

The Python import is `ml_model_factory`; install from the maintained
`usecase_code\50-ml-model-factory` project or its orange project copy. Configure
scenarios under `user-config`; do not edit shared engines or generated notebooks.

### 1. Prepare the local environment

From the repository root:

```powershell
Set-Location .\usecase_code\50-ml-model-factory
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[train]"
.\.venv\Scripts\python.exe -m ml_model_factory --help
.\.venv\Scripts\python.exe -m ml_model_factory validate --scenario user-config\model\scenarios\diabetes.json
.\.venv\Scripts\python.exe -m ml_model_factory usecases --pattern batch --task-folder classification --technology notebook
```

Use Python 3.10–3.13 and the declared dependency ranges. Package installation
needs access to your approved package feed; the following examples themselves
make no cloud calls. `train` installs local training dependencies, not Azure
credentials or compute.

### 2. Validate configuration and inspect a route with Python

Save as `inspect_model.py` in the model-factory root and run
`.\.venv\Scripts\python.exe .\inspect_model.py`. This reads the existing
scenario and catalog without downloading data, training or writing files.

```python
import json
from pathlib import Path
from ml_model_factory.config import load_json, validate_scenario
from ml_model_factory.usecases import describe, find

scenario = validate_scenario(load_json(Path("user-config/model/scenarios/diabetes.json")))
route = find("batch", "classification", "notebook")
print(json.dumps({"scenario": scenario["name"],
                  "features": scenario["features"],
                  "route": describe(route, [scenario])}, indent=2))
```

Choose batch, online or streaming, then a task and technology from the
[use-case catalog](../usecase-type/readme.md). The
[local classification notebook](../usecase-type/batch/classification/notebook/diabetes-custom.ipynb)
and its [prerequisites](../usecase-type/batch/classification/notebook/readme.md)
reuse the same engines. A supported catalog entry or rendered notebook is not
evidence that its cloud training or serving route has succeeded.

### 3. Optional local CSV preparation, training and evaluation

**Prerequisites:** an already-reviewed, local `diabetes.csv` matching the
[scenario's features and label](model/scenarios/diabetes.json), dataset
licensing/terms, and the local `train` dependencies above. Data is not bundled
with the starter. No Kaggle credentials or network download is hidden here;
see the explicit [`ingest` implementation](../accelerator/src/ml_model_factory/data.py)
if you separately choose ingestion.

This teaching scenario is **not clinical decision support**. Review missing
values, cohort representativeness and intended use. Do not substitute arbitrary
data, lower quality thresholds or treat a passing tutorial as production approval.

Save as `train_local.py` in the model-factory root and run it with the component
interpreter. Each run uses a fresh output folder and preserves the scenario's
split, estimator and quality gates. Only local artifacts are produced.

```python
import json
from pathlib import Path
from uuid import uuid4
from ml_model_factory.config import load_json, validate_scenario
from ml_model_factory.data import prepare
from ml_model_factory.training import train
from ml_model_factory.evaluation import evaluate

scenario = validate_scenario(load_json(Path("user-config/model/scenarios/diabetes.json")))
csv_path = Path(input("Path to the reviewed local diabetes.csv: ").strip()).resolve(strict=True)
run_dir = Path("ml-environment/outputs/diabetes") / ("local-" + uuid4().hex)
prepared, model, report = run_dir / "prepared", run_dir / "model", run_dir / "report"
manifest = prepare(scenario, csv_path, prepared)
train(scenario, prepared, model)
evaluation = evaluate(scenario, prepared, model, report)
print(json.dumps({"output": str(run_dir), "split_rows": manifest["split_rows"],
                  "metrics": evaluation["metrics"]}, indent=2))
```

Inspect `prepared\manifest.json`, the local MLflow model and
`report\metrics.json`, `quality-gate.json`, `comparison.json` and
`responsible-ai.json`. A failed gate raises an error and records the failure;
stop and investigate rather than changing its result. This code neither
registers a model nor deploys an endpoint.

CLI equivalents are `prepare --scenario ... --input ... --output ...`,
`train --scenario ... --prepared ... --model-output ...` and
`evaluate --scenario ... --prepared ... --model ... --output ...`;
use `python -m ml_model_factory <command> --help` for the exact arguments.

### 4. Optional Azure work and gated registration

First create your own `runtime.local.json` with **operator-reviewed existing**
workspace, compute, environment and storage bindings; see
[project-specific settings](readme.md#project-specific-settings),
[offline preview](readme.md#offline-preview-first) and the
[model-factory guide](../readme.md). Install the declared `azure` extra only
for that path. Approved identity/private connectivity, compatible pinned
environments and cost budgets are prerequisites, not outcomes of this tutorial.

For Azure ML SDK v2, the real functions are
[`render`, `submit`, `registration_definition` and `register`](../accelerator/src/ml_model_factory/azureml.py).
`render` writes local job definitions; `submit` creates a billed cloud run.
Registration requires a completed factory pipeline with matching scope,
evaluation lineage and a passing downloaded quality gate. Local training files
alone cannot satisfy that cloud registration contract.

The following is a **function definition only**; it makes no cloud call until
you explicitly invoke it after reviewing the completed job and its target.
Keep the real champion's compatible held-out evaluation and selection policy.
The first-model case is a separate explicit policy decision, not a default.

```python
from pathlib import Path
from ml_model_factory.config import load_json, validate_runtime
from ml_model_factory.azureml import register

def register_reviewed_winner(runtime_path: Path, completed_job_name: str,
                             model_name: str, policy_path: Path,
                             champion_report_path: Path) -> str:
    runtime = validate_runtime(load_json(runtime_path))
    policy = load_json(policy_path)
    champion = load_json(champion_report_path)
    return register(completed_job_name, runtime, model_name,
                    selection_policy=policy, champion_evaluation=champion)
```

See the [full SDK/CLI registration and selection tutorial](../../../documentation/v2/30-39/37-mlops.md#define-the-winning-model-in-json)
and actual [SDK wrapper](../accelerator/scripts/azureml_sdk.py) /
[CLI v2 wrapper](../accelerator/scripts/azureml_cli.py).
Endpoint deployment is a further reviewed operation; serving CLI mutations
preview unless `--execute` is supplied. Cloud routes can still fail because
of environment, data, networking or backend limitations. No live ML success
is claimed here, and no implementation repair or gate bypass is part of onboarding.

For agent workloads, start with the
[Agent Factory SDK](../../40-agent-factory/agent_factory/readme.md#project-team-quickstart).
<!-- project-team:end -->
