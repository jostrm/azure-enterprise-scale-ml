# Azure Data Factory templates for DataOps to MLOps

- Supports initial loads and delta loads.
- Used to prepare data for batch training and inference.
- Reads project Blob storage into an explicit destination before orchestrating compute.
- Model implementation: `usecase_code\50-ml-model-factory`.

## Scope and prerequisites

`main.bicep` deploys **only child linked services, datasets and pipelines into an existing factory**.
It does not create or change a factory, identity, integration runtime, storage account, network,
role assignment, Azure ML workspace, compute, endpoint, or trigger. Infrastructure enablement
and deployment belong to the parent AI Factory flow. Nothing is deployed merely by copying files.
Use a distinct `namePrefix`; a manual incremental deployment updates children with those names.

The project `storage2001` account has **HNS=false**. Use `AzureBlobStorage` and its **Blob**
endpoint, not `AzureBlobFS`, `dfs` or the existing `ls_storage_lake` module. Source and sink
accounts/endpoints are independently configurable. Set `sourceCredentialName` and
`sinkCredentialName` to the existing ADF credential `ls_cred_project_uami` only when that
credential exists and its UAMI is assigned to the factory; empty strings use the factory's
system-assigned managed identity. Source needs Storage Blob Data Reader and sink needs
Storage Blob Data Contributor, granted separately by an administrator.

`integrationRuntimeName` must identify an existing **self-hosted integration runtime (SHIR)**.
It must have working private DNS, routes, TLS and outbound access to Blob and ARM; validate
linked-service connectivity before queueing. Web activities explicitly set `connectVia`.
An Azure DevOps agent or GitHub runner on a VM **is not an ADF integration runtime**.
Installing a CI agent alone does not satisfy this prerequisite. No public-network fallback
or firewall bypass is enabled here. The factory system identity used by ARM Web activities
needs workspace-scoped permissions to create/read AML jobs; its identity is independent of
the configurable Blob credential. Azure ML job/compute identity also needs input/output data
access. No credentials are embedded in these templates.

## Manual install (administrator action; not performed automatically)

From the repository root in PowerShell 7, with Azure CLI and Bicep already provisioned:

```powershell
$templates = 'copy_my_subfolders_to_my_grandparent\dataops\azure-datafactory'
Copy-Item "$templates\parameters.example.json" "$templates\parameters.local.json"
# Edit parameters.local.json: existing factory, SHIR, Blob endpoints and optional credential names.
bicep build "$templates\main.bicep" --stdout | Out-Null
python -m unittest discover -s "$templates\tests" -v

# Explicit authenticated child-resource deployment; inspect scope and parameters first.
az deployment group create --subscription $subscriptionId --resource-group $resourceGroup `
  --name ml-factory-adf-children --mode Incremental `
  --template-file "$templates\main.bicep" --parameters "@$templates\parameters.local.json"
```

Do not commit resolved local parameters, job payloads or run files. This template does not
install tools or accept licenses. In ADF Git mode, coordinate these live child-resource
changes with the factory's authoring/publish branch; subsequent ADF publishes can replace them.

## Copy and Azure ML v2 job contract

The installed `<namePrefix>_copy_aml_v2` pipeline accepts:

| Parameter | Contract |
|---|---|
| `loadMode` | `initial` or `delta`; default `initial` |
| `sourceContainer`, `sourceFolder` | Source Blob location |
| `sinkContainer`, `sinkFolder` | Explicit destination Blob location |
| `filePattern` | Wildcard file selection, default `*` |
| `watermarkStart`, `watermarkEnd` | Delta UTC modification-time window `[start, end)` |
| `subscriptionId`, `resourceGroup`, `workspaceName` | Existing Azure ML target |
| `jobPayload` | An **ARM Jobs request object**, not CLI YAML |
| `lakeParameters` | Optional validated lake lineage/destination metadata; default `{}` preserves legacy runs |

Initial Copy reads all matching files recursively; delta Copy adds modification-time filters.
Both use Binary datasets and preserve folder hierarchy: there is no schema transformation.
Use nonoverlapping source and sink paths. This is file-level delta, **not CDC**: deletions
are not propagated, and no watermark store is updated automatically. Persist the next
watermark in your orchestrator only after the entire pipeline succeeds. Replaying a window
overwrites matching Blob destinations; it is not an exactly-once transaction.

