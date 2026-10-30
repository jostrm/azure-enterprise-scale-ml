# AI Factory MCP and AI Gateway SKU (project001 Dev)

A late, opt-in step of the normal project pipeline (ADO
`jobs/job-aifactory-mcp-ai-gateway.yaml`, task `71-aifactory-mcp-ai-gateway`; GitHub
Actions step "Deploy AI Factory MCP and AI Gateway SKU (project001 Dev)"). It runs in
the `foundry` phase after the project's Foundry, Container Apps and private Azure MCP
steps, and only when at least one flag is `true` and no delete-all flag is set.

| Flag | Effect |
|---|---|
| `enableAIFactoryMCP` | Hosts the governed, read-only AI Factory MCP as a private Container App (`aifactory-mcp-p001-dev`) in the project's internal Container Apps environment, with the Factory API as a sidecar and a dedicated user-assigned identity (`mi-aifactory-mcp-p001-dev`, AcrPull only). |
| `enableAIGatewaySKU` | Creates an owned AI Gateway (SKU `AIGateway`, system-assigned identity) in the project resource group, or adopts `aiGatewaySkuResourceId`. Grants the gateway identity **Azure AI User** on the project Foundry account and adds that account as a Foundry model provider. |
| `addAIFactoryMCP2AIGatewaySKU` | Registers the MCP as gateway tool server `aifactory-mcp-p001-dev` with the exact read-only allow list `aifactory_factory_health`, `aifactory_factory_capabilities`, `aifactory_factory_skills`, managed-identity credentials for `aifactoryMcpEntraAppId`, and adds the gateway identity to the MCP's application callers. |

`aifactoryMcpClassicApimResourceIds` (optional, comma-separated `Microsoft.ApiManagement/service`
resource IDs, requires `enableAIFactoryMCP`) adds each classic APIM gateway's system-assigned
identity to the MCP's application callers, after the project and native AI Gateway identities.
Use it for an APIM that fronts the MCP with `apim-mcp-server.bicep` and
`authentication-managed-identity`. The step only reads those APIMs: a missing APIM or one without
a system-assigned identity fails before any write, and an identity already in the list is not
added twice (the MCP refuses duplicate callers).

## Publish the MCP on the AI gateway pipeline's classic APIM (`addAIFactoryMCP2APIM`)

`addAIFactoryMCP2APIM: "true"` (requires `enableAIFactoryMCP`) wires the classic APIM that the
AI gateway pipeline manages (`apimGatewaySubscriptionId`, `apimGatewayResourceGroup`,
`apimGatewayServiceName`) to the MCP with no hand steps:

1. **Project pipeline (this step):** the APIM joins the MCP callers exactly like an entry of
   `aifactoryMcpClassicApimResourceIds` (no need to list it twice). The report prints the
   `AiFactory.Mcp.Read` app-role prerequisite for its identity.
2. **AI gateway pipeline** (ADO `esml-infra-common/jobs/job-2-ai-gateway.yaml`, GitHub
   `infra-ai-gateway.yml`, step "Expose the AI Factory MCP on APIM", after the OpenAI pool):
   `deploy.py apim-parameters --output <file>` reads the MCP app and the APIM (GET only) and
   writes the `esml-common/ai-gateway/apim/apim-mcp-server.bicep` parameters; the pipeline then
   deploys them to the APIM resource group. The result is API `enterprise-scale-ai-factory`
   (`https://<apim>/enterprise-scale-ai-factory/mcp`, plain HTTP proxy, 60 requests/min per client IP,
   APIM managed-identity token for `aifactoryMcpEntraAppId`) and the client subscription
   `aifactory-mcp-client` scoped to that API.

Order for a new factory: an existing APIM with a system-assigned identity, then the project pipeline,
then the AI gateway pipeline. The launcher refuses with the next step to take while the MCP app does
not exist or does not list the APIM identity yet. Stage/Prod runs skip it (the MCP is Dev only).

## Adopt an MCP app deployed outside the pipeline (`aifactoryMcpContainerAppResourceId`)

