# AI Factory Agent live voice (any project, Dev)

A late, opt-in step of the normal project pipeline (ADO `jobs/job-aifactory-agent-live-voice.yaml`,
task `72-aifactory-agent-live-voice`; GitHub Actions step "Deploy AI Factory Agent live voice (any project, Dev)").
It runs in the `foundry` phase after the Factory Chat Agent step ([46-factory-chat-agent](../46-factory-chat-agent/deploy.py),
task `70-factory-chat-agent`) and the AI Factory MCP step, as the last task of the project job (after the region
reports are published), and only when `enableAIFactoryAgentLiveVoice` is
`true` and no delete-all flag is set. It deploys the code in [40-aifactory-agent](../40-aifactory-agent/readme.md)
with Azure Voice Live: a voice card with a pulsing orb that listens, thinks and speaks.
Which voice technology it uses (always the Voice Live API; `speech_shell` with an Azure neural voice, or `realtime`
with a GPT realtime model such as `gpt-realtime-mini`) is explained in
[40-aifactory-agent, Live voice](../40-aifactory-agent/readme.md#live-voice-optional).

| Flags | Result |
|---|---|
| `enableFactoryChatAgent` only | The owned Foundry prompt Agent is created or updated by step 70. **This step does nothing.** |
| `enableFactoryChatAgent` + `enableAIFactoryAgentLiveVoice` | Step 70 creates the Agent; this step verifies it, builds the knowledge index and deploys the private chat web application with live voice. |
| `enableAIFactoryAgentLiveVoice` without `enableFactoryChatAgent` | The step fails with a clear message instead of ignoring the flag. |

| Input | Purpose |
|---|---|
| `modelGPTXName` | The project's existing chat model deployment (the same one step 70 uses); it must have succeeded. |
| `aifactoryAgentModelDeployment` | Optional: the agent's own model deployment for steps 70 and 72; empty uses `modelGPTXName`. Use it when the agent keeps a different model than the project. |
| `aifactoryAgentEntraAppId` | Client ID of the agent's Entra single-page-app registration (mandatory). |
| `aifactoryAgentReaderObjectIds` | Comma-separated Entra object IDs granted **read-only** chat access (mandatory, at most 20). |
| `aifactoryAgentContainerAppsEnvironment` | Internal Container Apps environment name; empty selects the single one in the project resource group. |
| `aifactoryAgentVoiceName` | Speech voice; empty uses `en-US-Ava:DragonHDLatestNeural`. |
| `aifactoryAgentVoiceLanguages` | Comma-separated BCP-47 input languages; empty uses `en-US`. Swedish needs `sv-SE,en-US`. |
| `aifactoryAgentConfigFile` | Optional: your own agent configuration, a JSON file relative to the repository root (for example `aifactory/agent/project001-dev.json`), merged over the generated one. See below. |

## Rules

- **Any project, Dev only.** The project number comes from `project_number_000` (3 digits, 001-999). The app is
  `aifactory-agent-project<NNN>-dev` with the scope `project<NNN>-dev`; project001 keeps its existing app name.
  Stage/Prod runs skip the step.
- **Dependencies are validated, never ignored:** `enableAIFoundry` and `enableAISearch` must be `true`, and
  either `enableContainerApps` is `true` or `aifactoryAgentContainerAppsEnvironment` names an existing environment; the Entra app ID and reader object IDs must be GUIDs; the model
  deployment and a text-embedding deployment must have succeeded in the project Foundry account; the
  owned Foundry Agent from step 70 must exist; the project needs one AI Search service (with several, the one named ...prj<NNN>...; other services such as demos never receive the index), a data storage
  account and exactly one (or the named) **internal** Container Apps environment.
- **This step never creates the Agent or a model deployment**, and it refuses an Agent that the
  Enterprise Scale AI Factory does not own.
- **Your configuration is the only customer-specific artefact.** The step generates a baseline configuration
  (read-only grants for the listed readers, writes disabled, voice on). `aifactoryAgentConfigFile` is merged over
  it, so you can keep realtime voice, language profiles, extra grants, cost settings and limits in git. It must
  not set `scopes`, `azure`, `location`, `auth.client_id`, `auth.audience`, the repository roots or
  `voice.enabled`; those always come from the pipeline and Azure, and the step fails if the file sets them.
  The path must stay inside the repository checkout.
- **An operator-deployed app is never replaced by the bare baseline.** The step creates or updates an app it
  created itself (tag `aifactory-integration: live-voice`). An app first deployed with
  `40-aifactory-agent/deploy.py` (tag `managed-by: enterprise-scale-ai-factory-agent`) is adopted only when
  `aifactoryAgentConfigFile` is set, because that file is then the reviewed source of its richer configuration.
  An app the agent does not own is never touched.
- **`false` never deletes.** Turning the flag off skips the step; the app, index, identity and roles
  stay. Delete-all runs skip this step, and the launcher rejects that combination if run directly.
- **Owned writes only.** The step runs the agent's own commands (`ingest`, `deploy.py --apply`), which
  refuse resources they do not own. It only *reads* Azure itself. Pipelines never write Microsoft Graph.
- **Private.** The application stays in the internal Container Apps environment. Voice reaches Azure
  Voice Live from the backend with the application's managed identity, never from the browser.

## What the step runs

1. An isolated Python environment under `$RUNNER_TEMP` (or `AGENT_TEMPDIRECTORY`/the system temp
   folder, never the checkout) with `requirements.lock.txt`, then the Linux wheels for the offline bundle.
2. `ingest` — creates/reconciles the owned Search index (**billed** embedding calls).
3. `deploy.py --apply --app-name aifactory-agent-project<NNN>-dev --integration live-voice` — owned identity,
   Voice Live roles, the private Container App (tagged as created by this step) and the knowledge refresh job.

## Voice Live roles

Microsoft documents keyless Voice Live access as **Cognitive Services User** and **Foundry User** (formerly
Azure AI User) on the Foundry account. `deploy.py` assigns them to the application identity from a separate
template (`40-aifactory-agent/infra/voice-roles.bicep`), only when voice is enabled, and never removes them.
They are broader than the project-scoped runtime role in `identity.bicep`, which stays untouched. Check in a
test environment whether a narrower scope is enough before using voice in production.

## Data roles of the deploying identity

Contributor and User Access Administrator carry no data actions, so the pipeline identity could deploy the
resources and still get 403 reading the agent, the index or a blob. Before their first data-plane call, steps
70 (`46-factory-chat-agent`) and 72 (this step) grant the deploying **service principal** these roles, once
(deterministic assignment names), and then wait about two minutes for RBAC to take effect:

| Role | Scope | Used by |
|---|---|---|
| Foundry User | project Foundry account | step 70 (agent versions), step 72 (agent check, embeddings) |
| Storage Blob Data Contributor | container `aifactory-agent` of the project data storage | step 72 (index state, deployment bundle) |
| Search Index Data Contributor | the project AI Search service | step 72 (knowledge index documents) |

An existing assignment at that scope or above (or an equivalent data role) counts, so nothing is written twice.
`plan` lists the roles it would grant. A signed-in user (the terminal launcher) is never granted roles: the
report names the role to request. The roles are never removed. The code is `agent_factory/deployer_access.py`.

## Prerequisites (one-time, outside the pipeline)

1. An Entra admin creates the agent's dedicated registration with
   `python -m aifactory_agent.browser_auth --config <config> --redirect-uri https://<application FQDN>/ --user-object-id <object id> --apply`
   (single-page app, delegated scope `access_as_user`, redirect URI = the application's exact HTTPS root).
   The token audience is the registration's client ID. Sign-in fails closed until this exists.
2. Enable `enableFactoryChatAgent` so step 70 creates the Foundry Agent, and deploy a text-embedding model.
3. The runner can reach the package feed, the project's private Foundry, Search and Storage endpoints.
4. Voice Live must be available in the Foundry account's region, and the application must resolve and
   reach the Foundry `services.ai.azure.com` private endpoint. See the agent readme's
   [Live voice](../40-aifactory-agent/readme.md#live-voice-optional) section for languages, cost and limits.

## Four ways to run it

| Route | How |
|---|---|
| Azure DevOps Run pipeline UI | `infra-project-genai`, Deployment mode `manual`, keep `XXX` / `not-applicable` / `{}`, and under **Stages to run** select only Dev. The project's variables file sets the two flags and the inputs above. |
| GitHub Actions Run workflow UI | `infra-project.yml` with environment `dev`; the repository variables `ENABLE_FACTORY_CHAT_AGENT`, `ENABLE_AI_FACTORY_AGENT_LIVE_VOICE` and `AIFACTORY_AGENT_*` set the step. |
| **Add-Factory-Agent** pipeline (agent only, fastest pipeline route) | Azure DevOps `esml-infra-project/add-factory-agent.yaml` or GitHub Actions `add-factory-agent.yml`: project number, the project's variables file, `plan` or `apply`. Runs only steps 70 and 72 (no infrastructure) with the Dev pipeline identity, which grants itself the agent's data roles. The project must already be deployed. |
| Terminal (no pipeline) | `./ADO-azurefactory.sh add-aifactory-agent-chat --to-project 001` (or `-addAIFactoryAgentChat -toProject 001`) plans; add `--apply` to deploy. `GHA-azurefactory.sh` takes the same options. |

The Add-Factory-Agent pipelines and the terminal route run the same entry (`bootstrap/lib/agent_chat_entry.py`). It reads the project's own variables file (`azurefactory/factories/*/scalesets/*/projects/projectNNN/variables.json`
in a registered layout, otherwise `aifactory/variables.json`, or `--config <file>`), switches the chat and voice options on
for that run only, and runs step 70's and this step's launchers with the signed-in Azure CLI identity (yours in a terminal, the pipeline's in Add-Factory-Agent).
`--agent-config <file>` overrides `aifactoryAgentConfigFile`; `--without-voice` deploys only the Foundry Agent.

## Faster deployments

A deployment used to take 27 to 34 minutes, about 20 of them re-embedding every knowledge document after any
repository change. Three things make repeated deployments fast, on every route:

| What | Effect |
|---|---|
| Embedding cache (`repository-embeddings.json` in the agent's own container) | Only new or changed documents are embedded; unchanged ones reuse their vector (keyed by embedding deployment, dimensions and exact text). |
| Skip the knowledge index | For code-only changes: `--skip-knowledge` (terminal), `refreshKnowledge: false` (Azure DevOps) or `refresh_knowledge: false` (GitHub Actions). The application keeps the last committed index; its refresh job updates it. |
| Cached operator environment | The virtual environment (in the runner's tool directory, or the laptop's temp folder) and the Linux wheels are reused while `requirements.lock.txt` is unchanged. |

## Run this launcher directly

```bash
export enableFactoryChatAgent=true enableAIFactoryAgentLiveVoice=true  # plus the project variables
python deploy.py validate          # offline
python deploy.py plan              # Azure GET only; writes the generated config to a temp folder
python deploy.py apply --apply     # owned writes through the agent's operator commands
```

The JSON report lists every step, the app and scope, the customer configuration file (if any), the resolved
model deployment and Container Apps environment, the verified Foundry Agent version, the knowledge index status
and the application's private FQDN. It never contains secrets or command output.

## Run this use case with an AI assistant

Copy a prompt, replace the `<...>` placeholders, and paste it into the assistant. Every assistant has a **demo data** prompt and a **your own data** prompt. [How these prompts work](../readme.md#run-the-use-cases-with-an-ai-assistant) explains where to paste them and what each assistant can and cannot do.

> **Data:** the voice agent answers from the AI Factory Agent's knowledge index (this repository's documentation). The **your own data** prompts adjust that corpus through `aifactoryAgentConfigFile`, and set your own voice and languages.

### AI Factory Agent Chat

Paste into the [AI Factory Agent Chat](../40-aifactory-agent/readme.md) with the **Project** explanation view and your scope selected. It answers from the indexed documentation with citations; the Factory actions panel only prepares a reviewable plan, which a person approves.

<details>
<summary><b>Demo data</b></summary>

```text
Explain the AI Factory Agent live voice step in usecase_code/40-agent-factory/47-aifactory-agent-live-voice for my scope <project001-dev>: the `enableFactoryChatAgent` and `enableAIFactoryAgentLiveVoice` flags, the Entra app and reader object IDs, the Voice Live region and private endpoint requirements, `speech_shell` versus `realtime`, the roles the pipeline grants, and what the JSON report shows. Cite the documentation and tell me which flags are enabled for my project.

Then, in the Factory actions panel (read-only):
/get-aifactory-settings
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
I want the voice agent to speak <language, e.g. Swedish and English> with the voice <voice name> and to also answer from <describe our own documentation>. Explain, with citations, how to set aifactoryAgentVoiceName and aifactoryAgentVoiceLanguages (for example sv-SE,en-US), what a customer aifactoryAgentConfigFile may and may not override (scopes, azure, auth and voice.enabled are not allowed), and how the knowledge index is refreshed.
```

</details>

### GitHub Copilot and Claude Code (one prompt for both)

The same prompt works in **GitHub Copilot** (VS Code Chat in *Agent* mode) and **Claude Code** (run `claude` in the repository root). Use a machine that is signed in to Azure CLI and connected to the AI Factory private network. Both assistants read this repository's `AGENTS.md`.

<details>
<summary><b>Demo data</b></summary>

```text
Turn on the AI Factory Agent with live voice for project001 Dev using usecase_code/40-agent-factory/47-aifactory-agent-live-voice.

First read AGENTS.md, then usecase_code/40-agent-factory/47-aifactory-agent-live-voice/readme.md, usecase_code/40-agent-factory/40-aifactory-agent/readme.md (Live voice).

1. Check prerequisites and report anything missing: Python 3.12, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Check the inputs: enableFactoryChatAgent, enableAIFactoryAgentLiveVoice, aifactoryAgentEntraAppId, aifactoryAgentReaderObjectIds (at most 20), the model and embedding deployments, the Container Apps environment, and Voice Live availability in my region. Report what is missing.
3. Prefer the pipeline: prepare the variable changes for my ADO variables.yaml or GitHub Actions variables as a diff for review. Do not commit or push without my approval.
4. For a local run of the launcher, set the flags in the shell only, then run `python deploy.py validate` (offline) and `python deploy.py plan` (Azure GET only) and summarize the plan.
5. Only after my approval, run `python deploy.py apply --apply` (owned writes, plus billed embedding calls during ingest) and show the private FQDN and knowledge index status from the JSON report.
6. Tell me how to open the private app over VPN and test it with: "How can a project team start using Foundry agents in an existing AI Factory?"

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
Turn on the AI Factory Agent with live voice using usecase_code/40-agent-factory/47-aifactory-agent-live-voice, with my own voice, languages and knowledge corpus.

First read AGENTS.md, then usecase_code/40-agent-factory/47-aifactory-agent-live-voice/readme.md, usecase_code/40-agent-factory/40-aifactory-agent/readme.md.

1. Check prerequisites and report anything missing: Python 3.12, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Set aifactoryAgentVoiceName to <voice, e.g. en-US-Ava:DragonHDLatestNeural> and aifactoryAgentVoiceLanguages to <e.g. sv-SE,en-US>.
3. Create a customer config file at <repo-relative path, e.g. aifactory/agent/project001-dev.json> and set aifactoryAgentConfigFile to it. In it, only adjust knowledge includes and excludes to add <my documentation globs>; do not set scopes, azure, location, auth or voice.enabled. Show me the file.
4. Run `python deploy.py validate` and `python deploy.py plan`, and confirm my config file is merged.
5. Only after my approval, run `python deploy.py apply --apply` (or prepare the pipeline variable diff instead), then show the knowledge index status.

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
Build a voice assistant prototype called "AI Factory Agent - live voice".
- A large animated orb with four states: idle, listening (pulsing), thinking (rotating), speaking (waveform).
- A push-to-talk button. Use the browser's built-in speech recognition and speech synthesis for the prototype, and mock answers about an AI Factory (for example "How can a project team start using Foundry agents?").
- A transcript panel that shows each spoken question and answer, with citations under every answer.
- A language selector: English (en-US), Swedish (sv-SE).

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
Build the same live-voice orb prototype for <company name> in <languages>.
Use my own question and answer pairs as mock answers: <paste rows of question | answer | source>.
Use my brand colors <colors> for the orb.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

## Video walkthrough tutorial - TBA

A video walkthrough tutorial, recorded by a person, will be published here soon. It shows how to run this code, step by step, to achieve the result described in this README.
