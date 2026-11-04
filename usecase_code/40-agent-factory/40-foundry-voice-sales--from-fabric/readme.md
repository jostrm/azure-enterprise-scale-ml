# Foundry voice sales — from Fabric

## 1. What

A configurable sales assistant for a **trusted single-user DSVM session**: browser text first, optional native live voice, answers grounded through your published Fabric Data Agent. No Azure resources are provisioned; no backend is deployed. Azure/Fabric/voice verification is **NOT RUN** by the local tests.

## 2. Architecture

`Browser (loopback) → local Python BFF → persisted Foundry prompt agent → query_sales_data(question) executed locally → Microsoft-hosted Fabric Data Agent MCP → permitted read-only sources`

Foundry executes the persisted `PromptAgentDefinition`; this is **not** a custom container-hosted agent or a bare model call. Fabric IQ is **not included**. See [architecture](docs/architecture.txt).

## 3. Prerequisites

- Python **3.13**, PowerShell **7.2+**, Git and Azure CLI; Node only for offline UI tests (no npm dependencies).
- Existing Foundry project and published prompt-agent name/version; a publisher needs an existing compatible model deployment. Optional Voice Live needs a verified compatible native realtime model/endpoint and approved processing region.
- Published Fabric Data Agent, paid F2+/P1+ capacity, tenant switches and source permissions; one signed-in Entra user per DSVM OS user. Azure RG RBAC does **not** grant Fabric access.
- **Foundry User** at project scope for this version-validating client; endpoint-only Agent Consumer is insufficient. Voice has additional resource-scoped permissions: see the access guide below.
- Approved DSVM DNS/TLS routing and, if required, private endpoints. Private support is conditional, not a promise: read [access and networking](docs/access-and-networking.txt).

## 4. DSVM quickstart

Work inside your copied template, for example `<consumer-root>\aifactory-usecase-code\40-agent-factory\40-foundry-voice-sales--from-fabric`. Do not work from an administrator's personal environment.

```powershell
.\Start-FoundryVoiceSales.ps1                         # Check: offline, no installs
.\Start-FoundryVoiceSales.ps1 -Action Setup           # Local .venv; locked package install
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env privately using the table below, then:
.\Start-FoundryVoiceSales.ps1 -Action Validate        # Offline configuration check
```

Setup may download packages; it never provisions or contacts Azure resources. For Azure actions, sign in **as yourself** in a separate terminal using `az login --tenant "<tenant-id>"`. The backend checks the configured tenant/subscription explicitly; the script never changes the Azure CLI default account.

No agent version yet? Diagnose/Connectivity/Discover accept a blank version; a publisher runs the separate Publish action below before Validate or Start.

## 5. Environment values: where to find them

| `.env` key | Approved source |
|---|---|
| `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | Entra tenant overview; Azure subscription overview |
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project overview: project endpoint, not a portal URL |
| `FOUNDRY_AGENT_NAME`, `FOUNDRY_AGENT_VERSION` | Existing published prompt agent; exact version from publisher |
| `FOUNDRY_MODEL_DEPLOYMENT` | Existing Foundry model deployment; needed only by Publish |
| `FABRIC_MCP_URL` | Published Fabric Data Agent MCP URL: `https://api.fabric.microsoft.com/v1/mcp/workspaces/<workspace-guid>/dataagents/<data-agent-guid>/agent`, or the exact approved workspace-private endpoint |
| `DOMAIN_CONFIG_PATH` | Local domain file, relative to the selected `.env` directory; default `config/domain.json`. Consumer overrides can use `config/domain.local.json` |
| `MCP_TOOL_NAME`, `MCP_QUESTION_ARGUMENT` | Optional constraints copied from reviewed **Discover** output; never guess a Fabric tool name/schema |
| `AZURE_RESOURCE_GROUP`, `AZURE_EXPECTED_USER`, `TEAM_GROUP_ID` | Optional consumer/admin-provided context and expected user; group ID is informational, not app authentication |
| `VOICE_ENABLED` | `false` until text succeeds and voice prerequisites are approved |
| `VOICE_ENDPOINT`, `VOICE_MODEL`, `VOICE_NAME` | Approved Voice Live endpoint, verified available native realtime model, and compatible voice; no guessed model/deployment default |
| `VOICE_API_VERSION` | Pinned `2026-07-15`; do not substitute an older event schema |

