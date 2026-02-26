# GenAIOps Templates

The AI Factory provides GenAIOps templates for the **GenAI-1** project type, enabling a full agentic AI lifecycle within a secure, private Azure environment.

---

## GenAI-1 Baseline Architecture

Every GenAI-1 project deploys a **secured baseline** automatically:

| Service | Purpose |
|---|---|
| **AI Foundry (Hub + Project)** | Central AI development environment |
| **AI Search** | Vector search for RAG scenarios |
| **AI Services / Azure OpenAI** | LLM and embedding model hosting |
| **Storage (×2)** | Data lake + AI Foundry default storage |
| **Key Vault** | Secrets, keys, CMK support |
| **Application Insights** | Monitoring and observability |
| **Private Networking** | All services connected via private endpoints |

Optional services are added via feature flags — see [Parameters](../../parameters/standard.md).

---

## Agentic Scenarios

The GenAI-1 template supports:

- **RAG (Retrieval Augmented Generation)**: AI Search + AI Foundry + GPT-4o
- **Agentic Workflows**: AI Foundry Agents with network injection, Capacity Host (`enableAFoundryCaphost=true`)
- **AI Gateway**: APIM integration via `foundryApiManagementResourceId`
- **Content Safety**: Azure Content Safety service (`enableContentSafety=true`)

---

## Default Model Deployment

| Model | Default enabled | Default version |
|---|---|---|
| `gpt-4o` | ✅ yes | `2024-11-20` |
| `text-embedding-3-large` | ✅ yes (recommended for production RAG) | latest |
| `gpt-4o-mini` | ❌ no | `2024-07-18` |
| `text-embedding-ada-002` | ❌ no | — |
| `text-embedding-3-small` | ❌ no | — |
| Custom GPT-X | ❌ no | configurable |

All model deployments are configurable — see [Parameters — Advanced Mode](../../parameters/advanced.md).

---

## GenAI Project Team Personas

| Persona | Description |
|---|---|
| `p011_genai_team_lead` | Project lead, architect |
| `p012_genai_team_member_aifoundry` | AI Foundry specialist |
| `p013_genai_team_member_agentic` | Agentic workflow developer |
| `p014_genai_team_member_dataops` | Data pipeline engineer |
| `p015_genai_team_member_frontend` | Front-end / app developer |

---

!!! info
    GenAIOps templates are located under `copy_my_subfolders_to_my_grandparent/genaiops/`.
