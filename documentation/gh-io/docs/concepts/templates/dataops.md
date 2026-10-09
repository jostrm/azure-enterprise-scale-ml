# DataOps templates

DataOps prepares data for your models and agents. Choose a data source, storage
target, transformation and versioning approach before running a workload.

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
