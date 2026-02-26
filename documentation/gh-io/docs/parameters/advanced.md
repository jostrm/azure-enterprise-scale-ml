# Parameters — Advanced Mode

This page lists **all parameters** — both mandatory (**M**) and optional (**O**) — from the `.env.template` file, organized by category. Mandatory parameters are also covered in [Standard Mode](standard.md).

!!! note "How to read the tables"
    - **M/O** — **M** = mandatory (required before first run), **O** = optional
    - **Guidance** follows tag priority: `ensure` › `recommended` › `keep-as-is` › `otherwise`
    - Source file: `environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template`

---

## Group 1 — GitHub Bootstrap

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `GITHUB_USERNAME` | `<todo>` | **M** | **ensure** your GitHub username or org name | GitHub user or org that owns the new repo |
| `GITHUB_NEW_REPO` | `<todo>/<todo>azure-enterprise-scale-aifactory-001` | **M** | **ensure** format must be `<org>/<repo-name>` | Full repo path for the new AI Factory repo |
| `TENANT_ID` | `<todo>` | **M** | **ensure** Azure Portal → Entra ID → Overview (Directory ID) | Azure AD / Entra tenant ID |
| `TENANT_AZUREML_OID` | `<todo>` | **M** | **ensure** Entra ID → Enterprise Apps → Azure Machine Learning (AppId `0736f41a-...`) → OID. **otherwise** optional if `ENABLE_AI_FOUNDRY=false` | Object ID of the Azure ML service principal in your tenant |
| `GITHUB_USE_SSH` | `false` | O | keep-as-is | Use SSH instead of HTTPS for git operations |
| `GITHUB_TEMPLATE_REPO` | `azure/enterprise-scale-aifactory` | O | keep-as-is | Source template repo used for bootstrapping |
| `GITHUB_NEW_REPO_VISIBILITY` | `public` | O | keep-as-is. **otherwise** `private` or `internal` | Visibility of the newly created repo |

---

## Group 2 — AI Factory Globals

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `AIFACTORY_LOCATION` | `eastus2` | **M** | keep-as-is. **otherwise** any Azure region name | Primary Azure region for all AI Factory resources |
| `AIFACTORY_LOCATION_SHORT` | `eus2` | **M** | keep-as-is. **otherwise** 4-char region abbreviation matching your region | Short suffix used in resource names |
| `ADMIN_AISEARCH_TIER` | `basic` | **M** | **ensure** `free` tier is **not allowed** when using private endpoints | AI Search SKU tier |
| `AISEARCH_SEMANTIC_TIER` | `free` | **M** | keep-as-is. Options: `disabled`, `free`, `standard` | Semantic search tier for AI Search |
| `AIFACTORY_SUFFIX` | `-001` | **M** | keep-as-is. **otherwise** increment to `-002`, `-003` for additional scale sets | AI Factory scale-set suffix appended to common resource names |
| `AIFACTORY_PREFIX` | `acme-ai` | O | keep-as-is. **otherwise** company-specific prefix, max 6 chars | Prefix for AI Factory resource group names |
| `LAKE_PREFIX` | `mrvel` | O | keep-as-is. max 8 chars | Data lake storage account name prefix |
| `USE_COMMON_ACR_FOR_PROJECTS` | `true` | O | keep-as-is. **otherwise** `false` = each project gets its own ACR (higher cost) | Share common ACR across all projects |
| `AIFACTORY_COMMON_ONLY_DEV_ENVIRONMENT` | `true` | O | keep-as-is. **otherwise** `false` = also deploy common resources in Stage + Prod | Deploy common resources only to DEV environment |
| `KEYVAULT_SOFT_DELETE` | `7` | O | keep-as-is. **ensure** mandatory value `7` if `CMK=true`. **otherwise** `90` days recommended for production KVs | Key Vault soft-delete retention period (days) |
| `USE_AD_GROUPS` | `true` | O | keep-as-is. **otherwise** `false` = assign RBAC to individual user OIDs | Use Entra ID groups for RBAC assignments |
| `ADMIN_USERNAME` | `esmladmin` | O | keep-as-is | Admin username for VMs deployed by AI Factory |
| `ADMIN_HYBRID_BENEFIT` | `false` | O | keep-as-is. **otherwise** `true` if you have eligible Windows Server / SQL Server licences | Enable Azure Hybrid Benefit on Windows VMs |
| `ENABLE_AMPLS` | `false` | O | keep-as-is | Enable Azure Monitor Private Link Scope |
| `ADD_BASTION_HOST` | `false` | O | keep-as-is | Deploy Azure Bastion host in the common VNet |
| `ENABLE_ADMIN_VM` | `false` | O | keep-as-is | Deploy admin jump-box VM |
| `DIAGNOSTIC_SETTING_LEVEL` | `gold` | O | keep-as-is. **otherwise** `silver` or `bronze` to reduce Log Analytics ingestion cost | Diagnostics verbosity level |

