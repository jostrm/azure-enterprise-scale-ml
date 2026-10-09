# DataOps templates

DataOps prepares data for your models and agents. Choose a data source, storage
target, transformation and versioning approach before running a workload.

## Watch the data flow

These configuration-wizard lessons illustrate reusable data paths, not running
pipelines. Choose a workload below. Reduced-motion preferences show still images.

=== "DataOps"

    Follow original inputs through Bronze, Silver and Gold, with explicit
    versioning and producer/consumer ownership.

    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcset="../../../assets/animations/dataops.png">
      <img src="../../../assets/animations/dataops.gif" alt="DataOps prepares versioned data through Bronze, Silver and Gold for downstream workloads." width="1400" height="937" loading="lazy">
    </picture>

    [Animated SVG](../../assets/animations/dataops.svg) |
    [GIF](../../assets/animations/dataops.gif) |
    [Still image](../../assets/animations/dataops.png)

=== "DataOps + MLOps"

    Prepare reproducible training and inference data, keeping held-out
    evaluation data separate from training.

    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcset="../../../assets/animations/dataops-mlops.png">
      <img src="../../../assets/animations/dataops-mlops.gif" alt="DataOps feeds versioned training, evaluation and inference data into an MLOps workload." width="1400" height="910" loading="lazy">
    </picture>

    [Animated SVG](../../assets/animations/dataops-mlops.svg) |
    [GIF](../../assets/animations/dataops-mlops.gif) |
    [Still image](../../assets/animations/dataops-mlops.png)

=== "DataOps + RAG"

    Prepare approved documents and retrieval copies without changing the
    source owner's data or treating ingestion as model training.

    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcset="../../../assets/animations/dataops-rag.png">
      <img src="../../../assets/animations/dataops-rag.gif" alt="DataOps prepares approved, traceable document content for retrieval-augmented generation." width="1400" height="967" loading="lazy">
    </picture>

    [Animated SVG](../../assets/animations/dataops-rag.svg) |
    [GIF](../../assets/animations/dataops-rag.gif) |
    [Still image](../../assets/animations/dataops-rag.png)

=== "DataOps + fine-tuning"

    Prepare an approved, versioned training dataset with separate evaluation
    inputs. This lesson does not submit a fine-tuning job.

    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcset="../../../assets/animations/dataops-finetuning.png">
      <img src="../../../assets/animations/dataops-finetuning.gif" alt="DataOps prepares curated training and separate evaluation data for fine-tuning." width="1400" height="937" loading="lazy">
    </picture>

    [Animated SVG](../../assets/animations/dataops-finetuning.svg) |
    [GIF](../../assets/animations/dataops-finetuning.gif) |
    [Still image](../../assets/animations/dataops-finetuning.png)

## A reusable data path

| Stage | Purpose |
| --- | --- |
| Landing / original inputs | Keep the source version and its origin clear. |
| Bronze | Preserve the supported original input representation. |
| Silver | Clean and transform data using the selected engine and format. |
| Gold | Create the model/application-ready view and reproducible splits. |
| Inference and feedback | Track scoring inputs, outputs, checkpoints and feedback separately. |

Current model-factory examples support versioned lake configuration, Delta-based
flows and explicit compatibility paths. Select the documented scenario rather
than treating every folder as an interchangeable input.

## Choose the tools for the workload

Data Factory can orchestrate ingestion, Databricks can transform/process data,
and Event Hubs can provide event streams when configured. These resource options
do not automatically create a complete data pipeline for every source.
Fabric/OneLake integration needs its own documented connections and permissions.

## Common or project storage

`use_common_datalake_storage` chooses the existing common or project data account
in supported workload examples. New example configurations use project storage;
omitting the setting in an older configuration retains its documented behavior.

!!! important "Selection does not move data"
    Changing this setting does not copy data, provision an account, grant access
    or repoint an already-deployed agent automatically. Reconfigure and verify
    the affected workload deliberately.

Keep team access and producer/consumer ownership explicit. Sharing Silver data
through a reference or an approved copy is not permission to overwrite another
project's data.

## Continue

- [ML Model Factory configuration and data](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/50-ml-model-factory/readme.md)
- [Agent Factory storage and ingestion](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/readme.md)
- [MLOps](mlops.md) and [GenAIOps](genaiops.md)

<details markdown="1">
<summary>More info</summary>

Keep user configuration and project-specific example copies separate from
maintainer-owned shared engines and generated outputs. Dataset licensing,
private connectivity, storage format, hierarchical namespace and checkpoint
requirements vary by scenario.

Provisioning storage and assigning an ACL are different from validating the
end user's effective access. Never infer access from the existence of a folder
or a successful deployment script.

</details>
