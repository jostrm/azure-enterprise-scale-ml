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

## Rules

- **project001 Dev only.** Another project number fails the step; Stage/Prod runs skip it.
- **Dependencies are validated, never ignored:** the MCP requires `enableContainerApps` and
  `enableAIFoundry` plus digest-pinned `aifactoryMcpImage`/`aifactoryMcpApiImage` and
  `aifactoryMcpEntraAppId`; the gateway requires `enableAIFoundry`; registration requires both
  and outbound VNet integration (`aiGatewaySkuOutboundSubnetId`, or an adopted gateway that has it).
- **`false` never deletes.** Turning a flag off skips the step; existing resources stay.
- **Ownership.** Writes only target resources tagged `aifactory-integration: mcp-ai-gateway`
  (or the tool server carrying its managed-by marker). A foreign resource with a derived name is
  refused. An adopted gateway is never modified; only its child model provider and tool server are.
- **Read-before-write, no deletes, no blind retries.** Re-runs reuse the MCP↔API key, skip existing
  role assignments and leave unchanged resources untouched.
- **Private.** The Container Apps environment must be internal; ingress is reachable only inside the VNet.

## Prerequisites (one-time, outside the pipeline)

1. Build and push the MCP and Factory API images to a registry in the project subscription and
   set their digest-pinned references.
2. An Entra admin creates the MCP API app registration with app role `AiFactory.Mcp.Read` and
   sets `aifactoryMcpEntraAppId`. Pipelines never write Microsoft Graph: after the gateway exists,
   the step prints the exact app-role assignment the admin must grant to the gateway identity.
3. For registration with a new gateway, provide a subnet delegated to `Microsoft.Web/serverFarms`
   (/27 or larger) with outbound 443 to Storage and AzureKeyVault, DNS and the MCP's private IP.
4. Grant callers **AI Gateway Tools User** on the tool server and sign in with Microsoft Entra ID.

## Run locally

```bash
export enableAIFactoryMCP=true enableAIGatewaySKU=true addAIFactoryMCP2AIGatewaySKU=true  # plus the project variables
python deploy.py validate          # offline
python deploy.py plan              # Azure GET only
python deploy.py apply --apply     # owned writes
```

The JSON report lists every create/update/unchanged action, the MCP and tool-server URLs and any
Entra prerequisite. It never contains secrets. AI Gateway preview pricing applies to the gateway; the
MCP app runs one replica of two 0.5 vCPU / 1 GiB containers.