An MCP app that was deployed another way (for example the pilot rollout `mcp/deploy/rollout.py`,
which made `aifactory-mcp-project001-dev` in Spider) can be adopted instead of creating
`aifactory-mcp-p001-dev` next to it. Set `aifactoryMcpContainerAppResourceId` to its resource ID
(requires `enableAIFactoryMCP` and `enableAIFoundry`; `enableContainerApps`, `aifactoryMcpImage` and `aifactoryMcpApiImage` are then not needed, because the app keeps its own environment and images).

- The app must be in the project resource group, must not carry this step's ownership tags (then
  it is already pipeline-managed: clear the variable), must have an `mcp` container with an
  `AIFACTORY_APPLICATION_AUTH_JSON` caller list, and must accept tokens for
  `aifactoryMcpEntraAppId`. Any mismatch fails before any write.
- The step selects the app's own Container Apps environment and applies the same private-network
  checks to it.
- **Only the caller lists grow:** missing project, native AI Gateway and classic APIM identities are
  appended to `AIFACTORY_APPLICATION_AUTH_JSON`, missing `factory.read` grants to
  `AIFACTORY_PILOT_CONFIG_JSON`. Existing callers stay. Images, identity, secrets, ingress, scale and
  tags are never changed. A change is one `PATCH` of the app template with a new revision suffix
  (`callers-<hash>`); with every caller present nothing is written.
- Both the native AI Gateway tool server and the APIM MCP API then point at the adopted app's URL.

To move to the pipeline-managed app instead, clear the variable and set the images: the step creates
`aifactory-mcp-p001-dev`; repoint the gateways (re-run both pipelines) before removing the old app by hand.

## Rules

- **project001 Dev only.** Another project number fails the step; Stage/Prod runs skip it.
- **Dependencies are validated, never ignored:** the MCP requires `enableContainerApps` and
  `enableAIFoundry` plus digest-pinned `aifactoryMcpImage`/`aifactoryMcpApiImage` and
  `aifactoryMcpEntraAppId`; the gateway requires `enableAIFoundry`; registration requires both
  and outbound VNet integration (`aiGatewaySkuOutboundSubnetId`, or an existing owned/adopted
  gateway that has it).
- Gateway-only runs discover the Foundry account without requiring MCP images, a Foundry project,
  model deployments, Search, storage or Container Apps. MCP-enabled runs retain those checks.
- Registration rejects missing outbound integration before gateway/MCP writes. An explicitly
  requested subnet must match an existing binding; this step never migrates it to another subnet.
  A read-only plan includes an owned gateway's planned subnet configuration without applying it.
  Omitting the optional gateway ID still selects its deterministic owned name, which may exist.
  A read distinguishes reuse from creation; an existing owned/adopted gateway may supply its
  read-validated subnet without the parameter. Missing integration fails before any mutation,
  not necessarily before reads. Invalid offline flag combinations and ID formats still fail
  before any Azure calls.
- **`false` never deletes.** Turning a flag off skips the step; existing resources stay.
- **Ownership.** Writes only target resources tagged `aifactory-integration: mcp-ai-gateway`
  (or the tool server carrying its managed-by marker). A foreign resource with a derived name is
  refused. An adopted gateway is never modified; only its child model provider and tool server are.
- **Read-before-write, no deletes, no blind retries.** Re-runs reuse the MCP↔API key, skip existing
  role assignments and leave unchanged resources untouched.
- Owned tool-server reconciliation checks the complete governed endpoint, exact endpoint count,
  protocol type, required flag, blocked tools and allowlist—not just the first endpoint's URL.
- **Private.** The Container Apps environment must be internal; ingress is reachable only inside the VNet.
  It must also have an **approved private endpoint**, which is how APIM and the AI Gateway reach the
  MCP; a missing one fails before any write. The Bicep that creates the environment owns that endpoint
  and its DNS record (`containerappsEnv.bicep` with `enableContainerApps`: `<environment>-pend`;
  `azureMcpServer.bicep` with `enableAzureMcpServer`: `<name>-pe`), registered in
  `privatelink.<region>.azurecontainerapps.io` (the zone in the common VNet resource group, or the hub's
  zone through its DNS policy when `centralDnsZoneByPolicyInHub` is true). This step only verifies them, so it never creates a
  second endpoint that would compete for the same record. A missing DNS zone group is reported as a
  prerequisite (the hub policy may add it a few minutes later); `outputs.mcp_private_endpoint_id` names
  the endpoint.

