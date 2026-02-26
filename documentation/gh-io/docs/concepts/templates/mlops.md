# MLOps Templates

The AI Factory provides MLOps templates for the **ESML** (Enterprise Scale Machine Learning) project type, enabling a full ML lifecycle within a secure, private Azure environment.

---

## ESML Architecture

The ESML project type includes:

- **Azure Machine Learning** workspace — private, with private endpoints on all dependent services.
- **AML Compute Clusters** — auto-scaling, configurable SKU and node count per environment.
- **AML Compute Instances** — for interactive development.
- **Private AKS Cluster** — for model serving at scale (Azure Arc-enabled).
- **Azure Container Registry (ACR)** — private, Premium SKU for model image storage.
- **Azure Data Factory** — for orchestrating training and batch-inference pipelines.
- **Databricks** (optional) — for large-scale feature engineering.

---

## ESML With Fabric Flavour

The ESML project type optionally integrates with **Microsoft Fabric**:

- Data scientists can work from Azure Databricks, Microsoft Fabric, or Azure Machine Learning — with the same MLOps template.
- Fabric provides a unified analytics platform with OneLake as the data foundation.

---

## MLOps Pipeline Templates

Templates are provided for:

| Template | Description |
|---|---|
| Training pipeline | AML pipeline for model training with logging and experiment tracking |
| Batch inference pipeline | Scheduled or event-driven batch scoring |
| Online inference | AKS-hosted REST endpoint with private networking |
| Model registration & promotion | Automated model registration and promotion across Dev → Stage → Prod |

---

## Compute Defaults (Overridable)

| Setting | DEV default | TEST/PROD default |
|---|---|---|
| AKS node SKU | `Standard_B4ms` | `Standard_DS13-2_v2` |
| AKS node count | 1 | 3 |
| AKS Kubernetes version | `1.33.2` | `1.33.2` |
| AML cluster max nodes | 3 | 5 |
| AML cluster SKU | `Standard_DS3_v2` | `Standard_D13_v2` |
| AML compute instance SKU | `Standard_DS11_v2` | `Standard_ND96amsr_A100_v4` |

All compute settings are overridable via `admin_aks_*` and `admin_aml_*` variables.

---

!!! info
    MLOps templates are located under `copy_my_subfolders_to_my_grandparent/mlops/`.
