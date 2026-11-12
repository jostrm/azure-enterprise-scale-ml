# DataOps templates

DataOps prepares data for your models and agents. Choose a data source, storage
target, transformation and versioning approach before running a workload.

## Watch the data flow

These lessons from the configuration wizard show the data path for each kind of workload. Choose a tab. If
your device asks for reduced motion, you get a still image.

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

    Prepare approved documents and the copies that retrieval reads. The source owner's data stays unchanged.

    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcset="../../../assets/animations/dataops-rag.png">
      <img src="../../../assets/animations/dataops-rag.gif" alt="DataOps prepares approved, traceable document content for retrieval-augmented generation." width="1400" height="967" loading="lazy">
    </picture>

    [Animated SVG](../../assets/animations/dataops-rag.svg) |
    [GIF](../../assets/animations/dataops-rag.gif) |
    [Still image](../../assets/animations/dataops-rag.png)

=== "DataOps + fine-tuning"

    Prepare an approved, versioned training dataset, with separate data for evaluation.

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

The Model Factory examples read and write a versioned data lake, with Delta tables where the scenario uses
them. Each scenario names its input folders.

## Choose the tools for the workload

Data Factory orchestrates ingestion, Databricks transforms the data, and Event Hubs carries event streams.
Switch on the ones your workload needs. To read from Fabric or OneLake, add a connection and give the
project access to the workspace. The [code templates library](../../code-templates/index.md) has templates that use
Fabric.

## Common or project storage

`use_common_datalake_storage` chooses where a workload example keeps its data: the common data lake of the
scale set, or the storage account of the project. New examples use project storage.

!!! important "Changing the setting doesn't move your data"
    When you change it, copy the data yourself and deploy the workload again, so that it reads from the new
    place.

A project writes only to its own data. To share Silver data with another project, give that project read
access or an approved copy.

## Continue

- [ML Model Factory configuration and data](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/50-ml-model-factory/readme.md)
- [Agent Factory storage and ingestion](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/readme.md)
- [MLOps](mlops.md) and [GenAIOps](genaiops.md)

<details markdown="1">
<summary>More info</summary>

Keep your configuration and your copies of the examples apart from the shared engines and from generated
output. Each scenario lists what it needs: the storage format, a hierarchical namespace, checkpoints and the
licence of its sample data.

After you assign access to a folder, test it as the person who will use it.

</details>
