# Enterprise Scale AI Factory

![Header](assets/images/header.png)

Welcome to the official **Enterprise Scale AI Factory** — an enterprise AI landing zone, established 2019, [WAF-aligned](https://learn.microsoft.com/en-us/azure/well-architected/ai/personas), designed for Azure Public Cloud and compatible with Azure Government and Sovereign Cloud.

---

## What is the AI Factory?

The **Enterprise Scale AI Factory** is a plug-and-play solution that automates the provisioning, deployment, and management of AI projects on Azure using a template-driven approach.

- **AI-ready landing zones** with templates for DataOps, MLOps, and GenAIOps.
- **Automatically deploys 1–35 Azure services** in a WAF-aligned application landing zone. It supports the full AI spectrum — generative AI, deep learning, machine learning, and traditional application development: AI Foundry, Azure Machine Learning, Databricks, AI Search, AKS, Logic Apps, Container Apps, Azure Functions, PostgreSQL, SQL Database, and more.
- **Add or remove services** at any time via feature flags — all wired up with private networking, RBAC, and monitoring automatically is created or cleaned up when removing resource.
- Supports both **GitHub Actions** and **Azure DevOps** as orchestrators.

!!! note
    Since the Well-Architected Framework does not recommend using Azure Developer CLI (`azd`) for production, this project uses GA `Azure CLI` with orchestrator pipelines in GitHub Actions or Azure DevOps Pipelines.

---

## Main Purpose

1. **Marry multiple best practices**: Secure Enterprise Scale AI Landing Zones + Secure GenAIOps/MLOps templates — GenAIOps templates built on unsecured infrastructure are incompatible with private-endpoint-based infra, so the two are designed together here.
2. **Plug-and-play**: Dynamically creates infra resources per team, including subnet/IP calculation, private networking, RBAC, and ACL permissions on the data lake — fully automated.
3. **Template-based project delivery**: Project-based structure (cost control, privacy, scalability) with ready-made templates for DataLake, DataOps, MLOps, and GenAIOps.
4. **Enterprise scale, security, and battle-tested**: Used by customers and partners with MLOps and GenAIOps since 2019.
5. **Intelligent CRUD for 30+ Azure resources**: Enable and disable feature flags to add or safely remove resources. The AI Factory's internal dependency graph ensures that services are created, updated, and deleted in the correct order — including proper cleanup — without breaking dependent resources.
6. **Turn-key Enterprise Scale Data Lake with Datamesh**: A structured, permission-layered data lake is provisioned automatically, with per-project ACL isolation and Datamesh-ready design, to marry data management with AI workloads.
7. **Flexible with 10+ BYO concepts**: Bring Your Own IaC (Bicep, Terraform, ARM) on top of the AI Factory pipelines; BYO networking (VNet, subnets, routing tables); BYO Data Lake; BYO App Service Environment; BYO encryption key (CMK) — all configurable via a handful of parameters.

---

## Architectures

The AI Factory supports two baseline architectures:

| Architecture | Description |
|---|---|
| **ESML** | Enterprise Scale Machine Learning — discriminative AI, MLOps, DataOps |
| **GenAI-1** | Enterprise Scale GenAI — AI Foundry, AI Search, agentic scenarios |

### GenAI-1 Baseline (minimum)
**AI Foundry · AI Search · 2× Storage · Key Vault · Monitoring · Dashboards · Private Networking**

Optional add-ons (enabled via feature flags, can be added at any time):

| Category | Services |
|---|---|
| **AI** | Azure OpenAI (standalone), Azure Machine Learning, Azure Speech, Azure Vision, Bing Grounding |
| **Front-end / Hosting** | Azure Container Apps, Azure Web App / Function App, AKS (private + Arc-enabled) |
| **Data & Databases** | Cosmos DB, MongoDB, Azure SQL, PostgreSQL Flexible, Azure Cache for Redis |
| **Integration & ETL** | Azure Data Factory, Databricks, Event Hubs, Logic Apps, APIM AI Gateway, Microsoft Fabric / OneLake |

![AI Factory Architectures](assets/images/10-two-architectures-v2.png)

---

## Quick Links

| Resource | Link |
|---|---|
| Setup Guide | [How-to set up AI Factory](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/20-29/24-end-2-end-setup.md) |
| Update Guide | [How-to update AI Factory](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/20-29/26-update-AIFactory.md) |
| CAF Documentation | [AI Factory in Cloud Adoption Framework](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/ai-machine-learning-mlops) |
| WAF AI Workload | [Well-Architected Framework — AI personas](https://learn.microsoft.com/en-us/azure/well-architected/ai/personas) |
| Bootstrap Template | [AIFactory Template Repo](https://github.com/azure/enterprise-scale-aifactory) |

---

## Public References

- **Epiroc Customer Story**: [Epiroc advances manufacturing innovation with AI Factory](https://customers.microsoft.com/en-us/story/1653030140221000726-epiroc-manufacturing-azure-machine-learning)
- **Technical Blog**: [Predict steel quality with Azure AutoML in manufacturing](https://techcommunity.microsoft.com/t5/ai-machine-learning-blog/predict-steel-quality-with-azure-automl-in-manufacturing/ba-p/3616176)
