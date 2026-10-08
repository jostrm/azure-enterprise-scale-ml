# Bicep infrastructure

Bicep describes the Azure resources that the infrastructure pipelines deploy.
AI Factory combines shared Bicep modules with configuration, planning, approval
and operation tracking.

## Recommended workflow

1. Choose your registered factory, scale set and project.
2. Review the supported [Parameters](../parameters/index.md).
3. Save approved configuration.
4. Prepare and separately approve deployment.
5. Follow the exact run and its resulting Azure resources.

Use the [CLI, Python SDK or REST walkthrough](../factory-tools/19-cli-and-api-and-usage.md).
You do not need to edit shared Bicep for every configuration change.

## Source organization

| Location under `environment_setup\aifactory\bicep` | Purpose |
| --- | --- |
| `esml-common` | Common infrastructure |
| `esml-project` | Machine-learning project infrastructure |
| `esml-genai-1` | Phased generative-AI project infrastructure |
| `modules` | Reusable resource and access-control modules |
| `copy_to_local_settings` | Provider templates copied into consumer repositories |
| `scripts` | Validation, configuration translation and supporting operations |

The shared `variables.json` template currently has a `dev` section. A
backend-generated registered project has `dev` and `stage_prod`; these are
different formats. See [the parameter reference](../parameters/advanced.md#scope-and-authoritative-sources).

## Existing resources and incremental updates

A Bicep deployment can update existing resources, but "incremental" does not mean
"nothing else can change." Inspect the plan, naming, dependencies and existing
state. Some properties cannot be changed in place.

!!! warning "Deletion is separate"
    Disabling a flag is not a general deletion approval. Use the
    [reviewed removal workflow](../factory-tools/20-cli-and-api-and-usage.md).

## Encryption and private networking

Customer-managed encryption keys, private endpoints, DNS and role assignments
are service-specific. Provide the supported key references and permissions and
check compatibility for each enabled service. Do not assume a single switch
enables every security feature everywhere.

<details markdown="1">
<summary>More info</summary>

Actual source modules include `aiSearch.bicep`, `keyVault.bicep`,
`storageAccount.bicep` and `aksCluster.bicep`. Use the
[module directory](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/modules)
for the current names rather than guessed filenames.

Published change `940b1b48` passes an existing AKS load-balancer subnet when
attaching that cluster to Azure ML. It does not turn every AKS cluster into
a supported/private inference target without its other prerequisites.

Bootstrap also has reviewed supporting operations outside Bicep. Neither a
successful compilation nor an accepted deployment request proves that all
resources, permissions and private connectivity are working.

</details>
