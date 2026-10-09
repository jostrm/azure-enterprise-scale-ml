# Infrastructure templates

Infrastructure as Code (IaC) describes resources as versioned files. AI Factory
uses Bicep modules and supporting scripts within reviewed workflows; the
templates alone are not the complete operational process.

## Common and project infrastructure

| Source area | Role |
| --- | --- |
| `esml-common` | Shared foundation and common services |
| `esml-project` | Machine-learning project resources |
| `esml-genai-1` | Generative-AI project phases |
| `modules` | Reusable Azure resource/access modules |
| Provider templates | Azure DevOps and GitHub Actions orchestration |

The GenAI source is split into foundation, core infrastructure, cognitive
services, databases, compute, AI/ML platform, access/security, Foundry, dashboards
and integration. Provider step names/numbers can differ; use the selected
pipeline's current definitions.

## Use settings before customizing shared code

For ordinary changes, start with [Parameters](../../parameters/index.md) and
[Factory tools](../../factory-tools/19-cli-and-api-and-usage.md).
Keep customer settings outside generated template copies. Replacing templates
can overwrite local customizations if they are stored in the wrong location.

Debug switches are for deliberate diagnosis. Skipping a task does not prove its
dependencies were deployed, nor turn a partial run into a successful factory.

## Reuse existing infrastructure deliberately

Supported inputs cover existing VNet/subnets, common groups, data lake, Key Vault
and selected service integrations. Validate resource identity, permissions and
ownership; do not give two independent tools conflicting control.

[Bicep details](../../iac/bicep.md) |
[Bring your own infrastructure](../../iac/terraform.md)

<details markdown="1">
<summary>More info</summary>

[Current Bicep source](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep) |
[GHA project phases](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml) |
[ADO project jobs](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs)

Ordinary deployment, selective project-resource deletion and ordered whole-factory
teardown use different reviewed contracts. Do not infer deletion order from an
infrastructure module list.

</details>
