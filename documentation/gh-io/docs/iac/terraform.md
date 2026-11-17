# Bring your own infrastructure

Do you already manage shared Azure resources with Terraform? Point ESAF at those resources with the settings
below. Decide which tool owns each resource, so that your Terraform and ESAF never change the same one.

!!! note "Terraform templates for the factory foundation"
    From v1.26, ESAF has Terraform templates for the factory foundation: the common resource group, the
    common network and the common resources (Key Vaults, data lake, container registry, Log Analytics, Data
    Factory, Bastion, admin VM, private DNS). They deploy the same resources, with the same names and
    conditions, as the Bicep templates `11-rgCommon`, `12-networkCommon` and `13-rgLevel`. Projects, the AI
    gateway, Kong, FinOps, policies and dashboards are still deployed with Bicep only.

## ESAF's own Terraform templates

| Part of the factory | Terraform | Bicep |
| --- | --- | --- |
| Factory foundation (common resource group, network, common resources) | Yes, `environment_setup/aifactory/terraform/esml-common` | Yes |
| Projects (`esml-genai-1`) | Not yet: the next slice | Yes |
| AI gateway (APIM), Kong, FinOps, policies, dashboards | Not yet | Yes |

The Terraform root reads the same `variables.json` as the Bicep pipelines. The GitHub Actions template
`infra-common-terraform.yml` (in `environment_setup/aifactory/terraform/copy_to_local_settings/github-actions`)
runs it with the same inputs, identity and checks as `infra-common.yml`, keeping the state in an Azure Storage
container you name. A factory deployed with Terraform and projects deployed with Bicep work together, because
both use the same names.

Use one tool per factory. A factory that Bicep deployed first must be imported into Terraform state before
Terraform manages it. See `environment_setup/aifactory/terraform/readme.md` for the design, the providers and
what differs.

## Choose Terraform: the `iac` switch

`iac` in the factory configuration (`variables.json`, `dev`) picks the tool for the factory foundation:
`"iac": "bicep"` (the default) or `"iac": "terraform"`. Set it before the factory is first deployed; one tool
per factory, because switching needs a `terraform import`. A new scale set takes the factory's `iac`.

```json
"iac": "terraform",
"tfstateResourceGroup": "rg-aif-tfstate-sdc-001",
"tfstateStorageAccount": "staiftfstatesdc001",
"tfstateContainer": "tfstate",
"tfstateSubscriptionId": ""
```

| Key | GitHub variable of `infra-common-terraform.yml` | Default |
| --- | --- | --- |
| `tfstateResourceGroup` | `TFSTATE_RESOURCE_GROUP` | required with Terraform |
| `tfstateStorageAccount` | `TFSTATE_STORAGE_ACCOUNT` | required with Terraform |
| `tfstateContainer` | `TFSTATE_CONTAINER` | `tfstate` |
| `tfstateSubscriptionId` | `TFSTATE_SUBSCRIPTION_ID` | the target subscription |

With the Factory API (`esaf.init_factory(..., iac="terraform")`, `azurefactory esaf init-factory --iac terraform`),
the API installs `infra-common-terraform.yml` instead of `infra-common.yml`, sets those GitHub variables and runs
the factory common through the pipeline route. It refuses Terraform with Azure DevOps (only a GitHub Actions
template exists), with an accelerator that has no Terraform template (before v1.26), without the two required
state keys, or for a factory that already uses the other tool. Projects stay on Bicep until the Terraform
project slice ships. Deleting a scale set or the factory also removes its state blobs
(`aifactory/<subscription>/<common resource group>/...`). Keep the state account outside the factory, so it
survives the factory's deletion, and give the deployment identity `Storage Blob Data Contributor` on it.

## A practical split

Your platform team provides subscriptions, the hub network, DNS, storage or other common services. ESAF then
uses them through these settings.

| Input | What it identifies |
| --- | --- |
| `vnetNameFull_param`, `vnetResourceGroup_param` | Existing VNet and its resource group |
| `commonResourceGroup_param` | Common resource-group reference |
| `datalakeName_param` | Existing data-lake account |
| `kvNameFromCOMMON_param` | Existing common Key Vault |
| `BYO_subnets` and the subnet names | Use subnets that already exist |
| `centralDnsZoneByPolicyInHub` and `privDns*` settings | Central private-DNS design and location |

See [all parameters](../parameters/advanced.md) for the exact names and conditions. Give the deployment
identity access to each resource you name.

## Before you integrate

1. Agree which tool owns each resource and its state.
2. Collect the IDs, subscriptions, address ranges, DNS zones and routes.
3. Give the deployment identity only the permissions it needs.
4. Read what a Factory or project deletion removes, so that it stays away from the resources Terraform owns.
   See [Clean up](../setup/05-clean-up.md).

<details markdown="1">
<summary>More info</summary>

[Bicep](bicep.md) |
[Add and update](../factory-tools/19-cli-and-api-and-usage.md)

ESAF's Bicep templates don't read Terraform state. You name each existing resource in the settings.

</details>
