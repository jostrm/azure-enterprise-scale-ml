# How to guide: publish a Foundry agent to Teams and Copilot

These PowerShell wrappers publish an **existing native Foundry agent** through
Microsoft's REST publishing flow, including projects with private networking:

- `publich-agent-to-TEAMS.ps1`
- `publich-agent-to-Copilot.ps1`

The `publich` spelling is intentional. Both wrappers use **one joint publication
to Microsoft Teams and Microsoft 365 Copilot/Copilot Chat**. They differ in access
instructions, not in the agent or catalog audience. Running both with unchanged
settings does not intentionally create two publications. These scripts do not
create a Copilot Studio agent.

## What you need

- PowerShell 7 (`pwsh`), Python 3 and Azure CLI (`az`) on PATH.
- An existing, tested native Foundry agent with its own identity.
- Foundry User (formerly Azure AI User), or equivalent permissions, on its project.
- VPN/private DNS access to the project when public network access is disabled.
- An Azure CLI sign-in to the project's tenant.
- This folder's three script files together, including `FoundryPublishing.psm1`.
- The matching `azure-enterprise-scale-ml` checkout/submodule. The Python backend
  lives there; copying only the two `.ps1` files to an unrelated folder is not enough.

No Azure Bot resource, client secret, or account-wide public access is created.
The native bot-registration feature must be available for the Foundry project;
the wrapper reports service errors instead of silently switching deployment models.

## 1. Open the scripts folder

For the installed Spider checkout:

```powershell
Set-Location 'C:\code\code_py_25\002_demo\azuredevops\aifactory-spider-001\aifactory\automation\projectteam\foundry-publishing'
```

For another consumer repository, use its
`aifactory\automation\projectteam\foundry-publishing` folder.

## 2. Copy and edit the example configuration

Keep your edited configuration outside the source checkout:

```powershell
$configFolder = Join-Path $HOME 'Documents\FoundryPublishing'
New-Item -ItemType Directory -Path $configFolder -Force | Out-Null
$config = Join-Path $configFolder 'publish-agent.config.json'
Copy-Item -LiteralPath '.\publish-agent.config.example.json' -Destination $config
notepad.exe $config
```

Do not repeat `Copy-Item` over an already edited configuration. All IDs and names
in the shipped example are **fictional**. Replace these values in `dev`:

| Key | What to enter |
|---|---|
| `tenantId` | Your Foundry project's Microsoft Entra tenant/directory ID. |
| `botFoundryProjectResourceId` | The full ARM ID of the **project**, including `/projects/<project-name>`, not just the account ID or HTTPS endpoint. |
| `botFoundryAgentName` | The existing agent's exact name, not its version ID, blueprint ID or identity GUID. |

The project ARM ID has this structure:

```text
/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.CognitiveServices/accounts/<foundry-account>/projects/<foundry-project>
```

The subscription is derived from that explicit ARM ID. The scripts do not run
`az account set`. Leave `enableBotService` and `enableAIFoundry` as `"true"` and
the deletion flags as `"false"`. Here, `enableBotService` gates the publishing
integration; it does not cause the wrapper to deploy a separate Azure Bot.

`botEnableM365PublicEndpoint` documents the publishing intent. The publishing
wrapper always previews the required M365 Activity-route exception for your
approval; setting this field to false is **not** a way to publish a private agent
without that route. Use `-WhatIf`, or decline confirmation, to avoid changes.

This minimal file is for the publishing wrappers, **not** a complete AI Factory
infrastructure deployment configuration. It contains no credentials.

### Using an existing Spider project configuration instead

You can skip copying the example if your project already contains the target:

```powershell
$config = 'C:\code\code_py_25\002_demo\azuredevops\aifactory-spider-001\azurefactory\factories\spider-swedencentral\scalesets\001\projects\project001\variables.json'
```

Check `botFoundryAgentName` before continuing. This project's current configuration
may select the isolated validation agent rather than the agent you intend to publish.
You can use `-AgentName 'your-existing-agent'` as an explicit override.

## 3. Connect and sign in

Connect the existing project VPN first, then sign in if necessary:

```powershell
$settings = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
az login --tenant $settings.dev.tenantId
```

Complete sign-in yourself. Do not put an access token, password or client secret
in the config file, profile or command history. A valid sign-in does not bypass
private networking; the project endpoint must also be reachable.

## 4. Preview without making changes

For Teams:

```powershell
.\publich-agent-to-TEAMS.ps1 -ConfigFile $config -WhatIf
```

For Microsoft 365 Copilot:

```powershell
.\publich-agent-to-Copilot.ps1 -ConfigFile $config -WhatIf
```

Review the resolved subscription, tenant, project, agent, effective active version,
scope, endpoint/authentication diff and outgoing metadata.

`-WhatIf` performs reads only: no metadata prompts, profile/receipt creation,
endpoint change, registration, publication or ZIP generation. A first preview
can report `status: blocked` with missing metadata; this is expected until you
supply the required publishing information.

## 5. Publish after reviewing the metadata

Run **one** of the following without `-WhatIf`:

```powershell
.\publich-agent-to-TEAMS.ps1 -ConfigFile $config
# Or:
.\publich-agent-to-Copilot.ps1 -ConfigFile $config
```

On first use, the script asks for missing publication metadata:

