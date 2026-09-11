# Reusable Azure ML v2 MLOps

Opt-in templates for `usecase_code\50-ml-model-factory`. These files create no Azure
resources and are inactive until an administrator installs a caller/workflow.
There are no push/PR triggers, automatic production deployment, legacy SDK copies,
license acceptance, or package/tool installs during pipeline execution.

## Shared script API

Both CI providers invoke the same portable Python script from PowerShell 7:

```powershell
$templates = 'copy_my_subfolders_to_my_grandparent\mlops\03_mlops_2026-09'
$python = 'usecase_code\50-ml-model-factory\.venv\Scripts\python.exe'
& $python "$templates\scripts\ci.py" validate --scenario path\to\scenario.json
& $python "$templates\scripts\ci.py" validate --scenario path\to\scenario.json --runtime runtime.json
& $python "$templates\scripts\ci.py" ingest --scenario path\to\scenario.json --output generated\ingest
& $python "$templates\scripts\ci.py" train --scenario path\to\scenario.json `
  --runtime runtime.json --mode custom --output generated
# A separate approved action, never chained automatically after train:
& $python "$templates\scripts\ci.py" deploy --scenario path\to\scenario.json `
  --runtime runtime.json --mode custom --model-id azureml:my-model:1 `
  --kind online --approval-environment approved-nonproduction
```

`--scenario` is the selected scenario **JSON path**, whose `name` identifies the model
scenario. Use `--mode automl` or `custom` as supported by that scenario. Runtime is
JSON, not YAML, with resolved `subscription_id`, `tenant_id`, `resource_group`,
`workspace_name`, `compute` and `input_data`; use the core's project/discovery flow
to resolve environment-specific names. Supply a versioned `environment` and optional
`gpu_compute`/`serving` settings as required by the model. No project-specific names
are embedded in either template.

Actions are independent:

1. **validate** calls the core's offline `validate` command and local tests. No Azure
   login, Azure CLI, SDK network calls, Kaggle download or dependency installation.
2. **ingest** explicitly calls core `ingest`. Kaggle credentials come only from secret
   environment variables. Dataset versions must be pinned; competition/data licenses
   must already have been accepted manually by an authorized person. This action does
   not accept terms. Data stays on the selected runner; it is not uploaded as a public
   CI artifact. Use the returned input path on that runner or your separately approved
   upload process to set runtime `input_data` for a subsequent training action.
3. **train** validates, creates a unique empty `generated\bundle-<id>` directory through
   core `render --output <bundle>`, then submits exactly `<bundle>\pipeline.yml`
   using `az ml job create -f ...` and explicit subscription,
   group and workspace flags. CLI extension **`ml==2.38.1`** is verified before queueing;
   dynamic extension install is disabled. Polling uses `az ml job show`.
   The core also exposes `submit --runtime ... --job pipeline.yml` for standalone SDK
   callers, but these templates deliberately submit via **CLI v2**, not the REST body.
4. Successful AML `Completed` (or `Succeeded` from a compatible caller) normalizes to
   **Succeeded**. Failed/canceled/unknown/missing states and finite polling timeouts
   fail closed. Default wait is 7,200 seconds with 30-second polls; use
   `--timeout-seconds` and `--poll-seconds` for bounded overrides. Timeout leaves the
   remote job running; inspect or explicitly cancel it rather than blindly resubmitting.
   `submitted-job.json` records the job name and bundle path. Repeated runs use fresh
   bundles because the renderer rejects nonempty output directories; previous bundles
   are preserved for diagnostics, never reused as current job input.
5. Only after success does `register_evaluated` call
   `ml_model_factory.azureml.register(job_name, runtime, manifest["model_name"])`.
   The core rechecks the successful factory pipeline, downloads its named `report`
   output, verifies `quality-gate.json` and lineage, and registers the named evaluated
   `model` output. There is no assumed CLI `register` subcommand. A failed gate cannot
   create a success receipt. `generated\registered-model.json` is recreated only after
   registration; stale receipts are removed before a new submission.
6. **deploy** is a separate action with an explicit immutable model ID, mode, scenario,
   `online|batch` kind and preconfigured approval environment. It renders a fresh
   deployment bundle and invokes
   `ml_model_factory.serving.deploy(runtime, bundle, model_id, kind)`.
   Core checks model gate tags and scenario/mode lineage before deploying.
   Deployment may switch online traffic or a batch default: reviewers must approve
   the target runtime and model first. **An environment name alone does not establish
   protection**: configure required reviewers/checks out of band and restrict who can
   select/create environments. No automatic production stage exists.

Capability limits are explicit in the rendered manifest. Image AutoML is currently
training-only without the evaluated `pipeline.yml`; this CI action refuses it rather
than registering an unevaluated model. Custom vision uses the core CLI pipeline.
AutoML forecasting deployment is unsupported and must not be substituted with an
ordinary tabular prediction endpoint. Optional custom-tabular `rai-pipeline.yml`
artifacts are separate, explicitly queued workflows, not an automatic claim that every
scenario has an Azure Responsible AI dashboard.

## Optional shared lake contract

Omit `runtime.lake` to retain existing input URIs, outputs and legacy project layouts.
Opt in by adding the following **credential-free** object to your resolved runtime:

```json
{
  "lake": {
    "project": "001",
    "environment": "dev",
    "use_case": "titanic",
    "dataset": "titanic-passengers",
    "data_version": "1",
    "snapshot_id": "reviewed-20260911",
    "run_id": "explicit-standalone-execution",
    "serving": "batch",
    "pipeline_id": "passenger-predictions",
    "pipeline_version": "v1",
    "prefix": "mlops/v1",
    "storage": {
      "account_url": "https://examplestorage.blob.core.windows.net",
      "container": "ml-model-factory",
      "datastore": "existing_project_blob"
    }
  }
}
```

`use_case` must match the scenario name (or omit it to use that name); `dataset` is a
stable data-product identifier, not the scenario display name. The shared
`ml_model_factory.lake.LakeLayout` owns all keys. Paths separate reusable versioned
datasets (`landing`, `bronze`, validated `silver`, rejected-data quarantine), immutable
use-case training snapshots, per-run model/evaluation artifacts, and versioned
`batch|online|streaming` inference `in/gold/out`. Quarantine and late feedback stay
outside immutable dataset-version/inference roots, using their shared layout keys.
Paths do not encode
Azure ML/Databricks technology or classification/regression/forecasting/vision task
names, so the same contract applies without copying data for each engine.

**Every CI train invocation generates a fresh `ci-<UUID>` lake `run_id`**, including
provider retries. The source runtime and its explicit `snapshot_id` remain unchanged.
The effective runtime is saved alongside the unique bundle and used for validation,
rendering and verified registration. Cloud preparation belongs to that run; re-running
training must not publish over the immutable snapshot. To intentionally assign an ID
yourself, use `train --lake-run-id <new-reviewed-execution-id>`; do not reuse an ID for
different work. Snapshot creation/publication is a separate explicit core flow, not
an automatic part of CI. No zip, folder-marker or migration uploads are introduced.
Azure ML preparation writes to `training/runs/<run_id>/prepared`, not snapshot gold.
Direct Azure ML output bindings do not provide an immutable create-only lock: manually
reusing a run ID can overwrite backend outputs. A rendered snapshot path is only a
reference until that snapshot has been separately published and verified.

Inference additionally requires an explicit immutable `model_version`, not `latest`
or a mutable registry alias. Review late observed labels under the contract's separate
`feedback` area, joined by stable request/entity IDs: predictions never automatically
become training labels. Streaming checkpoints belong to stable `pipeline_id` and
`pipeline_version`, not the current model/run. Use a new pipeline version for incompatible
query/schema changes, and review model feature-schema compatibility before a rollout.

Neither enabling the object nor running validation queues a job. Existing explicit
train/deploy actions, authenticated identities and approval gates remain unchanged.
Storage strings contain endpoints and names only; credentials belong to managed
identity or separately configured secret providers. Keep generated runtimes private.

## One-time runner provisioning (manual only)

Use an administrator-maintained Python 3.12 virtual environment and a reviewed,
immutable source commit. Preinstall Azure CLI, PowerShell 7, and the selected CLI v2
extension. The orchestration code itself uses the standard library; YAML contract
tests use PyYAML from the core package.

The helper below is optional and **never called by the workflows**:

```powershell
# Explicit administrator installation, not an instruction to run during validation:
python "$templates\scripts\bootstrap.py" --package usecase_code\50-ml-model-factory `
  --venv usecase_code\50-ml-model-factory\.venv --azure --kaggle --train `
  --ml-extension-version 2.38.1
