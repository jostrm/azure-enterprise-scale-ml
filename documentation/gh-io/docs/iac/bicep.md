# Bicep infrastructure

Bicep describes the Azure resources that the pipelines deploy. You change settings. ESAF runs the Bicep
modules for you.

## How a change reaches Azure

1. Choose the Factory, the scale set and the project.
2. Change the [settings](../parameters/index.md), for example switch on a service.
3. Run the change with the app, the CLI, the Python SDK or REST.
4. Follow the run until it ends, then look at the resources in Azure.

[Add and update](../factory-tools/19-cli-and-api-and-usage.md) walks through it for each tool. You only edit
Bicep when you add a service that ESAF doesn't have yet.

## Source organization

| Location under `environment_setup\aifactory\bicep` | Purpose |
| --- | --- |
| `esml-common` | The common part of a scale set |
| `esml-genai-1` | The project, deployed in phases |
| `modules` | One reusable module for each Azure service and for access |
| `copy_to_local_settings` | The Azure DevOps and GitHub Actions pipelines that are copied to your repository |
| `scripts` | Checks, settings conversion and helper steps of the pipelines |

The folder names keep their history. There is one project template today.

The `variables.json` of a project has two sections: `dev`, and `stage_prod` for Stage and Prod. See
[Every variable in variables.json](../parameters/variables.md).

## Updating what exists

Running the pipeline again updates the resources that exist and adds the services you switched on. Azure
can't change some properties in place. Such a change fails, and the log of the run gives the reason.

!!! warning "Switching a service off"
    A switched-off service that exists stays in Azure while `enableDeleteForDisabledResources` is `"false"`,
    the default. With `"true"`, the next project pipeline run deletes it. See
    [what happens when you switch a service off](../index.md#what-happens-when-you-switch-a-service-off).

## Encryption and private networking

Each service has its own settings for customer-managed keys, private endpoints, DNS and roles. Give the key
and the permissions that each switched-on service needs. See the
[Parameters reference](../parameters/advanced.md).

<details markdown="1">
<summary>More info</summary>

The modules include `aiSearch.bicep`, `keyVault.bicep`, `storageAccount.bicep` and `aksCluster.bicep`. See the
[module folder](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/modules)
for all of them.

When you attach an AKS cluster to Azure Machine Learning, the template passes the load-balancer subnet of
that cluster.

After a run succeeds, test that your users and the pipeline runner reach the services over the private
network.

</details>
