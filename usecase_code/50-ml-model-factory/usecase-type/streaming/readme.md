# streaming

**Purpose:** Process arriving events continuously or in micro-batches.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates exist for 40 of 42 leaf combinations below; each leaf README lists its route, prerequisites and limitations. Unsupported leaves explain why and name the supported alternative.

[Scenario configuration](../../user-config/model/scenarios/readme.md) | [Shared execution code](../../accelerator/readme.md) | [Start here](../../readme.md)

## References and examples

# Streaming use cases

Process events from Azure Event Hubs using Azure Databricks Structured Streaming or Azure Stream Analytics with a supported model inference integration. Produce near-real-time results and optionally save them to storage. Streaming inference does not necessarily imply continuous model training.

## Run this use case with an AI assistant

Copy a prompt, replace the `<...>` placeholders, and paste it into the assistant. Every assistant has a **demo data** prompt and a **your own data** prompt. [How these prompts work](../../../40-agent-factory/readme.md#run-the-use-cases-with-an-ai-assistant) explains where to paste them and what each assistant can and cannot do.

### AI Factory Agent Chat

Paste into the [AI Factory Agent Chat](../../../40-agent-factory/40-aifactory-agent/readme.md) with the **Project** explanation view and your scope selected. It answers from the indexed documentation with citations; the Factory actions panel only prepares a reviewable plan, which a person approves.

<details>
<summary><b>Demo data</b></summary>

```text
Explain the streaming ML templates in usecase_code/50-ml-model-factory/usecase-type/streaming for my scope <project001-dev>: the task folders (classification, regression, timeseries-forecasting, computer-vision), the technology branches (notebook, azure-automl, azureml-pipeline, databricks-notebook, databricks-azureml-pipeline-step), which combinations are tested in Azure, and how the diabetes teaching scenario runs locally before any cloud step. Cite the documentation.

Then, in the Factory actions panel (it prepares a reviewable plan; a person approves it):
/create-ml-model-oftype-for-project
  type: <classification | regression | timeseries-forecasting | computer-vision>
  serving_mode: streaming
  project_resource_id: </subscriptions/<sub>/resourceGroups/<project-rg>/providers/Microsoft.MachineLearningServices/workspaces/<workspace>>
(This works only if the platform team has approved a workload profile for this type; otherwise the chat reports the blocker.) Training submission is not a registered model or a deployment; those stay separate, approved steps.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
I want a streaming model on our own data: <describe the dataset, the target column, the features and the prediction we need>. Recommend the task folder and technology branch, explain how to write my own scenario JSON in usecase_code/50-ml-model-factory/user-config/model/scenarios (task, target, features, split, quality gates, dataset provider), where to put the data, and which runtime.local.json settings the cloud route needs. Cite the documentation.

Then, in the Factory actions panel (it prepares a reviewable plan; a person approves it):
/create-ml-model-oftype-for-project
  type: <task folder>
  serving_mode: streaming
  project_resource_id: </subscriptions/<sub>/resourceGroups/<project-rg>/providers/Microsoft.MachineLearningServices/workspaces/<workspace>>
(This works only if the platform team has approved a workload profile for this type; otherwise the chat reports the blocker.)
```

</details>

### GitHub Copilot and Claude Code (one prompt for both)

The same prompt works in **GitHub Copilot** (VS Code Chat in *Agent* mode) and **Claude Code** (run `claude` in the repository root). Use a machine that is signed in to Azure CLI and connected to the AI Factory private network. Both assistants read this repository's `AGENTS.md`.

<details>
<summary><b>Demo data</b></summary>

```text
Run the streaming ML use case from usecase_code/50-ml-model-factory/usecase-type/streaming locally with the diabetes teaching scenario, end to end, before any cloud step.

First read AGENTS.md, then usecase_code/50-ml-model-factory/readme.md, usecase_code/50-ml-model-factory/user-config/readme.md, usecase_code/50-ml-model-factory/usecase-type/streaming/readme.md, usecase_code/50-ml-model-factory/usecase-type/streaming/classification/notebook/readme.md.

1. Check prerequisites and report anything missing: Python 3.10-3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. In usecase_code/50-ml-model-factory, create the root `.venv` and install the package with the extras the README shows, then run `--help`, `validate --scenario user-config\model\scenarios\diabetes.json` and the unit tests.
3. The data is not bundled. Ask me for the path to my reviewed local diabetes.csv (Kaggle Pima Indians Diabetes, CC0, downloaded by me) and copy it to data\in\diabetes.
4. Run `prepare`, `train` and `evaluate` into a fresh run folder under ml-environment\outputs\diabetes, and show me the metrics and the quality gate. If the gate fails, stop; do not lower thresholds.
5. Run `sample-requests` to produce events.jsonl, then run `stream-score --source jsonl` locally over it (see `--help` for the arguments) and summarize the micro-batches, checkpoints and any quarantined events.
6. Then explain the cloud route for this pattern (scheduled Azure ML micro-batch jobs (`stream-job`) or Event Hubs with Azure AD identity (never connection strings)) and run only its preview. Do not add --execute or submit a billed run without my approval.
7. This is a teaching example, not clinical decision support.

Rules:
- Follow AGENTS.md. Use only commands and flags documented in the READMEs above; do not invent new ones.
- Run offline and read-only steps first. Before any command that writes to Azure (`--apply`, `--execute`, or a script the README says writes directly) or makes a billed model call, show me the exact command and its target and wait for my "yes".
- Never enable public network access, change networking or RBAC, approve all pending private links at once, edit integrity hashes, or print or store tokens, keys or SAS.
- Never overwrite an existing configuration file, and never commit configuration, journals, .venv folders or data.
- If a prerequisite is missing (private network, role, quota, upstream step), stop and tell me the blocker instead of working around it.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
Run the streaming ML use case from usecase_code/50-ml-model-factory/usecase-type/streaming on my own dataset.

First read AGENTS.md, then usecase_code/50-ml-model-factory/readme.md, usecase_code/50-ml-model-factory/user-config/readme.md, usecase_code/50-ml-model-factory/usecase-type/streaming/readme.md.

1. Check prerequisites and report anything missing: Python 3.10-3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Install the model factory in its root `.venv` as the README shows.
3. My data: <local path to CSV or Parquet>. Task: <classification | regression | forecasting | image task>. Target column: <target>. Features: <list or "all other columns">. Categorical: <list>. Sensitive: <list>. Copy it into data\in\<my-scenario>.
4. Create user-config\model\scenarios\<my-scenario>.json with a distinct name, modelled on the closest existing scenario, keep its quality gates, set the dataset provider and license notes honestly, and run `validate`. Show me the file.
5. Run `prepare`, `train` and `evaluate` locally into a fresh folder and show me the metrics and quality gate.
6. Run `sample-requests` to produce events.jsonl, then run `stream-score --source jsonl` locally over it (see `--help` for the arguments) and summarize the micro-batches, checkpoints and any quarantined events.
7. For the cloud route (scheduled Azure ML micro-batch jobs (`stream-job`) or Event Hubs with Azure AD identity (never connection strings)), help me create runtime.local.json from the examples with my existing workspace <name>, compute <name> and storage, and run only the previews. Stop before --execute or any billed submission.

Rules:
- Follow AGENTS.md. Use only commands and flags documented in the READMEs above; do not invent new ones.
- Run offline and read-only steps first. Before any command that writes to Azure (`--apply`, `--execute`, or a script the README says writes directly) or makes a billed model call, show me the exact command and its target and wait for my "yes".
- Never enable public network access, change networking or RBAC, approve all pending private links at once, edit integrity hashes, or print or store tokens, keys or SAS.
- Never overwrite an existing configuration file, and never commit configuration, journals, .venv folders or data.
- If a prerequisite is missing (private network, role, quota, upstream step), stop and tell me the blocker instead of working around it.
```

</details>

### Lovable

Lovable builds a hosted web front end. It cannot run this Python, sign in to your tenant or reach private AI Factory endpoints, so these prompts build a **prototype** with demo data or data you paste in. Paste only data you are allowed to share with an external service, and connect the prototype to the real result only through an API your platform team approves, never by enabling public access. Paste the **your own data** prompt as a follow-up message in the same Lovable project, after the demo prompt.

<details>
<summary><b>Demo data</b></summary>

```text
Build a "Streaming predictions" live dashboard prototype.
- A simulated event stream (one event per second) of mock sensor or customer events with an event ID and a timestamp.
- Micro-batches of 10 events: show each batch with its batch ID, checkpoint, number scored and number quarantined (invalid events).
- A live chart of predictions over time and a feed of the latest 20 scored events.
- Pause and resume controls, and a banner: "Streaming scoring does not mean continuous retraining".

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
Build the same "Streaming predictions" dashboard, replaying my own events.
Here are sample events as JSON lines: <paste 50-200 JSONL events>. Prediction field: <field>; timestamp field: <field>.
Replay them at <N> events per second in micro-batches of <M>, and flag events that are missing required fields <list> as quarantined.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

## Video walkthrough tutorial - TBA

A video walkthrough tutorial, recorded by a person, will be published here soon. It shows how to run this code, step by step, to achieve the result described in this README.
