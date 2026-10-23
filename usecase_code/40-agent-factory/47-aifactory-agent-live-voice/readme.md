# AI Factory Agent live voice (any project, Dev)

A late, opt-in step of the normal project pipeline (ADO `jobs/job-aifactory-agent-live-voice.yaml`,
task `72-aifactory-agent-live-voice`; GitHub Actions step "Deploy AI Factory Agent live voice (any project, Dev)").
It runs in the `foundry` phase after the Factory Chat Agent step ([46-factory-chat-agent](../46-factory-chat-agent/deploy.py),
task `70-factory-chat-agent`) and the AI Factory MCP step, and only when `enableAIFactoryAgentLiveVoice` is
`true` and no delete-all flag is set. It deploys the code in [40-aifactory-agent](../40-aifactory-agent/readme.md)
with Azure Voice Live: a voice card with a pulsing orb that listens, thinks and speaks.

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
  owned Foundry Agent from step 70 must exist; the project needs one AI Search service, a data storage
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

## Three ways to run it

| Route | How |
|---|---|
| Azure DevOps Run pipeline UI | `infra-project-genai`, Deployment mode `manual`, keep `XXX` / `not-applicable` / `{}`, and under **Stages to run** select only Dev. The project's variables file sets the two flags and the inputs above. |
| GitHub Actions Run workflow UI | `infra-project.yml` with environment `dev`; the repository variables `ENABLE_FACTORY_CHAT_AGENT`, `ENABLE_AI_FACTORY_AGENT_LIVE_VOICE` and `AIFACTORY_AGENT_*` set the step. |
| Terminal (no pipeline) | `./ADO-azurefactory.sh add-aifactory-agent-chat --to-project 001` plans; add `--apply` to deploy. `GHA-azurefactory.sh` takes the same options. |

The terminal route reads the project's own variables file (`azurefactory/factories/*/scalesets/*/projects/projectNNN/variables.json`
in a registered layout, otherwise `aifactory/variables.json`, or `--config <file>`), switches the chat and voice options on
for that run only, and runs step 70's and this step's launchers with your signed-in Azure CLI identity.
`--agent-config <file>` overrides `aifactoryAgentConfigFile`; `--without-voice` deploys only the Foundry Agent.

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
