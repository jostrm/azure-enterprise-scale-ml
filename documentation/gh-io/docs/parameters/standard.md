# Parameters — Standard checklist

Start with the inputs needed for your **selected route and environment**.
This is a concise mandatory/conditional checklist, not the complete inventory
or a guarantee that a subscription is ready to deploy.
See [Advanced reference](advanced.md) for exact defaults, aliases, every public
template key, bootstrap inputs and CLI/API options.

**M** = mandatory in context; **C** = required only when its condition applies.
Defaults can satisfy mandatory settings. Replace placeholders and verify
permissions, service availability, quota, DNS and private network reachability.

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
| C | `test_sub_id`, `prod_sub_id` | `STAGE_SUBSCRIPTION_ID`, `PROD_SUBSCRIPTION_ID` | Required for the environments you actually deploy; review isolation rather than blindly reuse Dev |

Also review the optional resource-name prefix before creation:
YAML/JSON `admin_aifactoryPrefixRG` defaults to `mrvel-1-`, while
GHA `AIFACTORY_PREFIX` defaults to `acme-ai`. These are not identical templates.

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

`AZURE_CLIENT_ID` selects a federated GHA deployment identity when configured.
Do not put client secrets, PATs or certificate material into committed
configuration. An existing seeding vault and valid secret names are different
prerequisites from creating an identity through bootstrap.

## Network and service dependencies

| M/C | Inputs | Condition / guidance |
|---|---|---|
| M | `common_vnet_cidr`, common subnet CIDRs; `dev_cidr_range`, `test_cidr_range`, `prod_cidr_range` | Shared templates use `172.16.XX.0/18` with aligned `0` / `64` / `128`; GHA uses `COMMON_*_CIDR` and `DEV_CIDR_RANGE` / `STAGE_CIDR_RANGE` / `PROD_CIDR_RANGE` |
| C | `privDnsSubscription_param`, `privDnsResourceGroup_param` | Required when `centralDnsZoneByPolicyInHub=true`; GHA uses `PRIV_DNS_SUBSCRIPTION_PARAM`, `PRIV_DNS_RESOURCE_GROUP_PARAM` |
| C | Existing VNet/subnet identifiers | Required when `BYO_subnets` / `BYO_SUBNETS=true`, and for each enabled service's subnet |
| C | `project_IP_whitelist` / `PROJECT_MEMBERS_IP_ADDRESS` | IP-allowlist access mode; not a substitute for private connectivity |
| C | `cmkKeyName` / `CMK_KEY_NAME`, vault protection and permissions | CMK enabled; review the relevant service's CMK exclusions |
| C | `admin_aiSearchTier`, `admin_semanticSearchTier` | AI Search enabled; defaults `basic` and `free`. Search SKU `free` is incompatible with Private Link |
| C | Foundry + capability host + Storage + AI Search + Cosmos DB | Required together for the standard private-agent/BYO-data-resource architecture, not for every possible Foundry architecture |

For that private-agent architecture, review
`enableAIFoundry` / `ENABLE_AI_FOUNDRY`,
`enableAFoundryCaphost` / `ENABLE_FOUNDRY_CAPHOST`,
`enableAISearch` / `ENABLE_AI_SEARCH`, and
`enableCosmosDB` / `ENABLE_COSMOS_DB` together.
Other deployment paths have different dependencies. Template feature defaults
and the simple-mode preset are not interchangeable.

Both DNS flags false mean standalone intent; `enableAIFactoryHub=true` means
own-hub intent unless central DNS is enabled, which takes precedence.
Flags do not establish peering. Public-access flags do not govern GitHub
repository visibility or guarantee private-only monitoring.

## If using the create bootstrap instead

Supply the route's public `AIF_*`, `GITHUB_REPOSITORY` or `ADO_*` inputs rather
than assuming the generated `.env` is the input schema. The general create
prompt currently defaults to `swedencentral` and accepts private networking
only; this differs from the shared templates. Simple mode fixes additional
settings and requires three private HTTPS gateway inputs.

Follow the [bootstrap contract and full input tables](advanced.md#bash-create-and-update-contract).
Before dispatch, review the exact factory/project/environment, resolved
configuration, networking dependencies, authentication and destructive flags.

For backend-generated Azure Factory v2 projects, the project's single
`variables.json` has direct top-level **`dev` and `stage_prod`** sections, each
retaining full configuration and separate subscription/SKU values. This differs
from the raw shared consumer template's current `dev`-only shape; see
[the two JSON contracts](advanced.md#scope-and-authoritative-sources).
