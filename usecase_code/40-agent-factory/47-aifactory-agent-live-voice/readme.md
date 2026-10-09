# AI Factory Agent live voice (project001 Dev)

A late, opt-in step of the normal project pipeline (ADO `jobs/job-aifactory-agent-live-voice.yaml`,
task `72-aifactory-agent-live-voice`; GitHub Actions step "Deploy AI Factory Agent live voice (project001 Dev)").
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
| `aifactoryAgentEntraAppId` | Client ID of the agent's Entra single-page-app registration (mandatory). |
| `aifactoryAgentReaderObjectIds` | Comma-separated Entra object IDs granted **read-only** chat access (mandatory, at most 20). |
| `aifactoryAgentContainerAppsEnvironment` | Internal Container Apps environment name; empty selects the single one in the project resource group. |
| `aifactoryAgentVoiceName` | Speech voice; empty uses `en-US-Ava:DragonHDLatestNeural`. |
| `aifactoryAgentVoiceLanguages` | Comma-separated BCP-47 input languages; empty uses `en-US`. Swedish needs `sv-SE,en-US`. |

## Rules

- **project001 Dev only.** Another project number fails the step; Stage/Prod runs skip it.
- **Dependencies are validated, never ignored:** `enableContainerApps`, `enableAIFoundry` and
  `enableAISearch` must be `true`; the Entra app ID and reader object IDs must be GUIDs; the model
  deployment and a text-embedding deployment must have succeeded in the project Foundry account; the
  owned Foundry Agent from step 70 must exist; the project needs one AI Search service, a data storage
  account and exactly one (or the named) **internal** Container Apps environment.
- **This step never creates the Agent or a model deployment**, and it refuses an Agent that the
  Enterprise Scale AI Factory does not own.
- **`false` never deletes.** Turning the flag off skips the step; the app, index, identity and roles
  stay. Delete-all runs skip this step, and the launcher rejects that combination if run directly.
- **Read-only access.** Generated grants contain only `knowledge.read` and `factory.read` for the
  listed users; factory writes stay disabled. No secrets are generated, stored or printed.
- **Owned writes only.** The step runs the agent's own commands (`ingest`, `deploy.py --apply`), which
  refuse resources they do not own. It only *reads* Azure itself. Pipelines never write Microsoft Graph.
- **Private.** The application stays in the internal Container Apps environment. Voice reaches Azure
  Voice Live from the backend with the application's managed identity, never from the browser.

## What the step runs

1. An isolated Python environment under `$RUNNER_TEMP` (or `AGENT_TEMPDIRECTORY`/the system temp
   folder, never the checkout) with `requirements.lock.txt`, then the Linux wheels for the offline bundle.
2. `ingest` — creates/reconciles the owned Search index (**billed** embedding calls).
3. `deploy.py --apply` — owned identity, Voice Live roles, the private Container App and the knowledge
   refresh job. The generated configuration sets `voice.enabled`.

## Voice Live roles

Microsoft documents keyless Voice Live access as **Cognitive Services User** and **Foundry User** (formerly
Azure AI User) on the Foundry account. `deploy.py` assigns them to the application identity from a separate
template (`40-aifactory-agent/infra/voice-roles.bicep`), only when voice is enabled, and never removes them.
They are broader than the project-scoped runtime role in `identity.bicep`, which stays untouched. Check in a
test environment whether a narrower scope is enough before using voice in production.

## Prerequisites (one-time, outside the pipeline)

1. An Entra admin creates the agent's single-page-app registration (Application ID URI
   `api://<client-id>`, delegated scope `access_as_user`) and registers the application's
   exact HTTPS root (`https://<application FQDN>/`) as its SPA redirect URI. Sign-in fails closed
   until this exists.
2. Enable `enableFactoryChatAgent` so step 70 creates the Foundry Agent, and deploy a text-embedding model.
3. The runner can reach the package feed, the project's private Foundry, Search and Storage endpoints.
4. Voice Live must be available in the Foundry account's region, and the application must resolve and
   reach the Foundry `services.ai.azure.com` private endpoint. See the agent readme's
   [Live voice](../40-aifactory-agent/readme.md#live-voice-optional) section for languages, cost and limits.

## Run locally

```bash
export enableFactoryChatAgent=true enableAIFactoryAgentLiveVoice=true  # plus the project variables
python deploy.py validate          # offline
python deploy.py plan              # Azure GET only; writes the generated config to a temp folder
python deploy.py apply --apply     # owned writes through the agent's operator commands
```

The JSON report lists every step, the resolved model deployment and Container Apps environment, the
verified Foundry Agent version, the knowledge index status and the application's private FQDN. It never
contains secrets or command output.
