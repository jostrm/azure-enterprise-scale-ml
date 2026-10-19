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
(requires `enableAIFactoryMCP`; `aifactoryMcpImage`/`aifactoryMcpApiImage` are then not needed).

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
2. An Entra admin creates the MCP API app registration with app role `AiFactory.Mcp.Read` and
   sets `aifactoryMcpEntraAppId`. Pipelines never write Microsoft Graph: after the gateway exists,
   the step prints the exact app-role assignment the admin must grant to the gateway identity
   and to each identity in `aifactoryMcpClassicApimResourceIds`.
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