| Prompt | What to supply |
|---|---|
| `shortDescription` | An approved one-sentence description, at most 80 characters. |
| `fullDescription` | An approved description, at most 4,000 characters. |
| `developerName` | The real publisher/developer name, at most 32 characters. |
| `developerWebsiteUrl` | Your publisher's real HTTPS website. |
| `privacyUrl` | The applicable approved HTTPS privacy statement. |
| `termsOfUseUrl` | The applicable approved HTTPS terms of use. |

The display name defaults to the agent name. Previously published or saved
approved metadata is reused when available. Do not use fictional example URLs
as your organization's legal policies.

**`-ConfigFile` selects the project and agent; it is not the publication metadata
profile.** The metadata above is prompted separately and saved after you approve.
Do not add those fields to the project JSON expecting them to populate the prompts.

The final confirmation shows the exact information being sent to **both**
Microsoft 365/Teams catalogs, the audience and any authorization/network change.
Metadata becomes visible to the selected audience, and subsequent agent responses
are processed by Microsoft 365. Decline if the preview is not what you intended.

For a private project, the approved change enables only the Activity Protocol
route with Microsoft-managed source IP filtering and channel authorization.
Account public access, other protocols and active-version routing are preserved.

## 6. Choose who can use it

The default is `Shared`: initially visible only to you under **Your agents**, with
`BotServiceRbac` checks. Sharing a Teams chat/link does not automatically grant
other people the required Foundry permissions.

For organization-wide publication:

```powershell
.\publich-agent-to-TEAMS.ps1 -ConfigFile $config -Scope Tenant -WhatIf
.\publich-agent-to-TEAMS.ps1 -ConfigFile $config -Scope Tenant
```

`Tenant` requests tenant-wide channel authorization and Microsoft 365 admin
approval. It can replace an existing Bot Service authorization scheme; inspect
the displayed change. After approval, look under **Built by your org**.
The same scope option works with the Copilot wrapper.

## 7. Check access in the target application

Open the agent store in Teams or Microsoft 365 Copilot, find the agent in the
appropriate section, and start a conversation. Confirm that it replies.

Published/submitted IDs are not proof of installation or a working conversation.
Tenant policies, pending admin approval and store caching can delay availability.
The scripts do not send a test message automatically.

## Repeat runs, profiles and recovery

Approved nonsecret metadata and receipts are saved next to your config under:

```text
.foundry-publish\<environment>-<agent-name>.profile.json
.foundry-publish\<environment>-<agent-name>.profile.receipt.json
```

This runtime directory ignores its own contents for Git. Profiles are bound to
the subscription, tenant, project, environment and agent. To change publication
metadata, edit the existing profile's `metadata` object, then preview again.
Do not change its target binding or add secrets. A repeat with unchanged settings
should not submit another app version; metadata updates use a reviewed new version.

If publication times out or returns an uncertain result, inspect the receipt and
live state before doing anything else. Only after resolving that uncertainty:

```powershell
.\publich-agent-to-TEAMS.ps1 -ConfigFile $config -RetryUncertain -WhatIf
```

Actual retry still requires a fresh confirmation. Do not delete receipts just
to bypass recovery safeguards. If a lock remains after a crash, confirm that no
publisher is running and inspect the receipt before removing that lock.

## Other useful options

| Option | Purpose |
|---|---|
| `-Environment dev` | Default environment. `stage`/`test` and `prod` require an explicit target in the relevant JSON section; the example leaves them unconfigured. |
| `-AgentName 'name'` | Override the configured existing agent. |
| `-ProjectResourceId '/subscriptions/.../projects/...'` | Override the full project ARM ID; tenant/subscription checks still apply. |
| `-ProfileFile 'C:\path\approved.profile.json'` | Select a different existing scoped metadata profile. Not a replacement for `-ConfigFile`. |
| `-RepositoryRoot 'C:\path\to\consumer'` | Locate the backend if automatic checkout/submodule discovery fails. |
| `-NonInteractive -Confirm:$false` | Automation only, with complete approved metadata and prior review. Missing metadata fails instead of prompting. |

From a project directory whose config is named `variables.json`, you can omit
`-ConfigFile` entirely. Invoke the wrapper by its absolute path while staying in
that project directory.

## Troubleshooting

| Symptom | Action |
|---|---|
| Cannot find the Python backend | Keep this folder in the consumer repository with its current `azure-enterprise-scale-ml` submodule, or supply `-RepositoryRoot`. |
| Public access disabled / endpoint unreachable | Connect the correct VPN and fix private DNS/reachability; do not enable account-wide public access. |
| Missing target or subscription mismatch | Replace every fictional ID/name and use the full project resource ID. Check the selected environment. |
| Missing metadata under `-WhatIf` | Run interactively without `-WhatIf` to enter the fields, then review and confirm. |
| Registration feature unavailable | Check Foundry's native registration feature availability for this project. The scripts do not fall back to creating another Bot. |
| `pending_admin` | Ask the Microsoft 365 administrator to review the request; do not claim organization-wide availability yet. |
| `pending_verification` or an uncertain attempt | Inspect the live publish defaults and saved receipt before retrying. |

## Microsoft references

- [Publish private-network agents using REST](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/publish-copilot-virtual-network?view=foundry)
- [Publishing troubleshooting](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/troubleshoot-publish-copilot)
