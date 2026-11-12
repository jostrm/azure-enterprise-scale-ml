# Parameters - required inputs

This checklist has the inputs you need for the orchestrator and the environment you chose. The
[complete reference](advanced.md) has every setting with its default and its name in each format.

**M** means mandatory. **C** means required only when its condition applies. A default can fill a mandatory
setting. Replace the placeholders with your own values.

The tools ask for these inputs when you create a Factory: see
[Create your AI Factory](../setup/02-create-factory.md). The tables below give the names the pipelines use.

## Before editing

| Decide first | Why it matters |
| --- | --- |
| A new Factory, or a repository that was set up with v1.24 | They are changed in different ways. |
| Dev, Stage or Prod | Each environment you deploy needs its own subscription, network range and pipeline access. |
| GitHub Actions or Azure DevOps | GitHub uses environments and variables. Azure DevOps uses service connections. |
| Which services | A service can need other services, more permissions and more budget. |

## Scope, naming and project

| M/C | YAML / JSON key | GitHub Actions key | What to review |
|---|---|---|---|
| M | `tenantId` | `TENANT_ID` | Azure deployment tenant |
| M | `dev_sub_id` | `DEV_SUBSCRIPTION_ID` | Dev subscription and deployment identity permissions |
| M | `admin_location`, `admin_locationSuffix` | `AIFACTORY_LOCATION`, `AIFACTORY_LOCATION_SHORT` | Template region `eastus2`, suffix `eus2`; change together |
| M | `admin_aifactorySuffixRG` | `AIFACTORY_SUFFIX` | Template scale-set suffix `-001`; select the intended factory |
| M | `project_number_000` | `PROJECT_NUMBER` | Three-digit project number, initially `001` |
| M | `technical_admins_ad_object_id` | `PROJECT_MEMBERS` | Entra object IDs; use group IDs when `use_ad_groups` / `USE_AD_GROUPS=true` |
| M | `runNetworkingVar` | `RUN_JOB1_NETWORKING` | Defaults `true`; skip only after confirming existing project networking |
| C | `test_sub_id`, `prod_sub_id` | `STAGE_SUBSCRIPTION_ID`, `PROD_SUBSCRIPTION_ID` | Required for the environments you deploy. Use separate subscriptions to isolate Stage and Prod from Dev |

Choose the resource-name prefix before you create the Factory. The templates have different defaults:
`admin_aifactoryPrefixRG` is `mrvel-1-` in YAML and JSON, and `AIFACTORY_PREFIX` is `acme-ai` for GitHub.

## Orchestrator and identity

| M/C | Inputs | Condition / guidance |
|---|---|---|
| C | `GITHUB_USERNAME`, `GITHUB_NEW_REPO` | GHA repository setup; use `owner/repo`. Generic template visibility is public; inspect it before creation |
| C | `azureDevOpsTenantId`, `dev_service_connection` | ADO route; organization tenant may differ from Azure deployment tenant |
| C | `test_service_connection`, `prod_service_connection` and corresponding `*_seeding_kv_service_connection` | Only for deployed environments; use the actual authorized service-connection names |
| M | `dev_admin_bicep_input_keyvault_subscription`, `dev_admin_bicep_kv_fw_rg`, `dev_admin_bicep_kv_fw` | Dev seeding-vault coordinates; GHA uses `AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID`, `AIFACTORY_SEEDING_KEYVAULT_RG`, `AIFACTORY_SEEDING_KEYVAULT_NAME` |
| C | Corresponding `test_admin_bicep_*` / `prod_admin_bicep_*` vault coordinates | Stage/Prod when deployed; GHA environment overrides are not separate template names |
| C | `azure_machinelearning_sp_oid` / `TENANT_AZUREML_OID` and `AZURE_MACHINELEARNING_SP_OID` | Required by the applicable Foundry/ML path; enterprise-application object ID, not application/client ID |
| C | `databricksOID` / `DATABRICKS_OID` | Databricks enabled |
| C | Common/project service-principal **secret-name** fields | Existing-SP/seeding route only. Federated managed-identity bootstrap can leave legacy secret references empty |

`AZURE_CLIENT_ID` selects the federated identity of the GitHub workflows. Keep client secrets, personal access
tokens and certificates out of the files you commit. Put them in the seeding Key Vault and name the secret in
the setting.

## Network and service dependencies

