# DataOps Templates

DataOps templates provide a structured approach to data ingestion, transformation, and governance within the AI Factory.

---

## Overview

The AI Factory includes a **DataOps template** aligned with the LAMBDA architecture, enabling both batch and real-time data pipelines.

Key tools available:

| Tool | Purpose |
|---|---|
| **Azure Data Factory** | Orchestrate ETL/ELT pipelines |
| **Azure Databricks** | Large-scale data transformation and ML |
| **Microsoft Fabric / OneLake** | Modern lakehouse with Snowflake and S3 integration |
| **Event Hubs** | Real-time streaming ingestion |

---

## Datalake Design

The AI Factory provisions a structured **Data Lake** with:

- **ACL permissions** per project team — each team accesses only its own data.
- **Datamesh-ready** structure — projects can be treated as independent data domains.
- **Standard lake prefix** configurable via `commonLakeNamePrefixMax8chars` (e.g. `mrvel`).

---

## DataOps for Core Team

The Core Team's DataOps engineers (`p081_coreteam_dataops`, `p082_coreteam_dataops_fabric`) are responsible for:

- Setting up shared ingestion pipelines in the common AI Factory resource group.
- Providing curated datasets to project teams via datalake ACLs.
- Managing Fabric integration for cross-system reporting.

---

!!! info
    DataOps templates are located under `copy_my_subfolders_to_my_grandparent/mlops/` and `copy_my_subfolders_to_my_grandparent/dbx/`.
