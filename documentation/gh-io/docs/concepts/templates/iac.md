# Infrastructure templates

Infrastructure as Code (IaC) describes Azure resources as versioned files. ESAF uses Bicep modules, and its
pipelines run them in the right order.

## Common and project infrastructure

| Source area | Role |
| --- | --- |
| `esml-common` | The common part: network, data lake, Key Vault and monitoring |
| `esml-genai-1` | The project, in phases |
| `modules` | One reusable module for each Azure service and for access |
| `copy_to_local_settings` | The Azure DevOps and GitHub Actions pipelines |

The folder names keep their history. There is one project template today, and the project pipeline deploys it
in phases: foundation, core infrastructure, AI services, databases, compute, the AI and ML platform, access,
Foundry, dashboards and integration.

## Use settings before customizing shared code

To change what is deployed, change a setting: start with [Parameters](../../parameters/index.md) and
[Add and update](../../factory-tools/19-cli-and-api-and-usage.md). Keep your settings outside the copied
templates, because an update replaces those copies.

The debug switches skip pipeline steps while you investigate a problem. Run the full pipeline again
afterwards.

## Reuse what you already have

You can point ESAF at a VNet and subnets, a common resource group, a data lake or a Key Vault that already
exist. Decide which tool owns each resource, so that two tools don't change the same one.

[Bicep details](../../iac/bicep.md) |
[Bring your own infrastructure](../../iac/terraform.md)

<details markdown="1">
<summary>More info</summary>

[Current Bicep source](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep) |
[GHA project phases](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml) |
[ADO project jobs](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs)

Deleting works in a set order, which differs from the order of deployment. Use
[Clean up](../../setup/05-clean-up.md) to delete a project, a scale set or a Factory.

</details>