Without the optional lake adapter, the job receives only the supplied `jobPayload`:
**copy output is not inferred or injected**.
Set the payload's input URI to the configured copy destination (or a registered data asset).
The same job mechanism can queue a prepared training pipeline or a batch-scoring job.
`job-payload.example.json` illustrates the **CommandJob REST wire shape**, using pre-existing
versioned code/environment and compute resource IDs. Its `train.py` is an explicit contract
with your uploaded code asset, not a file installed by this ADF template. Replace it with
your actual command or a validated PipelineJob ARM body. The example is intentionally
unresolved and is not a runnable training pipeline or automatic CLI-YAML conversion.

```powershell
# Resolve copy.example.json and job-payload.example.json into your own approved local files.
python "$templates\prepare_run.py" --runtime runtime.json `
  --copy copy.local.json --job-payload job-payload.local.json --output generated\adf-run.json

# Queue separately from installation; body is the pipeline parameter object, not an ARM envelope.
$uri = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.DataFactory/factories/$factoryName/pipelines/ml_factory_copy_aml_v2/createRun?api-version=2018-06-01"
az rest --method post --url $uri --body '@generated\adf-run.json'
```

`prepare_run.py` performs offline structural checks and rejects unresolved examples and
CLI-YAML-shaped objects. It maps runtime JSON `subscription_id`, `resource_group` and
`workspace_name` to the ADF names above. It is **not** the complete Azure REST schema validator.

### Optional shared lake binding: raw Copy is landing, never silver

Use the preprovisioned model-factory Python environment for this optional adapter.
`--lake lake.local.json` accepts the lake object documented in the MLOps README;
alternatively put that object under `runtime.lake`. Omit both to keep the original
Copy and ARM payload behavior unchanged. No existing directories are renamed or moved.

```powershell
$python = 'usecase_code\50-ml-model-factory\.venv\Scripts\python.exe'
& $python "$templates\prepare_run.py" --runtime runtime.json `
  --copy copy.local.json --job-payload job-payload.local.json `
  --lake lake.local.json --scenario scenario.json --input-name raw `
  --output generated\adf-run.json
```

The adapter uses **the shared `LakeLayout`, not a separate ADF naming convention**:

* Source remains the explicit external `sourceContainer`/`sourceFolder`. Put the reviewed
  scenario file directly under that folder; this adapter requires a single safe filename,
  not a nested path or guessed directory. Complex image-directory payloads require a
  separately reviewed binding rather than silently treating a folder as a file.
* Sink is derived from `lake.storage.container` and the dataset-version `landing` key;
  optional Copy sink values are replaced. `filePattern` becomes the scenario filename.
  The deployed sink linked service must use the same canonical `storage.account_url`.
  ADF's `ValidateLakeDestination` rejects account/container/prefix mismatches before Copy.
* The **existing** named ARM input (`raw` by default) is explicitly rebound as `uri_file`
  to `LakeLayout.azureml_uri("landing") + scenario.dataset.file`. Its mode is preserved.
  The configured existing datastore must reference the same account/container and grant
  job identity access. No data asset registration or inferred `silver` input is performed.
* `lakeParameters` records project/environment/use case, dataset/data version, snapshot
  and execution IDs, serving mode, query/version IDs and shared paths; ARM job tags carry
  source/run lineage. These are declared paths, **not evidence that every stage ran**.

Binary Copy performs no parsing, cleansing, feature engineering or quarantine validation.
It must not be labeled silver. Actual bronze/silver validation, rejected-record reason
codes, immutable gold snapshot preparation and model evaluation require a separate
explicit processing job. Copy does not create empty markers or upload zip archives.
Replaying Copy can overwrite raw landing files; choose a new data version when source
bytes change. It never writes a training snapshot. Use a fresh explicit `run_id` for a
new execution and a reviewed explicit `snapshot_id`; the builder does not invent either.
For Azure ML preparation, bind writable output to `training/runs/<run_id>/prepared`;
keep immutable snapshot gold as a separately published reference. Direct Azure ML
output paths are not create-only locks, so manually reusing run IDs is unsafe.

Dataset and use-case keys are independent of task type and compute engine. Inference
uses `batch|online|streaming`, an explicit immutable `model_version`, and per-run
`in/gold/out` plus separate quarantine and late-label `feedback` areas. Quarantine
and feedback remain outside immutable dataset-version/inference roots; their locations
are always taken from the shared layout, never inferred from an output prefix. Feedback must
reference stable request/entity IDs and observed labels; it is not automatically sent
to training. No inference or quarantine job is fabricated by this Copy adapter.
Do not place SAS tokens, connection strings or passwords in lake/Copy/payload JSON.
The optional builder rejects credential fields/URIs without printing their values.

