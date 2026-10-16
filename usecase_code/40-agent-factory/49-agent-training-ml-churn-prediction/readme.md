# 49 Agent training: ML churn prediction

**Purpose:** a Foundry prompt agent that creates, trains, retrains and batch-scores Azure ML use cases
through the ESML v2 SDK (`azure_esml`) and the canonical model-factory engines.
**Status:** Local tests and an offline from-scratch reproduction run without Azure. Every Azure write
needs an approved plan plus explicit flags. Passing tests is not evidence of a live run; see
[Evidence](#evidence).

The agent supports exactly two use cases:

| Use case | Model | What the agent does |
| --- | --- | --- |
| `49-agent-training-ml-churn-prediction` | `M49` | Creates a telco-churn use case from scratch, copied from the model factory's `batch/classification/azureml-pipeline` churn custom-pipeline template. It always uses **synthetic data**, publishes it to the AI Factory shared lake, trains it, registers it and runs batch scoring. |
| `air-passengers` | `M05` | Retrains the existing model with its reviewed binding and data, then compares the result with the champion. A kept champion is a valid outcome, and scoring then uses the champion. |

The churn data comes from `ml_model_factory.synthetic` (generator `telco-churn`, seed 49, 7,043 rows,
hash-pinned provenance). The factory's Kaggle churn dataset remains license-gated and is never used.

## How it works

```text
main.py ask --demo uc1|uc2
  Foundry prompt agent (existing chat deployment)  ->  function calls
  local, plan-bound MLRuntime (this process, over the private network)
    create_usecase_from_template  scenario + rollout binding + generated notebook + synthetic data
                                  -> esml-v2 lake-seed staging -> create-only shared-lake publication
    start_training / start_retraining   AzureMLRollout: prepare -> register definitions -> train
                                        (resumes the recorded job; never resubmits) -> gated registration
    run_batch_inference                 GOLD_INFERENCE plan -> create-only unlabeled gold input
                                        -> one pipeline job -> lake predictions
```

Foundry Playground cannot execute these client-side functions. Use `main.py ask` instead.

**Naming.** The model number sets `naming_style=model-prefix`, which gives these names:

- Data assets, experiments and display names: `M49_<use case>_...`
- Model: `M49_49_agent_training_ml_churn_prediction`
- Components and endpoints: lowercase `m49_` / `m49-`, because Azure requires lowercase names
- Job IDs: unchanged `esml-<sha>` values, which act as idempotency keys

**Lake paths.** All paths are on the `esml_shared_lake` datastore, below `mlops/v1/`:

- Master: `master/environments/<env>/datasets/<use case>/versions/<data version>`
- Project input: `projects/project<NNN>/environments/<env>/datasets/<use case>/versions/<data version>/in`
- Use case: `projects/project<NNN>/environments/<env>/usecases/<use case>/...`

The use-case folder has the same name as this example folder.

**Consumer copy.** The orange ML factory receives these files:

- The scenario `user-config/model/scenarios/49-agent-training-ml-churn-prediction.json`.
- A generated notebook in `usecase-type/batch/classification/azureml-pipeline/`.
- A local `user-config/esml-rollout.local.json` binding. It contains the reviewed
  `"model_numbers": {"49-agent-training-ml-churn-prediction": 49}`.

The notebook and the agent share the same AzureMLRollout receipt folder, so neither path can submit
a job twice.

## Prerequisites

- An orange repository with the canonical ML model factory layout, refreshed with
  `python -m ml_model_factory instantiate`.
- The reviewed `esml-rollout.local.json` that contains the custom `air-passengers` binding.
- The champion run's `training-completion.json`.
- Existing Azure ML computes, environment and datastore. This example never creates them.
- Data-plane access for the signed-in operator. This example never assigns roles.
- Private connectivity (VPN) to the Azure ML workspace, the shared lake and the Foundry project.

## Setup

```powershell
cd usecase_code\40-agent-factory\49-agent-training-ml-churn-prediction   # or the orange copy
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt "..\..\..\esml-v2[train,storage,dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

In an orange repository, install the ESML SDK from `<orange>\azure-enterprise-scale-ml\esml-v2`.
The ESML build has no editable mode, so reinstall the SDK after you change `esml-v2` or the
model-factory engines.

## Reproduce from scratch

All generated configuration, data, receipts and transcripts stay outside this template.

```powershell
$py = ".\.venv\Scripts\python.exe"
# 1. Consumer configuration (offline).
& $py main.py init-config --factory-config <orange>\aifactory\agent-factory\config.json `
  --target <target> --orange-root <orange> --reviewed-rollout <reviewed esml-rollout.local.json> `
  --champion-receipts <champion run folder> --project-endpoint <Foundry project endpoint> `
  --model-deployment <existing chat deployment> --state-root <orange>\aifactory\agent-factory\49-agent-training-ml-churn-prediction\.agent-factory `
  --output <orange>\aifactory\agent-factory\49-agent-training-ml-churn-prediction\config.json
# 2. Offline reproduction: synthesize, prepare, train, evaluate and score locally.
& $py main.py offline --config <config> --work <new empty folder>
# 3. Project copy and local lake staging (no Azure writes).
& $py main.py prepare-local --config <config>
# 4. Read-only private-connectivity and prerequisite checks.
& $py main.py preflight --config <config>
# 5. Plan every name, path, run and write. Approve the printed SHA-256 before running anything live.
& $py main.py plan --config <config> [--fresh]
```

**Live commands.** Run these only after the plan is approved. Each one needs
`--approved-plan <plan.json> --plan-sha256 <hex> --apply --allow-paid`:

```powershell
& $py main.py deploy --config <config> <approval flags>
& $py main.py ask --config <config> --demo uc1 <approval flags>   # create, train and score M49
& $py main.py ask --config <config> --demo uc2 <approval flags>   # retrain and score M05
```

`create-usecase`, `train`, `retrain` and `infer` run the same operations without the model, using
`--usecase`. Rerunning any of them resumes from receipts and does not repeat a recorded job.

If an inference job fails, the next `infer` starts a fresh attempt (`-a2` to `-a5`). Each attempt has
its own receipts and its own create-only lake paths, so a recorded job is never resubmitted.

- `--fresh` plans the next immutable data version (`aif49-synth-v<n>`). Published versions are never
  overwritten or deleted.
- The commands keep the workstation awake during bounded Azure waits. After a sleep or VPN drop,
  rerun the same command with the same approved plan.

## Safety boundaries

**Writes that need approval:**

- Create-only lake publication.
- Azure ML data assets and pipeline components.
- Training and inference jobs.
- Gated model registration.
- One owned agent version.
- Paid model responses.

**What it never does:**

- Create, resize or delete compute.
- Create endpoints.
- Change roles, networking, private endpoints, DNS, Search, SKUs or model deployments.
- Delete models, data or lake files.

The tools accept only enumerated use cases. They expose no shell, free paths or delete operations.
Tool results are redacted before they reach the model.

## Evidence

Local unit tests and `offline` show that the code paths and synthetic data work. They do not prove any
of the following:

- A shared-lake publication.
- A completed Azure ML job.
- A registered model.
- A deployed agent.

Live evidence is stored as redacted receipts and transcripts in the consumer state folder, and the
Azure ML receipts are stored in the ML factory's `ml-environment\outputs`. Retraining an unchanged
seasonal-naive model on unchanged data normally keeps the champion.

[Agent Factory](../readme.md) | [ML model factory](../../50-ml-model-factory/readme.md) | [ESML v2](../../../esml-v2)