Never put tokens in `.env`, browser storage, notebooks, logs, or source control. Existing private `.env` and domain overrides belong to the consumer.

## 6. Choose PowerShell or notebook

**PowerShell** (all Azure calls require explicit `-AllowAzure`):

```powershell
.\Start-FoundryVoiceSales.ps1 -Action Diagnose -AllowAzure
.\Start-FoundryVoiceSales.ps1 -Action Connectivity -AllowAzure # Add -RequirePrivate if required
.\Start-FoundryVoiceSales.ps1 -Action Discover -AllowAzure
.\Start-FoundryVoiceSales.ps1 -Action Smoke -AllowAzure -Question "<approved known-answer sales question>"
.\Start-FoundryVoiceSales.ps1 -Action Start -AllowAzure -OpenBrowser
# Later, close only this template's owned local server:
.\Start-FoundryVoiceSales.ps1 -Action Stop
.\Start-FoundryVoiceSales.ps1 -Action Test             # Python + Node, offline
```

`Text -AllowAzure -Question "..."` sends one grounded question. `Smoke` checks diagnostics/discovery/text, **not voice**. `Start` binds `127.0.0.1:8765`; choose `-Port 8766` for another instance and optional `-EnvFile "<absolute-path>"`. Check/Validate/Stop/Test do not require Azure consent.

**Notebook:** open [quickstart.ipynb](quickstart.ipynb) using the existing VS Code Jupyter extension and an already working Python 3.13 kernel to execute its explicitly enabled Setup cell. That cell calls `Setup -Notebook`, installing the complete `requirements-notebook.lock.txt` (including `ipykernel`) only into `.venv`. If you have no working notebook kernel, first run `.\Start-FoundryVoiceSales.ps1 -Action Setup -Notebook` in PowerShell. Then select the template's `.venv` interpreter and rerun notebook configuration. No global kernel registration or automatic global installs are needed or permitted. Ordinary `Setup` stays lightweight; `-Notebook` is valid only with Setup. Run All defaults to no Azure, installs, publication, or server launch. Use this route **instead of** repeating the remaining PowerShell workflow.

**Publisher-only write, separate from every startup:**

```powershell
.\Start-FoundryVoiceSales.ps1 -Action Publish -AllowAzure
```

This creates a Foundry prompt-agent version only. Set the returned `FOUNDRY_AGENT_VERSION` in `.env`, then Validate. Ordinary consumers use an administrator-provided version and skip publication.

## 7. Success

- Offline checks/tests pass; Start reports local health. **Neither proves cloud access.**
- Discover finds the published Fabric question tool. A known-answer text question returns the correct permitted source result through the persisted Foundry agent.
- Optional voice: the DSVM browser captures a real microphone, plays the grounded answer, and interruption stops playback correctly. Preserve the authoritative grounded transcript; native speech is provisional.

Each OS user runs their own instance and Azure CLI identity; Fabric applies **that user's** actual permissions. Loopback, same-origin checks and a session cookie do **not** authenticate other OS users. Shared/untrusted multi-user hosts and team-shared web-server deployment are unsupported.

## 8. Troubleshoot

Start with [troubleshooting](docs/troubleshooting.txt). For a missing RDP microphone, check Windows Sound input and Edge site permission; remote audio redirection is not assumed. **Use text fallback and do not claim voice passed.** Never resolve permissions by broadening Fabric access or guessing endpoints/roles.