### Verified REST API and completion semantics

- `PUT https://management.azure.com/subscriptions/{subscription}/resourceGroups/{group}/providers/Microsoft.MachineLearningServices/workspaces/{workspace}/jobs/{id}?api-version=2024-04-01`
- Body: `{"properties":{"jobType":"Command" | "Pipeline" | "AutoML" | "Spark" | "Sweep", ...}}`.
  Each job type has its own REST fields (`computeId`, `environmentId`, `codeId`, `inputs`,
  `jobInputType`, etc.). This is **not** `pipeline.yml`'s CLI schema (`type`, `compute`, `jobs`).
- The unique ID is `adf-<pipeline RunId>`; it is known before PUT, so no undocumented
  submission-output fields are assumed. Poll with **GET on the same Jobs URL**.
- Status is `response.properties.status`. AML Jobs v2 calls successful execution
  **`Completed`**; ADF activity success is **`Succeeded`**. These are different enums.
  Poll every 30 seconds, with a two-hour Until timeout and two-minute Web HTTP timeout.
  `Failed`, `Canceled`, `Cancelled` and `NotResponding` reach an explicit Fail activity.
  Missing/malformed/unknown states can never reach success and ultimately time out.
  ADF Until can continue after an inner Web failure, but the terminal timeout still fails closed.
- `turnOffAsync: true` prevents ADF from switching to implicit Location-header polling.
  Submission/status activities use managed identity and `secureInput`/`secureOutput`.
  Avoid secrets in payloads: pipeline run parameters can still be visible to authorized
  operators even when activity logs are masked.
- **No model registration or endpoint deployment occurs here.** After a training pipeline
  has succeeded, use MLOps registration, which additionally checks the downloaded evaluation
  quality gate and model lineage. A completed arbitrary job alone is insufficient.
  An ADF timeout does not cancel the underlying AML job; inspect/cancel it explicitly.

## Optional Databricks notebook orchestration

Set `databricksLinkedServiceName` to an **existing authenticated AzureDatabricks linked service**
to also install `<namePrefix>_copy_databricks`. Empty means no notebook pipeline is created.
The linked service should use the documented factory **system-assigned MSI** authentication
(`authentication: "MSI"`, workspace resource ID and existing cluster ID), or an approved
Key Vault-backed token configuration. Provision the identity as a Databricks service principal
with workspace access, notebook permissions and cluster attach/run permissions; configure
the required Azure workspace role assignments according to your Databricks/ADF integration.
Do not treat an Azure Storage UAMI credential as automatically valid Databricks authentication.
Test the linked service and its own SHIR `connectVia` route for private workspaces before use.
This template references, but does not create or modify, that linked service.

In addition to Copy parameters, pass `notebookPath`, `notebookInputPath`, `artifactRoot`,
`scenarioPath` and `experimentPath`. Import the factory's `databricks\train.py` and point
`notebookPath` at that notebook. The activity passes its exact widget names:
`input_path`, `artifact_root`, `scenario_path`, `experiment_path`, and optional `lake_config`.
The `lakeConfig` pipeline string defaults to empty; existing callers do not need it.
The optional `modelContext` string is passed as the `model_context` notebook widget.
Supply credential-free factory/project/environment identity, or put `aifactory`
alongside project/environment in `lakeConfig`. The notebook uses the shared tag
builder and rejects conflicts; full scope is mandatory for its separate registry
operation. Import both `lake_utils.py` and `model_tags.py` alongside `train.py`.
No model is registered merely by running the ADF notebook activity.

Set `notebookInputPath` to the copied CSV/Parquet, using a Spark-readable `wasbs://`
Blob URI or a driver-accessible path. The Databricks cluster must have separately configured
private storage connectivity and credentials; ADF's identity is not transferred to it.
Use a writable `/local_disk0/...` scratch artifact root or an existing `/Volumes/...` root.
Training logs the model and evaluation artifacts to the selected MLflow experiment before
the notebook completes; scratch files alone are not durable outputs.

Notebook failure or a failed model quality gate fails the ADF pipeline, with a two-hour
activity timeout. No automatic model deployment or promotion is attached. Batch and
streaming notebooks have different widget contracts and are not interchangeable with
this training activity.

### Databricks lake widgets and checkpoint storage

