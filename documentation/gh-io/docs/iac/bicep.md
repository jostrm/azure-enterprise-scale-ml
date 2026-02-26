# IaC — BICEP

All AI Factory infrastructure is defined in **Azure Bicep** — Microsoft's domain-specific language for declaring Azure resources. Bicep compiles to ARM JSON and is fully supported by Azure CLI.

---

## Why Bicep?

- **GA technology** — used per WAF recommendation (avoids AZD/AVM preview tooling in production).
- **Modular** — each Azure service is a separate Bicep module, reused across project types.
- **Auditable** — all deployments are logged in Azure Deployment history.
- **Incremental** — Bicep deployments are idempotent; re-runs only update changed resources.

---

## Repository Structure

```
environment_setup/aifactory/bicep/
├── copy_to_local_settings/
│   ├── azure-devops/
│   │   └── esml-yaml-pipelines/variables/variables.yaml   # ADO parameters
│   └── github-actions/
│       └── .env.template                                  # GHA parameters
└── modules/                                               # Bicep modules
```

---

## Key Modules

| Module | Description |
|---|---|
| `aiFoundry.bicep` | AI Foundry Hub + project, private endpoints, RBAC |
| `aiSearch.bicep` | AI Search with optional shared private link |
| `networking.bicep` | VNet, subnets, NSGs, private DNS zones |
| `keyvault.bicep` | Key Vault with soft-delete, RBAC, private endpoint |
| `acr.bicep` | Azure Container Registry (Premium, private) |
| `storage.bicep` | Storage accounts with ACLs and private endpoints |
| `aks.bicep` | Private AKS cluster with Arc registration |
| `containerApps.bicep` | Azure Container Apps environment |
| `cosmosdb.bicep` | Cosmos DB with private endpoint |

---

## Deployment Flow

```
Pipeline triggers
      │
      ▼
Step 05: Build ACR image (if Container Apps)
      │
      ▼
Steps 61–100: Bicep module deployments (parallel where possible)
      │
      ▼
      Done ✓
```

See [IaC Templates](../concepts/templates/iac.md) for the full list of pipeline steps.

---

## CMK Support

Customer-Managed Keys (CMK) are supported for:

- Key Vault (stores the CMK key)
- Storage accounts
- Azure Machine Learning workspaces
- AI Foundry

Enable via: `cmk=true`, `cmkKeyName=<your-key-name>`.

!!! warning
    CMK requires `acr_dedicated=true` and `acr_SKU=Premium`. Ensure the ACR container registry has been set up before enabling CMK.
