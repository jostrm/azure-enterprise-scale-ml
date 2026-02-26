# Parameters — Standard Mode

Standard Mode lists only the **mandatory** parameters — the minimum set you must configure before running the AI Factory pipeline for the first time.

For every parameter including optional ones, see [Advanced Mode](advanced.md).

!!! tip
    Search this page with **Ctrl+F**. Every variable name matches exactly the key in `.env.template` (GitHub Actions) or `variables.yaml` (Azure DevOps).

---

## How to read the tables

| Column | Meaning |
|---|---|
| **Variable** | The exact key name to set in `.env.template` / `variables.yaml` |
| **Default** | Value already in the file — what you get without editing |
| **Guidance** | `ensure` = look up from external source · `keep-as-is` = no change needed · `recommended` = production best practice |
| **Description** | What the variable controls

---

## Group 1 — GitHub Bootstrap *(GitHub Actions only)*

| Variable | Default | Guidance | Description |
|---|---|---|---|
| `GITHUB_USERNAME` | `<todo>` | **ensure** your GitHub username or organisation name | GitHub username or org that owns the new repository |
| `GITHUB_NEW_REPO` | `<todo>/<todo>azure-enterprise-scale-aifactory-001` | **ensure** format must be `<org>/<repo-name>` | Full path of the new GitHub repository to create |
| `TENANT_ID` | `<todo>` | **ensure** Azure Portal → Entra ID → Overview → Directory (tenant) ID | Azure tenant ID |
| `TENANT_AZUREML_OID` | `<todo>` | **ensure** Entra ID → Enterprise Apps → search `Azure Machine Learning` (AppId: `0736f41a-0425-4b46-bdb5-1563eff02385`) → Object ID. Not needed if `ENABLE_AI_FOUNDRY=false` | Azure Machine Learning service principal Object ID |

---

## Group 2 — AI Factory Globals

| Variable | Default | Guidance | Description |
|---|---|---|---|
| `AIFACTORY_LOCATION` | `eastus2` | keep-as-is or change to your preferred region | Primary Azure region for all AI Factory resources |
| `AIFACTORY_LOCATION_SHORT` | `eus2` | keep-as-is or update to match `AIFACTORY_LOCATION` (e.g. `weu`, `neu`, `swe`) | Short region suffix used in resource names |
| `ADMIN_AISEARCH_TIER` | `basic` | **ensure** `free` is **not allowed** when using private endpoints | AI Search SKU. Options: `free`, `basic`, `standard`, `standard2`, `standard3`, `storage_optimized_l1`, `storage_optimized_l2` |
| `AISEARCH_SEMANTIC_TIER` | `free` | keep-as-is | Semantic search tier. Options: `disabled`, `free`, `standard` |
| `AIFACTORY_SUFFIX` | `-001` | keep-as-is for the first scale set. **otherwise** increment to `-002`, `-003` for additional scale sets | AI Factory scale set suffix — appended to resource group names |
| `AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID` | `<todo>` | **ensure** subscription where the DEV seeding Key Vault exists | Subscription ID of the DEV seeding Key Vault |
| `AIFACTORY_SEEDING_KEYVAULT_NAME` | `<todo>` | **ensure** Key Vault must already exist and contain the SP secrets | Name of the DEV seeding Key Vault |
| `AIFACTORY_SEEDING_KEYVAULT_RG` | `<todo>` | **ensure** resource group must already exist | Resource group of the DEV seeding Key Vault |
| `COMMON_SERVICE_PRINCIPAL_KV_S_NAME_APPID` | `esml-common-sp-id` | **ensure** secret name must match exactly what is stored in the seeding Key Vault | Secret name in seeding KV holding the common Service Principal App ID |
| `COMMON_SERVICE_PRINCIPAL_KV_S_NAME_SECRET` | `esml-common-sp-secret` | **ensure** secret name must match exactly what is stored in the seeding Key Vault | Secret name in seeding KV holding the common Service Principal secret |

---

## Group 3 — Azure Subscriptions & CIDR Ranges

!!! note
    `STAGE_SUBSCRIPTION_ID` and `PROD_SUBSCRIPTION_ID` are optional but strongly recommended — use separate subscriptions from DEV.

