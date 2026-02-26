# IaC Templates

Infrastructure as Code (IaC) is the backbone of the AI Factory. All resources are defined in **Azure Bicep**, ensuring repeatable, auditable, and version-controlled deployments.

---

## Bicep Architecture

The Bicep templates are structured as modular, composable units:

```
environment_setup/aifactory/bicep/
├── modules/               # Reusable resource modules
│   ├── aiFoundry.bicep
│   ├── aiSearch.bicep
│   ├── networking.bicep
│   ├── keyvault.bicep
│   └── ...
├── esml-common/           # AI Factory common infrastructure
└── esml-project/          # Per-project infrastructure
```

---

## Deployment Stages (Pipeline Steps)

| Step | Description |
|---|---|
| 61 | Foundation — Resource Groups, Managed Identities, VMs |
| 62 | Core Infrastructure — Application Insights, Key Vault, Storage, ACR |
| 63 | Cognitive Services — AI Search, OpenAI, Vision, Speech, etc. |
| 64 | Databases — Cosmos DB, SQL, PostgreSQL, Redis |
| 65 | Compute Services — Container Apps, Web App, Function App |
| 66 | AI Platform (V1) — AI Foundry Hub with default project and connections |
| 67 | ML Platform — Azure Machine Learning, Data Factory, Databricks |
| 68 | Integration — Logic Apps, Event Hubs |
| 69 | AI Foundry V2 (2025) — AI Foundry V2 with RBAC and default project |
| 100 | RBAC & Security — Role assignments across all services (steps 61–99) |

Each step can be individually skipped via `debug_disable_XX` flags for faster re-runs during development.

---

## Bring Your Own (BYO) Options

The IaC supports several BYO overrides to integrate with existing infrastructure:

| BYO Option | Variable |
|---|---|
| Existing vNet | `vnetNameFull_param` + `vnetResourceGroup_param` |
| Existing subnets | `BYO_subnets=true` + subnet name variables |
| Existing Common Resource Group | `commonResourceGroup_param` |
| Existing Data Lake | `datalakeName_param` |
| Existing Key Vault | `kvNameFromCOMMON_param` |
| Existing ASEv3 | `byoASEv3=true` + `byoAseFullResourceId` |
| BYO Terraform | See [BYO Terraform](../../iac/terraform.md) |

---

!!! tip
    See [IaC — BICEP](../../iac/bicep.md) for detailed Bicep usage and best practices.
