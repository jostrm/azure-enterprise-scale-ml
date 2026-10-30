# online

**Purpose:** Serve low-latency request/response inference through an endpoint.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates exist for 42 of 42 leaf combinations below; each leaf README lists its route, prerequisites and limitations.

[Scenario configuration](../../user-config/model/scenarios/readme.md) | [Shared execution code](../../accelerator/readme.md) | [Start here](../../readme.md)

## References and examples

## Serving behavior

Online inference is request/response. Availability, latency and scale-to-zero support depend on the selected hosting service and configuration; no endpoint is created by this folder.

## Run this use case with an AI assistant

Copy a prompt, replace the `<...>` placeholders, and paste it into the assistant. Every assistant has a **demo data** prompt and a **your own data** prompt. [How these prompts work](../../../40-agent-factory/readme.md#run-the-use-cases-with-an-ai-assistant) explains where to paste them and what each assistant can and cannot do.

### AI Factory Agent Chat

Paste into the [AI Factory Agent Chat](../../../40-agent-factory/40-aifactory-agent/readme.md) with the **Project** explanation view and your scope selected. It answers from the indexed documentation with citations; the Factory actions panel only prepares a reviewable plan, which a person approves.

<details>
<summary><b>Demo data</b></summary>

```text
Explain the online ML templates in usecase_code/50-ml-model-factory/usecase-type/online for my scope <project001-dev>: the task folders (classification, regression, timeseries-forecasting, computer-vision), the technology branches (notebook, azure-automl, azureml-pipeline, databricks-notebook, databricks-azureml-pipeline-step), which combinations are tested in Azure, and how the diabetes teaching scenario runs locally before any cloud step. Cite the documentation.

Then, in the Factory actions panel (it prepares a reviewable plan; a person approves it):
/create-ml-model-oftype-for-project
  type: <classification | regression | timeseries-forecasting | computer-vision>
  serving_mode: online
  project_resource_id: </subscriptions/<sub>/resourceGroups/<project-rg>/providers/Microsoft.MachineLearningServices/workspaces/<workspace>>
(This works only if the platform team has approved a workload profile for this type; otherwise the chat reports the blocker.) Training submission is not a registered model or a deployment; those stay separate, approved steps.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
I want a online model on our own data: <describe the dataset, the target column, the features and the prediction we need>. Recommend the task folder and technology branch, explain how to write my own scenario JSON in usecase_code/50-ml-model-factory/user-config/model/scenarios (task, target, features, split, quality gates, dataset provider), where to put the data, and which runtime.local.json settings the cloud route needs. Cite the documentation.

Then, in the Factory actions panel (it prepares a reviewable plan; a person approves it):
/create-ml-model-oftype-for-project
  type: <task folder>
  serving_mode: online
  project_resource_id: </subscriptions/<sub>/resourceGroups/<project-rg>/providers/Microsoft.MachineLearningServices/workspaces/<workspace>>
(This works only if the platform team has approved a workload profile for this type; otherwise the chat reports the blocker.)
```

</details>

### GitHub Copilot and Claude Code (one prompt for both)

The same prompt works in **GitHub Copilot** (VS Code Chat in *Agent* mode) and **Claude Code** (run `claude` in the repository root). Use a machine that is signed in to Azure CLI and connected to the AI Factory private network. Both assistants read this repository's `AGENTS.md`.

<details>
<summary><b>Demo data</b></summary>

```text
Run the online ML use case from usecase_code/50-ml-model-factory/usecase-type/online locally with the diabetes teaching scenario, end to end, before any cloud step.

First read AGENTS.md, then usecase_code/50-ml-model-factory/readme.md, usecase_code/50-ml-model-factory/user-config/readme.md, usecase_code/50-ml-model-factory/usecase-type/online/readme.md, usecase_code/50-ml-model-factory/usecase-type/online/classification/notebook/readme.md.

1. Check prerequisites and report anything missing: Python 3.10-3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. In usecase_code/50-ml-model-factory, create the root `.venv` and install the package with the extras the README shows, then run `--help`, `validate --scenario user-config\model\scenarios\diabetes.json` and the unit tests.
3. The data is not bundled. Ask me for the path to my reviewed local diabetes.csv (Kaggle Pima Indians Diabetes, CC0, downloaded by me) and copy it to data\in\diabetes.
4. Run `prepare`, `train` and `evaluate` into a fresh run folder under ml-environment\outputs\diabetes, and show me the metrics and the quality gate. If the gate fails, stop; do not lower thresholds.
5. Run `sample-requests`, then `online-test` with online-request.json against the local model, exactly as the README shows, and show the response.
6. Then explain the cloud route for this pattern (Azure ML managed online endpoint (`serving-render` / `serving-deploy` / `serving-invoke` / `serving-delete --kind online`)) and run only its preview. Do not add --execute or submit a billed run without my approval.
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
Run the online ML use case from usecase_code/50-ml-model-factory/usecase-type/online on my own dataset.

First read AGENTS.md, then usecase_code/50-ml-model-factory/readme.md, usecase_code/50-ml-model-factory/user-config/readme.md, usecase_code/50-ml-model-factory/usecase-type/online/readme.md.

1. Check prerequisites and report anything missing: Python 3.10-3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Install the model factory in its root `.venv` as the README shows.
3. My data: <local path to CSV or Parquet>. Task: <classification | regression | forecasting | image task>. Target column: <target>. Features: <list or "all other columns">. Categorical: <list>. Sensitive: <list>. Copy it into data\in\<my-scenario>.
4. Create user-config\model\scenarios\<my-scenario>.json with a distinct name, modelled on the closest existing scenario, keep its quality gates, set the dataset provider and license notes honestly, and run `validate`. Show me the file.
5. Run `prepare`, `train` and `evaluate` locally into a fresh folder and show me the metrics and quality gate.
6. Run `sample-requests`, then `online-test` with online-request.json against the local model, exactly as the README shows, and show the response.
7. For the cloud route (Azure ML managed online endpoint (`serving-render` / `serving-deploy` / `serving-invoke` / `serving-delete --kind online`)), help me create runtime.local.json from the examples with my existing workspace <name>, compute <name> and storage, and run only the previews. Stop before --execute or any billed submission.

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
Build a "Real-time prediction" form prototype for a diabetes-risk teaching model (label it "teaching example, not clinical decision support").
- A form with the 8 inputs (Pregnancies, Glucose, BloodPressure, SkinThickness, Insulin, BMI, DiabetesPedigreeFunction, Age), validation and sensible defaults.
- A "Predict" button that calls one function, predict(features), returning a mock prediction, probability and model version after a short delay.
- A response panel with the request and response JSON, plus the latency.
- A history of the last 10 requests.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
Build the same "Real-time prediction" form for my model <model name>.
Inputs: <paste feature names, types and allowed ranges>. Output: <prediction label and meaning>.
Use these example requests and responses as mock data: <paste 3-5 JSON request/response pairs>.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

## Video walkthrough tutorial - TBA

A video walkthrough tutorial, recorded by a person, will be published here soon. It shows how to run this code, step by step, to achieve the result described in this README.