## Prerequisites (one-time, outside the pipeline)

1. Build and push the MCP and Factory API images to a registry in the project subscription and
   set their digest-pinned references.
2. An Entra admin creates the MCP API app registration (the secretless "MCP SP") with app role `AiFactory.Mcp.Read`,
   usually per project in one batch with `esml-util/29b-create-mcp-api-sp-for-projects.sh`, which stores its client ID
   in the seeding Key Vault as `esml-projectNNN-mcp-app-id`. Either set `aifactoryMcpEntraAppId`, or leave it empty and
   set `aifactory_mcp_AppID_seeding_kv_name` to that secret name: the pipelines read it from the seeding Key Vault
   (ADO step 03 exposes it as `$(<secret name>)`, GHA step 03 exports it). The AI gateway pipeline takes the audience
   from the MCP app itself. Pipelines never write Microsoft Graph: the step prints, for every
   caller (the Foundry project identity, the AI Gateway identity once it exists, and each classic
   APIM identity), the exact admin command that assigns the role with the Microsoft Graph Bicep
   template `environment_setup/aifactory/bicep/esml-common/ai-gateway/entra/aifactory-mcp-app-role.bicep`:

   ```bash
   az deployment group create --subscription <project-subscription> --resource-group <project-rg> \
     --name aifactory-mcp-app-role-<first 8 of the principal ID> \
     --template-file environment_setup/aifactory/bicep/esml-common/ai-gateway/entra/aifactory-mcp-app-role.bicep \
     --parameters mcpEntraAppId=<aifactoryMcpEntraAppId> callerPrincipalId=<caller object ID>
   ```

   The admin runs it from the accelerator root, once per new caller, signed in with Graph
   permissions `AppRoleAssignment.ReadWrite.All` and `Application.Read.All` (Bicep CLI 0.36.1+;
   extension `microsoftgraph/v1.0:1.0.0`). The resource group only records the deployment. No
   pipeline references the template.
3. For registration with a new gateway, provide a subnet delegated to `Microsoft.Web/serverFarms`
   (/27 or larger) with outbound 443 to Storage and AzureKeyVault, DNS and the MCP's private IP.
4. Grant callers **AI Gateway Tools User** on the tool server and sign in with Microsoft Entra ID.

## Run locally

```bash
export enableAIFactoryMCP=true enableAIGatewaySKU=true addAIFactoryMCP2AIGatewaySKU=true  # plus the project variables
python deploy.py validate          # offline
python deploy.py plan              # Azure GET only
python deploy.py apply --apply     # owned writes
python deploy.py apim-parameters --output apim-mcp.parameters.json  # AI gateway pipeline, GET only
```

The JSON report lists every create/update/unchanged action, the MCP and tool-server URLs and any
Entra prerequisite. It never contains secrets. AI Gateway preview pricing applies to the gateway; the
MCP app runs one replica of two 0.5 vCPU / 1 GiB containers.

## Run this use case with an AI assistant

