# Azure DevOps

Choose Azure DevOps when your team keeps its repositories, pipelines and service connections there. The
Factory, its settings and the Bicep templates are the same as with GitHub Actions.

## Start with a Factory

Create the Factory with the `ado` orchestrator: follow [Create your AI Factory](../setup/02-create-factory.md),
or [Add and update](../factory-tools/19-cli-and-api-and-usage.md) when you want to review each step yourself.

## What to have ready

| Input | What it is |
| --- | --- |
| Azure tenant and subscription | The environment you deploy to, and an identity that may deploy there. |
| Azure DevOps organization, project and repository | Where the code and the pipelines live. |
| Azure DevOps tenant | `azureDevOpsTenantId`. It can differ from the Azure `tenantId`. Keep both as they are. |
| Service connections | One for each environment you deploy, by its exact name. |
| Agent pool | A Linux pool. With private networking, its agents need a route to the private endpoints. |
| Version | The ESAF version to deploy, such as `main` or a release. |

### Service-connection parameters

| JSON/YAML key | Purpose |
| --- | --- |
| `dev_service_connection` | Dev deployment |
| `dev_seeding_kv_service_connection` | Dev seeding-vault access |
| `test_service_connection` / `test_seeding_kv_service_connection` | Stage, when selected |
| `prod_service_connection` / `prod_seeding_kv_service_connection` | Prod, when selected |

One service principal can serve several of these connections. Each connection you name must be authorized
for its pipeline. The settings that end in a secret name hold the name of a Key Vault secret, never the
secret itself.

## Follow the run

Keep the job ID that a call returns, and follow that job until it ends. Then open the pipeline run in Azure
DevOps for the details of each step. The CLI commands `workflow status` and `workflow watch` follow GitHub
runs only.

[Parameters](../parameters/index.md) |
[Add and update](../factory-tools/19-cli-and-api-and-usage.md) |
[Remove and recover](../factory-tools/20-cli-and-api-and-usage.md)

<details markdown="1">
<summary>Earlier way: the launcher scripts</summary>

A repository that was set up with v1.24 has these scripts in its root:

- `ADO-create-new-aifactory-scaleset.sh` creates a Factory with its identities, repository and pipelines.
- `ADO-update-aifactory-and-run-project.sh` updates the templates and runs the project pipeline.
- `--project-only` runs the project pipeline without updating the templates.
- `--aifactory-env dev|stage|prod` selects the environment.

Create uses version `124` unless you give another, and update keeps the version that was saved. Name `main` to
use the current development version. `--prepare-only` prepares Azure and the settings without completing the
deployment, so it does change things. All inputs are in the
[launcher reference](../parameters/advanced.md#bash-create-and-update-contract).

The variables live in `aifactory\esml-infra\azure-devops\bicep\yaml\variables\variables.yaml`. Azure
DevOps uses the YAML names, and GitHub uses its own uppercase names.

[Current ADO templates](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops) |
[Setup overview](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/20-29/24-end-2-end-setup.md)

</details>