| M/C | Inputs | Condition / guidance |
|---|---|---|
| M | `common_vnet_cidr`, common subnet CIDRs; `dev_cidr_range`, `test_cidr_range`, `prod_cidr_range` | Shared templates use `172.16.XX.0/18` with aligned `0` / `64` / `128`; GHA uses `COMMON_*_CIDR` and `DEV_CIDR_RANGE` / `STAGE_CIDR_RANGE` / `PROD_CIDR_RANGE` |
| C | `privDnsSubscription_param`, `privDnsResourceGroup_param` | Required when `centralDnsZoneByPolicyInHub=true`; GHA uses `PRIV_DNS_SUBSCRIPTION_PARAM`, `PRIV_DNS_RESOURCE_GROUP_PARAM` |
| C | Existing VNet/subnet identifiers | Required when `BYO_subnets` / `BYO_SUBNETS=true`, and for each enabled service's subnet |
| C | `project_IP_whitelist` / `PROJECT_MEMBERS_IP_ADDRESS` | The IP addresses that may reach the services, with hybrid or public networking |
| C | `cmkKeyName` / `CMK_KEY_NAME`, vault protection and permissions | CMK enabled; review the relevant service's CMK exclusions |
| C | `admin_aiSearchTier`, `admin_semanticSearchTier` | AI Search enabled; defaults `basic` and `free`. Search SKU `free` is incompatible with Private Link |
| C | Foundry + capability host + Storage + AI Search + Cosmos DB | Required together for private Foundry agents that keep their data in your own resources |

For private Foundry agents, switch these on together:
`enableAIFoundry` / `ENABLE_AI_FOUNDRY`,
`enableAFoundryCaphost` / `ENABLE_FOUNDRY_CAPHOST`,
`enableAISearch` / `ENABLE_AI_SEARCH`, and
`enableCosmosDB` / `ENABLE_COSMOS_DB`.

The two hub settings choose the hub mode. Both `false` is Standalone. `enableAIFactoryHub=true` is Own hub.
`centralDnsZoneByPolicyInHub=true` is External hub, and it wins when both are `true`. See
[Hub and network modes](../reference/hub-and-network-modes.md).

## Optional Factory MCP and AI Gateway

You need these inputs only when you switch on the Factory MCP server or the AI gateway for **project 001 in
Dev**.

| Input | Required when |
| --- | --- |
| `enableAIFactoryMCP` plus Foundry and Container Apps | Hosting the read-only Factory MCP. |
| `aifactoryMcpImage`, `aifactoryMcpApiImage` | MCP hosting; supply approved digest-pinned images from the expected registry. |
| `aifactoryMcpEntraAppId` | MCP hosting; an administrator prepares the app registration and required role. |
| `enableAIGatewaySKU` plus Foundry | Creating/adopting the dedicated AI Gateway integration. |
| `aiGatewaySkuResourceId` | Adopting an existing gateway rather than creating one. |
| `addAIFactoryMCP2AIGatewaySKU` plus both components | Registering MCP on the gateway. |
| `aiGatewaySkuOutboundSubnetId` | Registration with a new gateway; an adopted gateway must already have suitable outbound networking. |
| `aifactoryMcpClassicApimResourceIds` | Optional, with MCP hosting: classic APIM gateways that call the MCP with their system-assigned identity; an administrator assigns `AiFactory.Mcp.Read` to each identity. |
| `addAIFactoryMCP2APIM` plus the `apimGateway*` APIM | Publishing the MCP on the AI gateway pipeline's classic APIM: the project step admits the APIM identity, then the AI gateway pipeline deploys the MCP API and client subscription `aifactory-mcp-client`. |
| `aifactoryMcpContainerAppResourceId` | Optional, with MCP hosting: adopt an MCP app deployed outside the pipeline; only its caller lists grow. |

The step prints, for each MCP caller, the exact admin-run command for the Microsoft Graph Bicep template `esml-common/ai-gateway/entra/aifactory-mcp-app-role.bicep` that assigns `AiFactory.Mcp.Read`; no pipeline writes Microsoft Graph.

All three switches are `false` by default, and `false` skips the step. See
[MCP and AI gateway](advanced.md#mcp-and-ai-gateway-parameters). The pooled API Management gateway, Kong and
Application Gateway have their own settings.

<details markdown="1">
<summary>Earlier way: the launcher scripts</summary>

## Inputs of the launcher scripts

The launcher scripts read their inputs from environment variables that start with `AIF_`, `ADO_` or
`GITHUB_`. The region prompt of the create script defaults to `swedencentral`, while the templates default to
`eastus2`. Simple mode sets more of the inputs for you. You give a host name, a backend and a certificate
only when simple mode deploys an Application Gateway.

All inputs are in the [launcher reference](advanced.md#bash-create-and-update-contract). Before you start a
run, read which Factory, project and environment it targets and which delete settings are `true`.

The `variables.json` of a project that the Factory API created has two sections, **`dev` and `stage_prod`**.
The template in the repository has a `dev` section only. See
[the two formats](advanced.md#scope-and-authoritative-sources).

Create uses version `124` unless you give another, and update keeps the version that was saved. Name `main` to
use the current development version.

</details>
