# Azure DevOps

Choose Azure DevOps when your team uses its repositories, pipelines and service
connections. It is a provider choice, not a different Factory configuration model.

## Start with a registered factory

Use the [CLI, Python SDK or REST guide](../factory-tools/19-cli-and-api-and-usage.md)
to save configuration with the explicit `ado` orchestrator, review its binding and
separately approve deployment or supported Full bootstrap.

Selecting `ado` does not itself create a pipeline, authorize a service connection
or deploy resources. A blocked registered operation is not permission to use a
legacy launcher instead.

## Collect the right inputs

| Input | What to confirm |
| --- | --- |
| Azure tenant/subscription | The selected environment and deployment identity's permissions. |
| ADO organization/project/repository | The actual source and pipeline location. |
| ADO tenant | `azureDevOpsTenantId` can differ from Azure `tenantId`; do not change IDs merely to make them match. |
| Service connections | Exact authorized names and permissions for each environment being deployed. |
| Runner/pool | Supported OS, private connectivity and approved pool/image for the selected route. |
| Version | Matching launcher, helpers, templates and API/runtime contracts. |

Scoped registered workers use the supported Linux execution contract. Other
legacy paths can have different runner assumptions. Do not infer Azure login
from an agent being online.

### Service-connection parameters

| JSON/YAML key | Purpose |
| --- | --- |
| `dev_service_connection` | Dev deployment |
| `dev_seeding_kv_service_connection` | Dev seeding-vault access |
| `test_service_connection` / `test_seeding_kv_service_connection` | Stage, when selected |
| `prod_service_connection` / `prod_seeding_kv_service_connection` | Prod, when selected |

These names do not necessarily require separate principals for every duty, but
every referenced connection must be authorized for its intended use.
Secret-name references are not credential values.

## Follow the exact run

Preserve the confirmation/job ID and the provider run details. Check the actual
deployment result rather than treating HTTP acceptance or a local script exit
as success. The CLI's `workflow status/watch` feature is GitHub-specific;
use catalog job status and ADO's own run results for this provider.

[Parameters](../parameters/index.md) |
[Deployment/status tutorials](../factory-tools/19-cli-and-api-and-usage.md) |
[Deletion and recovery](../factory-tools/20-cli-and-api-and-usage.md)

<details markdown="1">
<summary>Alternative and Legacy ways</summary>

Existing legacy consumer repositories use the matching scripts installed at the
consumer root:

- `ADO-create-new-aifactory-scaleset.sh`: full creation flow, including potentially
  billable Azure/identity/repository changes.
- `ADO-update-aifactory-and-run-project.sh`: reviewed update/project execution.
- `--project-only`: excludes the template/library update portion; not a version
  upgrade or a blanket safety guarantee.
- `--aifactory-env dev|stage|prod`: selects the project environment.

Legacy create defaults to `124`; update normally inherits the saved version.
Use an explicit supported version, including `main` for development, when
intended. A version selection does not migrate layouts.
`--prepare-only` can change Azure and configuration; it is not a read-only
preview. Use the selected source's help and
[complete input contract](../parameters/advanced.md#bash-create-and-update-contract).

The source YAML is copied into
`aifactory\esml-infra\azure-devops\bicep\yaml\variables\variables.yaml`.
Project JSON overrides require the matching adapter; GitHub uppercase names
are not a replacement for ADO keys.

[Current ADO templates](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops) |
[Setup overview](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/20-29/24-end-2-end-setup.md)

</details>