---

## Group 3 — Azure Subscriptions & CIDR Ranges

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `DEV_SUBSCRIPTION_ID` | `<todo>` | **M** | **ensure** the common SP must have Contributor on this subscription | DEV Azure subscription ID |
| `DEV_CIDR_RANGE` | `61` | **M** | keep-as-is. **otherwise** any integer 0–255 that doesn't conflict with existing VNets | Integer replacing `XX` in all DEV subnet CIDRs (e.g. `172.16.61.0/26`) |
| `STAGE_CIDR_RANGE` | `62` | **M** | keep-as-is | Integer replacing `XX` in STAGE subnet CIDRs |
| `PROD_CIDR_RANGE` | `63` | **M** | keep-as-is | Integer replacing `XX` in PROD subnet CIDRs |
| `STAGE_SUBSCRIPTION_ID` | `<todo>` | O | **recommended** use a separate subscription from DEV | STAGE Azure subscription ID |
| `PROD_SUBSCRIPTION_ID` | `<todo>` | O | **recommended** use a separate subscription from DEV | PROD Azure subscription ID |

---

## Group 4 — Versioning & Resource Tags

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `AIFACTORY_VERSION_MAJOR` | `1` | O | keep-as-is | AI Factory major version (used in tags) |
| `AIFACTORY_VERSION_MINOR` | `24` | O | keep-as-is | AI Factory minor version (used in tags) |
| `AIFACTORY_BRANCH_CHOSEN` | `release/v1.24` | O | keep-as-is | Git branch checked out during bootstrap |
| `TAG_COSTCETER_COMMON` | `9999` | O | keep-as-is. **otherwise** set to your organisation's cost centre code | Cost centre tag applied to common resources |
| `TAG_REPOSITORY` | `aifactory` | O | keep-as-is | Repository tag value |
| `TAG_REPOSITORY_BRANCH` | `aifactory-001` | O | keep-as-is | Branch tag value |
| `TAGS` | *(JSON blob)* | O | keep-as-is. **otherwise** update `CostCenter` and `Description` values | Additional Azure resource tags as a JSON object |

---