Copy a prompt, replace the `<...>` placeholders, and paste it into the assistant. Every assistant has a **demo data** prompt and a **your own data** prompt. [How these prompts work](../readme.md#run-the-use-cases-with-an-ai-assistant) explains where to paste them and what each assistant can and cannot do.

> **Data:** this is an opt-in pipeline step with no dataset. The **your own data** prompts target your own project variables, an existing AI Gateway or an existing MCP app.

### AI Factory Agent Chat

Paste into the [AI Factory Agent Chat](../40-aifactory-agent/readme.md) with the **Project** explanation view and your scope selected. It answers from the indexed documentation with citations; the Factory actions panel only prepares a reviewable plan, which a person approves.

<details>
<summary><b>Demo data</b></summary>

```text
Explain the AI Factory MCP and AI Gateway SKU step in usecase_code/40-agent-factory/45-aifactory-mcp-gateway for my scope <project001-dev>: what `enableAIFactoryMCP`, `enableAIGatewaySKU`, `addAIFactoryMCP2AIGatewaySKU` and `addAIFactoryMCP2APIM` each do, which pipeline step runs them, the Entra app and caller roles, the outbound subnet, and the costs. Cite the documentation and tell me which flags are enabled for my project.

Then, in the Factory actions panel (read-only):
/get-aifactory-settings
/get-aifactory-health
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
We already have an AI Gateway <resource id> and want to register the AI Factory MCP on it, and also expose it on our APIM <service name> in <resource group>. Explain, with citations, which variables to set (aiGatewaySkuResourceId, aifactoryMcpEntraAppId, the APIM variables, the outbound subnet), how callers get the AiFactory.Mcp.Read role, and which read-only tools are allowed.
```

</details>

### GitHub Copilot and Claude Code (one prompt for both)

The same prompt works in **GitHub Copilot** (VS Code Chat in *Agent* mode) and **Claude Code** (run `claude` in the repository root). Use a machine that is signed in to Azure CLI and connected to the AI Factory private network. Both assistants read this repository's `AGENTS.md`.

<details>
<summary><b>Demo data</b></summary>

```text
Plan the AI Factory MCP and AI Gateway SKU step in usecase_code/40-agent-factory/45-aifactory-mcp-gateway for project001 Dev and, after my approval, apply it.

First read AGENTS.md, then usecase_code/40-agent-factory/45-aifactory-mcp-gateway/readme.md.

1. Check prerequisites and report anything missing: Python 3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Tell me whether my team normally runs this through the project pipeline (ADO task 71-aifactory-mcp-ai-gateway or the GitHub Actions step). If so, prepare the variable changes as a diff for review instead of running anything locally.
3. For a local run, set enableAIFactoryMCP=true, enableAIGatewaySKU=true and addAIFactoryMCP2AIGatewaySKU=true plus my project variables in the shell only, never in committed files.
4. Run `python deploy.py validate` (offline) and `python deploy.py plan` (Azure GET only) and summarize every create, update and unchanged action and any Entra prerequisite.
5. After my approval, run `python deploy.py apply --apply`, then show the MCP and tool-server URLs from the JSON report.
6. Remind me that AI Gateway preview pricing applies and that setting a flag to false never deletes anything.

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
Plan the AI Factory MCP step in usecase_code/40-agent-factory/45-aifactory-mcp-gateway against my existing AI Gateway, APIM and project settings.

First read AGENTS.md, then usecase_code/40-agent-factory/45-aifactory-mcp-gateway/readme.md.

1. Check prerequisites and report anything missing: Python 3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Use my values: aiGatewaySkuResourceId <existing gateway id>, aifactoryMcpEntraAppId <app id>, aiGatewaySkuOutboundSubnetId <subnet id, /27 or larger, delegated to Microsoft.Web/serverFarms>, and, for APIM, apimGatewaySubscriptionId <id>, apimGatewayResourceGroup <rg>, apimGatewayServiceName <name>. Show me where each one belongs (pipeline variables or shell environment).
3. Run `python deploy.py validate` and `python deploy.py plan` and confirm the plan adopts my existing resources instead of creating new ones.
4. For APIM, run `python deploy.py apim-parameters --output apim-mcp.parameters.json` (GET only) and explain which AI gateway pipeline step consumes it.
5. Only after my approval, run `python deploy.py apply --apply`.

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
Build an "AI Factory MCP tool catalog" prototype for agent developers.
- A list of read-only MCP tools: aifactory_factory_health, aifactory_factory_capabilities, aifactory_factory_skills, each with a description and a "Try it" button that shows a realistic mock JSON response.
- A status card for the deployment: MCP app (private Container App), AI Gateway tool server, APIM exposure, each with a status badge and a last-updated time.
- A "How to call it" panel with the steps an agent needs (Entra app role AiFactory.Mcp.Read, AI Gateway Tools User), with no real URLs or secrets.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
Build the same "AI Factory MCP tool catalog" prototype, using my own deployment report.
Here is the JSON report from `deploy.py plan` (it contains no secrets; replace URLs with placeholders if needed): <paste JSON>.
Render each action as a row (create | update | unchanged) with its resource, and show any Entra prerequisite as a warning card.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

## Video walkthrough tutorial - TBA

A video walkthrough tutorial, recorded by a person, will be published here soon. It shows how to run this code, step by step, to achieve the result described in this README.
