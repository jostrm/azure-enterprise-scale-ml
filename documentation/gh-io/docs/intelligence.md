# AI Factory Intelligence

AI Factory Intelligence is the top-level capability that transforms the AI Factory from a set of Bicep templates into a **self-aware, context-driven provisioning platform**.

---

## Capability Summary

| Capability | Description |
|---|---|
| **Dynamic IP/Subnet Calculator** | One integer per environment → all subnet CIDRs auto-calculated |
| **Dynamic RBAC Engine** | Service principal + managed identity roles assigned automatically across all services |
| **Persona Mapping** | Entra ID groups → predefined personas → fine-grained RBAC |
| **Feature Flag Orchestrator** | Pipeline reads flags → invokes only the required Bicep modules |
| **Incremental / Idempotent Deployments** | Re-run safely at any time to add services or apply updates |
| **Salt-based Resource Naming** | Deterministic unique 5-char salt prevents resource name collisions |
| **Debug Mode** | Individual pipeline steps can be skipped (`debug_disable_XX=true`) |

---

## Dynamic IP Calculator

Given only:

```yaml
dev_cidr_range: "61"
test_cidr_range: "62"
prod_cidr_range: "63"
common_vnet_cidr: "172.16.0.0/16"
```

The pipeline automatically calculates all subnets:

| Subnet | DEV CIDR |
|---|---|
| Common subnet | `172.16.61.0/26` |
| Scoring subnet | `172.16.61.64/26` |
| Power BI GW subnet | `172.16.61.128/26` |
| Bastion subnet | `172.16.61.192/26` |
| Project GenAI subnet | `172.16.61.X/26` |
| Project AKS subnet | `172.16.61.X/26` |

---

## Dynamic RBAC Engine

At deployment time, the pipeline:

1. Reads the project service principal OID and managed identity from the seeding Key Vault.
2. Assigns the correct Azure RBAC roles to each service (Storage, Key Vault, AI Foundry, AI Search, ACR, etc.).
3. Sets up ACL permissions on the Data Lake for the project team.
4. Applies Entra ID group assignments based on configured personas.

---

## Feature Flag Orchestrator

Feature flags in `variables.yaml` / `.env` control which services are deployed:

```yaml
enableAIFoundry: "true"      # deploy AI Foundry
enableAISearch: "true"       # deploy AI Search
enableCosmosDB: "false"      # skip Cosmos DB
enableContainerApps: "false" # skip Container Apps (add later)
```

On re-run with `enableContainerApps: "true"`, only the Container Apps step runs — existing services are untouched.

---

For the full persona reference, see [AI Factory Intelligence — Concepts](concepts/intelligence.md).