For opt-in use, import `databricks\lake_utils.py` as a Python workspace file alongside the
notebooks (or use the complete Databricks Git folder), and install the reviewed factory
wheel containing `ml_model_factory.lake`. Legacy empty `lake_config` does not import the
new helper. `lake_config` accepts the **lake object as JSON text** or a driver-readable JSON
file; no credentials belong in either. ADF passes the optional `lakeConfig` string through.
The existing Jobs template likewise has an empty-default `lake_config` job parameter.

* **Train:** leave `input_path` empty or set it to the exact configured landing filename.
  `LakeLayout.blob_uri` is translated to `wasbs://` for the HNS=false project data account.
  The cluster needs separately configured Blob credentials/connectivity. Training artifacts
  use the shared per-run key under the writable artifact root and fail if that run directory
  already exists. MLflow records actual input/artifact bindings in `lake-lineage.json`.
  Preparation remains per-run; no immutable snapshot, silver data, or lake model publication
  is claimed. Durable model/evaluation outputs are still the logged MLflow artifacts.
* **Batch:** retain distinct explicit `catalog.schema.table` input/output names. The
  contract's Blob output key is **not a Unity Catalog table name**. MLflow records the actual
  table bindings and model version, and scored rows retain `lake_run_id`. A table is created
  with `errorifexists`; retries do not overwrite an earlier scoring table.
* **Streaming:** set `checkpoint_root` to a durable existing
  `/Volumes/<catalog>/<schema>/<volume>` or a **separate, verified HNS-enabled**
  `abfss://<container>@<checkpoint-account>.dfs.core.windows.net/<prefix>`.
  The helper appends the shared stable `operations/streaming/<pipeline_id>/versions/<pipeline_version>/checkpoints`
  key. Leave the old `checkpoint` widget empty (or pass exactly that derived path).
  It rejects `wasbs://` for lake checkpoints; HNS=false project Blob data support does
  **not** establish compatible streaming checkpoint semantics. For ABFS it verifies the
  Hadoop connector class is installed; administrators must still verify access, HNS,
  supported runtime/connector and checkpoint behavior. No SAS URI is accepted.

Streaming model rollouts/reruns retain the checkpoint: it is not nested below a run/model.
Never share it between different queries. Bump `pipeline_version` for incompatible
state/schema/query changes and explicitly review replay. Output remains a real configured
Delta table; the notebook does not convert a lake key into a table. Numeric `models:/.../N`
URIs must match `lake.model_version=N`; immutable `runs:/<run-id>/...` URIs use that run ID
as the lake model version. Mutable aliases are rejected. Model/task adapter capabilities
are unchanged: training is tabular/forecasting, streaming is stateless classification or
regression, and scalar batch scoring does not support image outputs.

MLflow lineage declares contract locations and actual bindings but does **not** claim
they were materialized. Streaming malformed JSON fails; null event IDs/timestamps are
filtered and late events can be dropped by the watermark. No quarantine sink is
pretended: add reviewed validation/rejected-record processing when required. Late-label
feedback is reserved separately and never auto-promoted into training. Event Hubs secrets
are read from the configured secret scope and are not printed or logged as lineage.

## Reference contracts and validation limits

- [Azure ML Jobs PUT, 2024-04-01](https://learn.microsoft.com/en-us/rest/api/azureml/jobs/create-or-update?view=rest-azureml-2024-04-01)
- [Azure ML Jobs GET, 2024-04-01](https://learn.microsoft.com/en-us/rest/api/azureml/jobs/get?view=rest-azureml-2024-04-01)
- [ADF Web activity: MSI, connectVia, async handling](https://learn.microsoft.com/en-us/azure/data-factory/control-flow-web-activity)
- [Blob managed-identity linked services](https://learn.microsoft.com/en-us/azure/data-factory/connector-azure-blob-storage)
- [Databricks linked service authentication](https://learn.microsoft.com/en-us/azure/data-factory/compute-linked-services#azure-databricks-linked-service)
- [DatabricksNotebook baseParameters](https://learn.microsoft.com/en-us/azure/data-factory/transform-data-databricks-notebook)

Offline tests parse JSON, compile Bicep and check child-only scope, wire contracts, status
handling, private routing declarations, optional landing/input bindings and credential
rejection. Factory `tests\test_databricks.py` also executes mocked legacy/lake notebooks,
checks stable checkpoints across model/run changes and rejects unsupported checkpoint
backends. These checks do not prove live
RBAC, SHIR/private DNS connectivity, data format compatibility, registered asset validity,
Databricks permissions, or Azure service acceptance. Those are explicit preflight/run checks.