| Variable | Default | Guidance | Description |
|---|---|---|---|
| `DEV_SUBSCRIPTION_ID` | `<todo>` | **ensure** subscription exists and the common SP has Contributor access | DEV Azure subscription ID |
| `DEV_CIDR_RANGE` | `61` | keep-as-is. Replaces `XX` in CIDR templates (e.g. `172.16.61.0/26`). **otherwise** choose any `0–255` value not conflicting with other environments or existing subnets | CIDR substitution value for DEV environment subnets |
| `STAGE_CIDR_RANGE` | `62` | keep-as-is. Must differ from `DEV_CIDR_RANGE` and `PROD_CIDR_RANGE` | CIDR substitution value for STAGE environment subnets |
| `PROD_CIDR_RANGE` | `63` | keep-as-is. Must differ from `DEV_CIDR_RANGE` and `STAGE_CIDR_RANGE` | CIDR substitution value for PROD environment subnets |

---

## Group 4 — Common Service Principal (Secret Names in Seeding KV)

| Variable | Default | Guidance | Description |
|---|---|---|---|
| `AZURE_MACHINELEARNING_SP_OID` | `<todo>` | **ensure** Entra ID → Enterprise Apps → `Azure Machine Learning` (AppId: `0736f41a-0425-4b46-bdb5-1563eff02385`) → Object ID. Not needed if `ENABLE_AI_FOUNDRY=false` | Azure Machine Learning service principal Object ID |
| `INPUT_COMMON_SPID_KEY` | `esml-common-sp-id` | **ensure** must match the secret name in your seeding Key Vault | Secret name holding the common SP App ID |
| `INPUT_COMMON_SP_SECRET_KEY` | `esml-common-sp-secret` | **ensure** must match the secret name in your seeding Key Vault | Secret name holding the common SP secret |
| `COMMON_SERVICE_PRINCIPLE_OID_KEY` | `esml-common-sp-oid` | **ensure** must match the secret name in your seeding Key Vault | Secret name holding the common SP Object ID |

---

## Group 5 — Project Setup

| Variable | Default | Guidance | Description |
|---|---|---|---|
| `PROJECT_NUMBER` | `001` | keep-as-is for the first project. **otherwise** increment to `002`, `003`, etc. for additional projects | Project number — used in resource group names and subnet naming |
| `PROJECT_MEMBERS` | `<todo>` | **ensure** comma-separated Entra ID Object IDs of users or AD security groups (when `USE_AD_GROUPS=true`) | Entra ID Object IDs of the project team members |
| `RUN_JOB1_NETWORKING` | `true` | keep-as-is when creating or updating a project. **otherwise** set `false` to skip networking on service-only re-runs | Whether to run subnet/IP calculation and networking deployment |

---

## Group 6 — Project Service Principals (Secret Names in Seeding KV)

These are the **names** of secrets in the seeding Key Vault that hold the project team's service principal credentials. They must exist before running the pipeline.

| Variable | Default | Guidance | Description |
|---|---|---|---|
| `PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID` | `esml-project001-sp-id` | **ensure** must match the secret name in your seeding Key Vault | Secret name for the project SP App ID |
| `PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID` | `esml-project001-sp-oid` | **ensure** must match the secret name in your seeding Key Vault | Secret name for the project SP Object ID |
| `PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S` | `esml-project001-sp-secret` | **ensure** must match the secret name in your seeding Key Vault | Secret name for the project SP secret |

---

## Group 7 — Core Service Flags

| Variable | Default | Guidance | Description |
|---|---|---|---|
| `ENABLE_AI_FOUNDRY` | `true` | **recommended** keep `true` for enterprise-grade private networking | Deploy AI Foundry Hub and default project with private endpoints |
| `ADMIN_AI_SEARCH_TIER` | `basic` | **ensure** `free` is **not allowed** when using private endpoints | AI Search SKU tier for the project |
| `ADMIN_SEMANTIC_SEARCH_TIER` | `free` | keep-as-is | Semantic search tier. Options: `disabled`, `free`, `standard` |

---

!!! success "That's all you need for a first deployment"
    Once Groups 1–7 are filled in, run the pipeline. The AI Factory calculates networking, deploys all Bicep modules, and configures RBAC automatically — producing a working **AI Foundry + AI Search + private networking** baseline in ~10 minutes.

!!! info "Want to enable more services?"
    All optional services (Cosmos DB, AKS, Container Apps, ML Studio, Databricks, models, BYO networking, etc.) are in [Advanced Mode](advanced.md).