## Group 5 — Common Service Principal (Identity Keys)

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID` | `<todo>` | **M** | **ensure** subscription where the DEV seeding Key Vault exists | Subscription ID of the DEV seeding KV |
| `AIFACTORY_SEEDING_KEYVAULT_NAME` | `<todo>` | **M** | **ensure** Key Vault must exist and contain the required SP secrets | Name of the DEV seeding Key Vault |
| `AIFACTORY_SEEDING_KEYVAULT_RG` | `<todo>` | **M** | **ensure** resource group must exist | Resource group of the DEV seeding KV |
| `AZURE_MACHINELEARNING_SP_OID` | `<todo>` | **M** | **ensure** Entra ID → Enterprise Apps → Azure Machine Learning → Object ID | OID of the Azure ML service principal |
| `COMMON_SERVICE_PRINCIPAL_KV_S_NAME_APPID` | `esml-common-sp-id` | **M** | **ensure** must exactly match the secret name in your seeding KV | Secret name storing the common SP App ID |
| `COMMON_SERVICE_PRINCIPAL_KV_S_NAME_SECRET` | `esml-common-sp-secret` | **M** | **ensure** must exactly match the secret name in your seeding KV | Secret name storing the common SP secret |
| `INPUT_COMMON_SPID_KEY` | `esml-common-sp-id` | **M** | **ensure** must exactly match secret name in seeding KV | Read alias for common SP App ID secret name |
| `INPUT_COMMON_SP_SECRET_KEY` | `esml-common-sp-secret` | **M** | **ensure** must exactly match secret name | Read alias for common SP secret name |
| `COMMON_SERVICE_PRINCIPLE_OID_KEY` | `esml-common-sp-oid` | **M** | **ensure** must exactly match secret name | Secret name storing the common SP Object ID |

---

## Group 6 — Project Setup

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `PROJECT_NUMBER` | `001` | **M** | keep-as-is. **otherwise** `002`, `003`… for additional projects | Three-digit project number used in resource names |
| `PROJECT_MEMBERS` | `<todo>` | **M** | **ensure** comma-separated Entra ID OIDs (users) or AD group OIDs | OIDs that receive project-level RBAC |
| `RUN_JOB1_NETWORKING` | `true` | **M** | keep-as-is. **otherwise** `false` to skip networking job on subsequent re-runs | Run the networking deployment job |
| `PROJECT_MEMBERS_EMAILS` | `<todo>` | O | **recommended** set for cost tracking and notifications | Comma-separated email addresses of project members |
| `PROJECT_MEMBERS_IP_ADDRESS` | `-` | O | **ensure** mandatory if IP-whitelisting mode is enabled | Comma-separated public IPs for firewall whitelisting |
| `TAG_COSTCENTER` | `1234` | O | keep-as-is. **otherwise** your project cost centre code | Cost centre tag for project resources |
| `TAGS_PROJECT` | *(JSON blob)* | O | keep-as-is. **otherwise** update field values | Additional resource tags for project resources |
| `SERVICE_SETTING_DEPLOY_PROJECT_VM` | `false` | O | keep-as-is | Deploy a jump-box VM in the project resource group |
| `PROJECT_TYPE` | *(type string)* | O | keep-as-is | Project persona type (affects RBAC persona mapping) |
| `PROJECT_PREFIX` | `esml-` | O | keep-as-is | Prefix for project resource group names |
| `PROJECT_SUFFIX` | `-rg` | O | keep-as-is | Suffix for project resource group names |

---

## Group 7 — Project Service Principals (Secret Names in Seeding KV)

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID` | `esml-project001-sp-id` | **M** | **ensure** must exactly match the secret name in your seeding KV | Secret name for the project SP App ID |
| `PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID` | `esml-project001-sp-oid` | **M** | **ensure** must exactly match the secret name in your seeding KV | Secret name for the project SP Object ID |
| `PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S` | `esml-project001-sp-secret` | **M** | **ensure** must exactly match the secret name in your seeding KV | Secret name for the project SP client secret |

---

## Group 8 — Core Service Flags

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ENABLE_AI_FOUNDRY` | `true` | **M** | **recommended** keep `true` for enterprise-grade private networking | Deploy AI Foundry Hub and default project with private endpoints |
| `ADMIN_AI_SEARCH_TIER` | `basic` | **M** | **ensure** `free` is **not allowed** when using private endpoints | AI Search SKU tier for the common AI Factory |
| `ADMIN_SEMANTIC_SEARCH_TIER` | `free` | **M** | keep-as-is. Options: `disabled`, `free`, `standard` | Semantic search tier |

---

## Group 9 — Networking — Public / Private Controls

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET` | `true` | O | **recommended** `false` for a fully private deployment | Allow public access to services even when placed behind a VNet |
| `ENABLE_PUBLIC_GENAI_ACCESS` | `true` | O | **recommended** `false` for a fully private deployment | Enable public access to GenAI endpoints |
| `ENABLE_PUBLIC_ACCESS_WITH_PERIMETER` | `true` | O | **recommended** `false` for a fully private deployment | Enable public access via network perimeter policy |
| `CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB` | `false` | O | keep-as-is. **otherwise** `true` if a hub manages all private DNS zones centrally | Use central hub private DNS instead of per-spoke DNS zones |
| `PRIV_DNS_SUBSCRIPTION_PARAM` | `<todo>` | O | **ensure** mandatory if `CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB=true` | Subscription ID containing the central private DNS zones |
| `PRIV_DNS_RESOURCE_GROUP_PARAM` | `<todo>` | O | **ensure** mandatory if `CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB=true` | Resource group containing the central private DNS zones |

