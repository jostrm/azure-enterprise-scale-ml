# AI Factory Intelligence

AI Factory Intelligence refers to the built-in automation layer that makes the AI Factory a truly "intelligent" provisioning platform — not just a collection of Bicep templates.

---

## What Is AI Factory Intelligence?

AI Factory Intelligence is the set of automated capabilities that understands **context** and acts accordingly:

1. **Dynamic Subnet / IP Calculator** — automatically computes all CIDR ranges for every subnet in every environment (Dev, Stage, Prod) from a single `cidr_range` integer per environment. No manual IP planning required.
2. **Dynamic RBAC** — automatically assigns the correct roles to the correct identities (Managed Identities, Service Principals, user groups) across all services in a project — including private endpoint connections, Key Vault access, and storage ACLs.
3. **Persona-based Access Control** — maps Entra ID security groups to predefined personas (e.g. `p001_esml_team_lead`, `p012_genai_team_member_aifoundry`) so that access rights follow skills and responsibilities, not just roles.
4. **Feature-flag orchestration** — the pipeline reads your `variables.yaml` / `.env` configuration and decides which Bicep modules to invoke, in which order, skipping disabled services entirely.
5. **Incremental deployment** — re-run the pipeline at any time to add new services (e.g. set `enableContainerApps=true`) without touching previously deployed resources.

---

## Personas

The AI Factory uses a persona system aligned with [WAF AI personas](https://learn.microsoft.com/en-us/azure/well-architected/ai/personas):

| Persona ID | Role |
|---|---|
| `p001` | ESML Team Lead |
| `p002` | ESML Data Scientist |
| `p003` | ESML Front-end Developer |
| `p011` | GenAI Team Lead |
| `p012` | GenAI AI Foundry specialist |
| `p013` | GenAI Agentic developer |
| `p014` | GenAI DataOps engineer |
| `p015` | GenAI Front-end developer |
| `p080` | Core Team IT Admin |
| `p081` | Core Team DataOps |
| `p082` | Core Team Fabric DataOps |

---

## Salt-based Uniqueness

Each AI Factory deployment gets a deterministic 5-character **salt** derived from the User-Assigned Managed Identity. This salt is used in all resource names to ensure uniqueness without collisions across scale sets.

Example: `adf-cmn-weu-dev-a4c2b-001` — the `a4c2b` is the salt.