```

The helper installs the selected extras from the local source (`[azure,kaggle,train,dev]`)
and checks the exact `ml` extension version. Omit unneeded `--train`/`--kaggle` extras.
It does not use the legacy SDK. The core pyproject specifies compatible dependency
ranges; it is **not a transitive lockfile**. For fully reproducible runner provisioning,
use your approved resolved constraints/lock and immutable source revision instead of
an unconstrained fresh resolution. These CI templates never upgrade an existing runner.

`pythonPath`/`python_path` can point outside the checkout to a centrally maintained
environment. Checkout uses `clean: false` so an explicitly provisioned in-repository
venv is not deleted. Keep trusted self-hosted runner workspaces isolated; do not allow
untrusted fork/pull-request code to execute with credentials. Editable installation
keeps the package aligned with the checked-out source.

## Validation

```powershell
& $python -m unittest discover -s "$templates\tests" -v
```

Tests cover YAML contracts, offline separation, explicit approval, status/timeout
handling, CLI pin mismatch, stale receipts, failed quality gates, legacy runtimes,
unique lake execution IDs and unchanged snapshot IDs. No cloud
submission/deployment or dependency installation is performed by tests. Live service
RBAC, OIDC federation, private connectivity, approved runner state, dataset licensing
and model quality remain environment-specific prerequisites.

See `ado\readme.md` and `github\readme.md` for manual installation. ADF child templates,
separate ARM payloads and SHIR prerequisites are in `dataops\azure-datafactory`.