---

## Group 10 — Security — Defender / CMK / RBAC

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ENABLE_DEFENDER_FOR_AI_SUB_LEVEL` | `false` | O | keep-as-is | Enable Microsoft Defender for AI at subscription level |
| `ENABLE_DEFENDER_FOR_AI_RESOURCE_LEVEL` | `false` | O | keep-as-is | Enable Microsoft Defender for AI at resource level |
| `CMK` | `false` | O | keep-as-is | Enable Customer-Managed Key encryption for storage and Key Vault |
| `CMK_KEY_NAME` | `<todo>aifactory-cmk-key` | O | **ensure** mandatory if `CMK=true`. Provide the exact CMK key name in your Key Vault | Name of the CMK key in the shared Key Vault |
| `CMK_KEY_VERSION` | `""` | O | keep-as-is (auto-uses latest key version) | CMK key version; empty = always use latest |
| `UPDATE_KEYVAULT_RBAC` | `false` | O | keep-as-is | Re-apply RBAC policies on the common Key Vault |
| `BYO_CONTRIBUTOR_ROLE_ID` | `b24988ac-6180-42a0-ab88-20f7382dd24c` | O | keep-as-is (built-in Contributor role) | Custom contributor role ID if your org uses a scoped role |
| `DISABLE_CONTRIBUTOR_ACCESS_FORUSERS` | `false` | O | **recommended** `true` for production governance | Remove Contributor access from individual users |
| `DISABLE_RBAC_ADMIN_ON_RG_FORUSERS` | `false` | O | **recommended** `true` for production governance | Remove RBAC Administrator role from individual users on RGs |
| `ENABLE_DELETE_FOR_DISABLED_RESOURCES` | `true` | O | keep-as-is | Delete orphaned or disabled resources on re-runs |
| `DELETE_ALL_SERVICES_FOR_PROJECT` | `false` | O | keep-as-is. **otherwise** `true` deletes **all** project resources — use with caution | Tear down all services in a project on re-run |
| `DISABLE_WHITELISTING_FOR_BUILD_AGENTS` | `false` | O | keep-as-is | Skip adding build agent IPs to service firewall rules |

---

## Group 11 — AI Foundry

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `UPDATE_AI_FOUNDRY` | `false` | O | keep-as-is. set `true` to update an existing AI Foundry Hub | Run the AI Foundry update step |
| `ADD_AI_FOUNDRY` | `false` | O | keep-as-is | Add AI Foundry to an existing project |
| `ENABLE_FOUNDRY_CAPHOST` | `false` | O | **recommended** `true` — enables private agents (requires `ENABLE_COSMOS_DB=true`) | Enable AI Foundry Capacity Host for agentic workloads |
| `FOUNDRY_DEPLOYMENT_TYPE` | `1` | O | keep-as-is. `1`=PG, `2`=AVM, `3`=Both | AI Foundry internal deployment architecture variant |
| `ENABLE_AIFACTORY_CREATED_DEFAULT_PROJECT_FOR_AIFV2` | `true` | O | keep-as-is | Create the AI Foundry v2 default project automatically |
| `DISABLE_AGENT_NETWORK_INJECTION` | `false` | O | keep-as-is. **otherwise** `true` only if you need serverless agents — requires Class B/C subnet ranges | Disable network injection for AI Foundry agents |

---

## Group 12 — ML & Data Platform

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ENABLE_DATAFACTORY` | `false` | O | keep-as-is | Deploy Azure Data Factory in the project resource group |
| `ENABLE_DATAFACTORY_COMMON` | `false` | O | keep-as-is | Deploy Azure Data Factory in the common resource group |
| `ENABLE_AZURE_MACHINE_LEARNING` | `false` | O | keep-as-is | Deploy Azure Machine Learning workspace |
| `ADD_AZURE_MACHINE_LEARNING` | `false` | O | keep-as-is | Add AML to an existing project |
| `ENABLE_DATABRICKS` | `false` | O | keep-as-is | Deploy Azure Databricks workspace |
| `DATABRICKS_OID` | `<todo>` | O | **ensure** mandatory if `ENABLE_DATABRICKS=true` | Object ID of the Databricks service principal |

