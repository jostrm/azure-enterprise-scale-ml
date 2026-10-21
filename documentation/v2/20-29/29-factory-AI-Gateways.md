# 29. AI Gateways in the AI Factory

The AI Factory supports three gateway options in front of models and the [AI Factory MCP](./29-factory-MCP.md).
They can be combined; each is opt-in.

| | Native AI Gateway SKU | Classic APIM with AI policies | Kong AI gateway |
|---|---|---|---|
| What | Azure API Management SKU `AIGateway` (the new AI Gateway, `ai.gateway.azure.com`) | An existing API Management service (Developer, Basic, Standard, Premium or a v2 tier) | Kong Gateway OSS in Azure Container Instances |
| Where | Project resource group (project001 Dev) | Any resource group you name (`apimGatewayResourceGroup`) | Its own `*-kong-*` resource group in the common VNet |
| Created by | Project pipeline step 71 (creates or adopts) | You (the pipeline configures an existing APIM), or the AI gateway pipeline with opt-in [managed provisioning](#managed-apim-opt-in) | AI gateway pipeline |
| Pipeline | Project pipeline, foundry phase | AI gateway pipeline (`infra-ai-gateway`) | AI gateway pipeline (`infra-ai-gateway`) |
| Models | Foundry account as a model provider (managed identity) | Azure OpenAI backend pool with 429 circuit breakers | Routes to Azure OpenAI or Foundry (private endpoint), or to APIM |
| MCP | Tool server `aifactory-mcp-p001-dev` (`addAIFactoryMCP2AIGatewaySKU`) | API `enterprise-scale-ai-factory` (`addAIFactoryMCP2APIM`) | Not built in |

## Native AI Gateway SKU

| Variable | GHA | Meaning |
|---|---|---|
| `enableAIGatewaySKU` | `ENABLE_AI_GATEWAY_SKU` | Create (or adopt) the AI Gateway, grant its identity **Azure AI User** on the project Foundry account and add that account as a model provider. Requires `enableAIFoundry`. |
| `aiGatewaySkuResourceId` | `AI_GATEWAY_SKU_RESOURCE_ID` | Adopt an existing AI Gateway instead of creating one (it is never modified; only its model provider and tool server are). |
| `aiGatewaySkuOutboundSubnetId` | `AI_GATEWAY_SKU_OUTBOUND_SUBNET_ID` | Outbound VNet integration (subnet delegated to `Microsoft.Web/serverFarms`, /27 or larger). Needed to reach the private MCP. |
| `addAIFactoryMCP2AIGatewaySKU` | `ADD_AI_FACTORY_MCP_2_AI_GATEWAY_SKU` | Register the MCP as a read-only tool server (allow-list `factory_health`, `factory_capabilities`, `factory_skills`) and add the gateway identity to the MCP callers. Requires `enableAIFactoryMCP` and `enableAIGatewaySKU`. |

The tool server is visible in the AI Gateway portal; callers need the **AI Gateway Tools User** role on it.
Details: [MCP step readme](../../../usecase_code/40-agent-factory/45-aifactory-mcp-gateway/readme.md).

## Classic APIM with AI policies

The AI gateway pipeline configures an **existing** APIM (`ENABLE_APIM` does not create one). It deploys an Azure
OpenAI backend pool, a token guard, 429-aware circuit breakers and the API policy, from
[`esml-common/ai-gateway/apim`](../../../environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/README.md).
Optional policies give it the features of the native AI Gateway: client-IP and per-user (validated Entra `oid`)
limits, Entra token validation, token metrics and a semantic cache.

| Variable | GHA | Meaning |
|---|---|---|
| `ENABLE_APIM` | `ENABLE_APIM` | Deploy the OpenAI pool, policies and API on the existing APIM. |
| `apimGatewaySubscriptionId`, `apimGatewayResourceGroup`, `apimGatewayServiceName` | `APIM_GATEWAY_*` | Which APIM. It needs a system-assigned managed identity. |
| `apimGatewaySku`, `apimGatewaySkuCapacity` | `APIM_GATEWAY_SKU*` | SKU and units (no in-place move between classic and v2). |
| `apimGatewayApiId`, `apimGatewayApiPath`, `apimGatewayBackendPoolName` | `APIM_GATEWAY_*` | API and pool names. |
| `apimGatewayAggregateTpm`, `apimGatewayCallerTpm`, `apimGatewayRetryCount` | `APIM_GATEWAY_*` | Token limits and retries. |
| `apimGatewayBackendsJson` | `APIM_GATEWAY_BACKENDS_JSON` | The backend accounts (JSON array). |
| `apimGatewayAssignOpenAIUserRole`, `apimGatewayManagedIdentityPrincipalId` | `APIM_GATEWAY_*` | Optional role assignment for the APIM identity on the backends. |
| `addAIFactoryMCP2APIM` | `ADD_AI_FACTORY_MCP_2_APIM` | Publish the AI Factory MCP on this APIM (below). |

**The MCP on the classic APIM.** With `addAIFactoryMCP2APIM: "true"` (and `enableAIFactoryMCP`):

1. The project pipeline adds this APIM's identity to the MCP callers and prints the admin role command.
2. The AI gateway pipeline step "Expose the AI Factory MCP on APIM" (after the OpenAI pool) reads the MCP and the
   APIM (GET only) and deploys `apim-mcp-server.bicep`: a plain HTTP proxy API at
   `https://<apim>/enterprise-scale-ai-factory/mcp` (60 requests per minute per client IP, the APIM managed-identity
   token for the MCP SP) and the client subscription `aifactory-mcp-client`. It refuses, naming the next step, until
   the MCP exists and lists the APIM identity. Stage and Prod skip it, because the MCP runs only in Dev.

Pipeline guide: [`infra-ai-gateway.md`](../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/infra-ai-gateway.md).

### Managed APIM (opt-in)

By default the AI gateway pipeline only configures an APIM you already have. To have it **create** a private
StandardV2 APIM, or to configure an existing one only after a reviewed what-if, turn on the reviewed runner.
Nothing changes until you do.

| Variable | GHA | Meaning |
|---|---|---|
| `apimGatewayManagedProvisioning` | `APIM_GATEWAY_MANAGED_PROVISIONING` | `"true"` (with `ENABLE_APIM`) runs APIM through the reviewed runner instead of the classic step. Default `"false"`. |
| `apimGatewayConfigFile` | `APIM_GATEWAY_CONFIG_FILE` | Your APIM JSON, relative to the repository root, e.g. `aifactory/gateways/apim.dev.json`. Empty: an existing APIM described by the `APIM_GATEWAY_*` variables. |

How to use it:

1. Copy [`apim.managed.dev.example.json`](../../../environment_setup/aifactory/bicep/copy_to_local_settings/ai-gateway/apim.managed.dev.example.json)
   (new private APIM) or [`apim.existing.dev.example.json`](../../../environment_setup/aifactory/bicep/copy_to_local_settings/ai-gateway/apim.existing.dev.example.json)
   (existing APIM) into your repository, one file per environment, and fill in your tenant, subscription, resource
   group, region, APIM name, network IDs (managed) and backends.
2. Set `apimGatewayManagedProvisioning: "true"` and `apimGatewayConfigFile` (GitHub: the `APIM_GATEWAY_*`
   repository or environment variables). Leave the `apimGatewayResourceGroup`/`apimGatewayServiceName`
   variables empty or naming the same APIM, because the MCP and Kong steps use them.
3. Run the AI gateway pipeline with `action: plan` (the default; offline, no Azure login). Review `plan.json` in
   the run artifact `apim-gateway-<environment>-<attempt>` and copy its `planDigest`.
4. Run it with `action: what-if` for one environment (Azure DevOps `deploymentTarget: dev`, GitHub
   `environment: dev`). Review the `<phase>.what-if.json` and copy its `previewDigest`.
5. Run it with `action: apply`, `approvedPlan`/`approved_plan` and `approvedPreview`/`approved_preview` set to the
   two digests. The first create of a managed APIM also needs `approveInitialPublicBootstrap` (it starts with
   public access, which the later lockdown phase disables).
6. Each apply writes one phase: integration subnet (if you asked for one), service, private endpoint, lockdown,
   configuration. Repeat steps 4-5, following `nextAction` in `receipt.json`, until `configuration` is applied.
   The MCP step and Kong run in the same run as that last apply.

A private endpoint must be approved by its network owner; the pipeline never approves it. Details, limits and
recovery: [APIM README](../../../environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/README.md#managed-provisioning-and-reviewed-deployments-opt-in).

## Kong AI gateway

Kong Gateway OSS runs in Azure Container Instances in the common VNet, with its declarative `kong.yaml` on a file
share. It routes, secures (consumer API key) and rate-limits traffic to Azure OpenAI or Foundry over private
endpoints, or acts as an edge in front of APIM (`kongGatewayApimHost`).

| Variable | GHA | Meaning |
|---|---|---|
| `ENABLE_KONG` | `ENABLE_KONG` | Deploy Kong. Independent of `ENABLE_APIM`. |
| `kongGatewayVnetResourceGroup`, `kongGatewayVnetName`, `kongGatewaySubnetCidr`, `kongGatewaySubnetName` | `KONG_GATEWAY_*` | Where Kong runs. |
| `kongGatewayApimHost` | `KONG_GATEWAY_APIM_HOST` | Upstream APIM host. |
| `kongGatewayImage`, `kongGatewayCpu`, `kongGatewayMemoryGb` | `KONG_GATEWAY_*` | Container settings. |
| `kongConsumerApiKey` | `KONG_CONSUMER_API_KEY` (secret) | Consumer key. |

Details: [Kong readme](../../../environment_setup/aigateway/kong/readme.md), [AI gateway overview](../../../environment_setup/aigateway/readme.md).

## Which one?

- **Agents in Foundry that need governed tools and models in one place:** the native AI Gateway SKU, with the MCP
  registered as a tool server.
- **An enterprise APIM you already run, with your own policies and subscriptions:** classic APIM, with
  `addAIFactoryMCP2APIM` for the MCP.
- **A new private APIM owned by the AI Factory, with a reviewed preview before every change:** classic APIM with
  managed provisioning (`apimGatewayManagedProvisioning`).
- **An open-source gateway or an edge in front of APIM:** Kong.

All three reach private backends only through private endpoints and private DNS, and none of them changes who may
call the MCP: that is always the MCP's app role `AiFactory.Mcp.Read` plus its caller list.