---

## Group 13 — AKS

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ENABLE_AKS_FOR_AZURE_ML` | `true` | O | keep-as-is. **ensure** mandatory if `ENABLE_AZURE_MACHINE_LEARNING=true` | Deploy private AKS cluster for AML online endpoints |
| `AKS_OUTBOUND_TYPE` | `loadBalancer` | O | keep-as-is. **otherwise** `userDefinedRouting` if routing through Azure Firewall | AKS outbound connectivity type |
| `AKS_PRIVATE_DNS_ZONE` | `system` | O | keep-as-is | AKS private DNS zone. `system` = AKS-managed, or supply a custom DNS zone resource ID |
| `AKS_AZURE_FIREWALL_PRIVATE_IP` | `""` | O | **ensure** mandatory if `AKS_OUTBOUND_TYPE=userDefinedRouting` | Private IP of Azure Firewall for UDR routing |

---

## Group 14 — Cognitive Services

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ENABLE_AI_SEARCH` | `true` | O | keep-as-is | Deploy Azure AI Search (required for RAG and Agents) |
| `ADD_AI_SEARCH` | `false` | O | keep-as-is | Add AI Search to an existing project |
| `ENABLE_AI_SEARCH_SHARED_PRIVATE_LINK` | `true` | O | keep-as-is | Enable shared private link for AI Search indexer |
| `ENABLE_AZURE_OPENAI` | `false` | O | keep-as-is | Deploy standalone Azure OpenAI (separate from AI Foundry) |
| `ENABLE_AZURE_AI_VISION` | `false` | O | keep-as-is | Deploy Azure AI Vision |
| `ENABLE_AZURE_SPEECH` | `false` | O | keep-as-is | Deploy Azure AI Speech |
| `ENABLE_AI_DOC_INTELLIGENCE` | `false` | O | keep-as-is | Deploy Azure AI Document Intelligence |
| `ENABLE_BING` | `false` | O | keep-as-is | Enable Bing Grounding for AI Foundry agents |
| `ENABLE_BING_CUSTOM_SEARCH` | `false` | O | keep-as-is | Enable Bing Custom Search |
| `BING_CUSTOM_SEARCH_SKU` | `G2` | O | keep-as-is | Bing Custom Search SKU |
| `ENABLE_CONTENT_SAFETY` | `false` | O | keep-as-is | Deploy Azure AI Content Safety |

---

## Group 15 — Databases

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ENABLE_COSMOS_DB` | `false` | O | keep-as-is. **ensure** required if `ENABLE_FOUNDRY_CAPHOST=true` | Deploy Azure Cosmos DB account |
| `COSMOS_KIND` | `GlobalDocumentDB` | O | keep-as-is. **otherwise** `MongoDB` | Cosmos DB API kind |
| `ENABLE_POSTGRESQL` | `false` | O | keep-as-is | Deploy Azure Database for PostgreSQL Flexible Server |
| `POSTGRES_ADMIN_EMAILS` | `""` | O | **ensure** mandatory if `ENABLE_POSTGRESQL=true` | Comma-separated admin email(s) for PostgreSQL Entra auth |
| `ENABLE_REDIS_CACHE` | `false` | O | keep-as-is | Deploy Azure Cache for Redis |
| `ENABLE_SQL_DATABASE` | `false` | O | keep-as-is | Deploy Azure SQL Database |

---

## Group 16 — Functions, Web Apps & Container Apps

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ENABLE_FUNCTION` | `false` | O | keep-as-is | Deploy Azure Function App |
| `FUNCTION_RUNTIME` | `dotnet` | O | keep-as-is. **otherwise** `python`, `node`, or `java` | Function App runtime stack |
| `FUNCTION_VERSION` | `v7.0` | O | keep-as-is | Function App runtime version |
| `ENABLE_WEBAPP` | `false` | O | keep-as-is | Deploy Azure Web App (App Service) |
| `WEBAPP_RUNTIME` | `python` | O | keep-as-is | Web App runtime stack |
| `WEBAPP_RUNTIME_VERSION` | `3.11` | O | keep-as-is | Web App runtime version |
| `ASE_SKU` | `IsolatedV2` | O | keep-as-is | App Service Environment v3 SKU family |
| `ASE_SKU_CODE` | `I1v2` | O | keep-as-is | App Service Environment v3 SKU code |
| `ASE_SKU_WORKERS` | `1` | O | keep-as-is | Number of App Service Environment workers |
| `ENABLE_CONTAINER_APPS` | `false` | O | keep-as-is | Deploy Azure Container Apps environment |
| `ENABLE_APPINSIGHTS_DASHBOARD` | `false` | O | keep-as-is | Deploy Application Insights dashboard workbook |
| `ACA_W_REGISTRY_IMAGE` | `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest` | O | keep-as-is | Seed image for the Container App |

---

## Group 17 — Integration

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ENABLE_LOGIC_APPS` | `false` | O | keep-as-is | Deploy Azure Logic Apps |
| `ENABLE_EVENT_HUBS` | `false` | O | keep-as-is | Deploy Azure Event Hubs namespace |
| `ENABLE_BOT_SERVICE` | `true` | O | keep-as-is | Deploy Azure Bot Service |
| `FOUNDRY_API_MANAGEMENT_RESOURCE_ID` | `""` | O | keep-as-is. **otherwise** provide the full ARM resource ID of an existing APIM instance | Link an existing APIM instance as AI Gateway for AI Foundry |

---

## Group 18 — AI Models

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `DEPLOY_MODEL_GPT_4O` | `true` | O | keep-as-is | Deploy GPT-4o model in AI Foundry |
| `DEFAULT_GPT_4O_VERSION` | `2024-11-20` | O | keep-as-is | GPT-4o model version |
| `DEFAULT_GPT_CAPACITY` | `40` | O | keep-as-is (= 40 K TPM) | Capacity for GPT-4o in thousands of tokens per minute |
| `DEPLOY_MODEL_GPT_4O_MINI` | `false` | O | keep-as-is | Deploy GPT-4o-mini model |
| `DEFAULT_GPT_4O_MINI_VERSION` | `2024-07-18` | O | keep-as-is | GPT-4o-mini model version |
| `DEPLOY_MODEL_TEXT_EMBEDDING_3_LARGE` | `true` | O | keep-as-is — **recommended** for production RAG | Deploy text-embedding-3-large |
| `DEPLOY_MODEL_TEXT_EMBEDDING_3_SMALL` | `false` | O | keep-as-is | Deploy text-embedding-3-small |
| `DEPLOY_MODEL_TEXT_EMBEDDING_ADA_002` | `false` | O | keep-as-is (legacy) | Deploy text-embedding-ada-002 (older model) |
| `DEFAULT_EMBEDDING_CAPACITY` | `25` | O | keep-as-is (= 25 K TPM) | Capacity for all embedding models |
| `DEPLOY_MODEL_GPT_X` | `false` | O | keep-as-is | Deploy a custom or future GPT model |
| `MODEL_GPTX_NAME` | `gpt-5-mini` | O | keep-as-is | Custom model name (used when `DEPLOY_MODEL_GPT_X=true`) |
| `MODEL_GPTX_VERSION` | `""` | O | keep-as-is (empty = latest available) | Custom model version |
| `MODEL_GPTX_SKU` | `DataZoneStandard` | O | keep-as-is | Custom model SKU |
| `MODEL_GPTX_CAPACITY` | `30` | O | keep-as-is (= 30 K TPM) | Custom model capacity |
| `DEFAULT_MODEL_SKU` | `Standard` | O | keep-as-is | Default SKU for all model deployments |

---

## Group 19 — Naming, Suffixes & ACR

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `ADMIN_COMMON_RESOURCE_SUFFIX` | `-001` | O | keep-as-is | Suffix appended to common AI Factory resource names |
| `ADMIN_PRJ_RESOURCE_SUFFIX` | `-001` | O | keep-as-is | Suffix appended to project resource names |
| `USE_COMMON_ACR_OVERRIDE` | `true` | O | keep-as-is | Override to use the shared common ACR |
| `ACR_IP_WHITELIST` | `""` | O | keep-as-is | Comma-separated IPs to add to the ACR firewall |
| `ACR_ADMIN_USER_ENABLED` | `false` | O | keep-as-is (`false` = more secure) | Enable ACR admin user account |
| `ACR_DEDICATED` | `true` | O | keep-as-is. **ensure** `true` when using private endpoints or CMK | Dedicate the ACR to the AI Factory (no shared SKU) |
| `ACR_SKU` | `Premium` | O | keep-as-is. **ensure** `Premium` is required for private endpoints and CMK | Azure Container Registry SKU |

---

## Group 20 — Baseline Networking

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `VNET_RESOURCE_GROUP_BASE` | `esml-common` | O | keep-as-is | Base name for the common VNet resource group |
| `VNET_NAME_BASE` | `vnt-esmlcmn` | O | keep-as-is | Base name for the common VNet |
| `SUBNET_COMMON_BASE` | `snet-esml-cmn-001` | O | keep-as-is | Base name for the common subnet |
| `COMMON_VNET_CIDR` | `172.16.0.0/16` | O | keep-as-is. **otherwise** choose a `/16` that doesn't conflict with your hub VNet | Common VNet address space |
| `COMMON_SUBNET_CIDR` | `172.16.XX.0/26` | O | keep-as-is (`XX` is replaced at runtime by the env CIDR range) | Common subnet CIDR |
| `COMMON_SUBNET_SCORING_CIDR` | `172.16.XX.64/26` | O | keep-as-is | Scoring/inference subnet CIDR |
| `COMMON_PBI_SUBNET_NAME` | `snet-esml-cmn-pbi-001` | O | keep-as-is | Power BI Gateway subnet name |
| `COMMON_PBI_SUBNET_CIDR` | `172.16.XX.128/26` | O | keep-as-is | Power BI Gateway subnet CIDR |
| `COMMON_BASTION_SUBNET_NAME` | `AzureBastionSubnet` | O | keep-as-is. **ensure** must be **exactly** `AzureBastionSubnet` for Azure Bastion to work | Bastion subnet name (Azure-required fixed name) |
| `COMMON_BASTION_SUBNET_CIDR` | `172.16.XX.192/26` | O | keep-as-is | Bastion subnet CIDR |

---

## Group 21 — BYO Subnets & VNet Overrides

!!! note
    Only needed when `BYO_SUBNETS=true`. Leave all defaults if letting the AI Factory auto-calculate subnets.

| Variable | Default | M/O | Guidance | Description |
|---|---|---|---|---|
| `BYO_SUBNETS` | `false` | O | keep-as-is. **otherwise** `true` to use pre-existing subnets | Bring your own subnets instead of AI Factory auto-creating them |
| `DEV_NETWORK_ENV` | `dev-` | O | keep-as-is | DEV prefix inserted into BYO subnet names |
| `STAGE_NETWORK_ENV` | `stage-` | O | keep-as-is | STAGE prefix inserted into BYO subnet names |
| `PROD_NETWORK_ENV` | `prod-` | O | keep-as-is | PROD prefix inserted into BYO subnet names |
| `VNET_RESOURCE_GROUP_PARAM` | `""` | O | **ensure** mandatory if `BYO_SUBNETS=true` | Resource group of the BYO VNet |
| `VNET_NAME_FULL_PARAM` | `""` | O | **ensure** mandatory if `BYO_SUBNETS=true` | Full name of the BYO VNet |
| `SUBNET_COMMON` | `""` | O | **ensure** mandatory if `BYO_SUBNETS=true` | Name of the BYO common subnet |

---

!!! success "You now have a complete view of all parameters"
    Return to [Standard Mode](standard.md) to see the minimal mandatory set needed for a first deployment.

!!! info "Source file"
    All parameters above map directly to variables in:
    `environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template`
